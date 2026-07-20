"""Shared unit-handling helpers for christiangeorgelucas/unit-tools.

Everything that touches Pint goes through here, so the input guards, the error
vocabulary and the canonical spelling of a unit are defined exactly once.

WHY THE GUARDS EXIST — each one is a measured behaviour of the parser, not a
precaution in the abstract:

  * ``Quantity("[1,2,3] meter")`` parses as 123 metre. Pint's expression parser
    is permissive enough to read punctuation as digits, which would silently
    turn a malformed input into a plausible wrong answer. ``_check_expression``
    rejects any character outside a conservative set instead.
  * ``Quantity("1 " + "*".join(["meter"] * 20000))`` drives the parser into
    ``RecursionError`` after ~2.5s of work. Bounding the raw expression to 256
    characters caps the operator chain at ~128, far below the interpreter's
    recursion limit, and the bound is checked BEFORE the string reaches Pint.
  * ``Quantity("1e999 meter")`` yields an infinite magnitude. Non-finite values
    are refused on the way in and on the way out, so a node never emits one.

Pint owns the algorithmically hard parts throughout: parsing unit expressions,
dimensional analysis, the ~800-entry unit registry, and offset-unit conversion.
"""

import math
import re
import unicodedata

import pint

# One registry for the whole process. A registry is read-only once built —
# nodes only look units up, never define them — so sharing it keeps nodes
# stateless while avoiding a ~0.5s rebuild per invocation.
_UREG = pint.UnitRegistry(cache_folder=None)

# Maximum length of a unit expression, in characters. See module docstring.
MAX_UNIT_LEN = 256
# Maximum length of the free text `Parse` accepts.
MAX_TEXT_LEN = 512
# Largest absolute exponent permitted on any unit in an expression.
#
# An unbounded exponent lets a caller name a unit whose conversion factor is
# not representable, and the failure is silent: converting 2 "m**1e9" to
# "km**1e9" needs a factor of 1e-3**1e9, which underflows to exactly 0.0, so
# the node would return 0 — a WRONG ANSWER, not an error. The reverse
# direction raises OverflowError from inside the maths library.
#
# 50 is far above any real unit expression (a volume is 3, an exotic tensor
# term might reach 12) and keeps every factor comfortably inside float64:
# 1e-3**50 is 1e-150, with ~150 decades of headroom.
MAX_UNIT_EXPONENT = 50

# Relative tolerance for declaring two magnitudes equal after a conversion.
#
# Conversion is floating-point, so two values that are equal by definition can
# differ in the last bits: 0 degC reduces to exactly 273.15 K, while 32 degF —
# the same temperature — reduces to 273.15000000000003 K. Comparing with `==`
# would report the second as greater, which is wrong. This tolerance is far
# looser than that error (~1e-16 relative) and far tighter than any difference
# a caller would consider meaningful.
RELATIVE_TOLERANCE = 1e-12

# Maximum decimal places `Format` will render (a float64 carries ~17
# significant digits; beyond 15 the extra places are noise).
MAX_PRECISION = 15

# Characters permitted in a unit expression: letters, digits, whitespace, and
# the operators/symbols Pint's unit grammar actually uses. Deliberately
# excludes brackets, commas, quotes and underscore-adjacent punctuation that
# the parser would coerce rather than reject.
#
# Both Unicode spellings of micro (U+00B5 MICRO SIGN, U+03BC GREEK SMALL MU)
# and ohm (U+03A9 GREEK CAPITAL OMEGA, U+2126 OHM SIGN) are accepted, because
# real-world input uses each interchangeably.
_ALLOWED_UNIT_CHARS = re.compile(r"^[0-9A-Za-z_\s.+\-*/^()%µμΩΩ°]*$")

# One number: optional sign, digits with an optional decimal point (or a bare
# leading point), and an optional exponent. Anchored at the start so `Parse`
# reads the magnitude itself instead of letting Pint's permissive parser do it.
_LEADING_NUMBER = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*)$", re.DOTALL
)


class UnitError(Exception):
    """A structured, caller-facing failure carrying an Error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _check_expression(expr: str, code: str, label: str) -> str:
    """Bound and charset-check a raw expression BEFORE it reaches the parser."""
    if not isinstance(expr, str):
        raise UnitError(code, f"{label} must be a string")
    # Unicode canonical normalisation, applied BEFORE the length check so the
    # bound is on what the parser actually sees. This is what makes U+2126
    # OHM SIGN work: it is canonically equivalent to U+03A9 GREEK CAPITAL
    # OMEGA, which is the spelling the registry defines. NFC (not NFKC) is
    # deliberate — it maps only canonically-equivalent characters and so
    # cannot change which unit an expression names.
    expr = unicodedata.normalize("NFC", expr)
    if len(expr) > MAX_UNIT_LEN:
        raise UnitError(
            code,
            f"{label} is {len(expr)} characters; the maximum is {MAX_UNIT_LEN}",
        )
    if not _ALLOWED_UNIT_CHARS.match(expr):
        bad = next(c for c in expr if not _ALLOWED_UNIT_CHARS.match(c))
        raise UnitError(
            code,
            f"{label} contains the character {bad!r}, which is not valid in a "
            f"unit expression",
        )
    return expr


def parse_unit(units: str, label: str = "units"):
    """Resolve a unit expression to a Pint Unit, or raise UnitError.

    An empty expression is dimensionless. A expression carrying a scaling
    factor (``"2*m"``, ``"5"``) is refused by Pint itself — a unit is not a
    quantity — and that refusal is surfaced as INVALID_UNIT.
    """
    units = _check_expression(units, "INVALID_UNIT", label)
    stripped = units.strip()
    if not stripped:
        return _UREG.dimensionless
    try:
        unit = _UREG.Unit(stripped)
    except UnitError:
        raise
    except Exception as exc:  # pint raises a wide family of parse errors
        raise UnitError("INVALID_UNIT", f"{label} {units!r} is not a valid unit: {exc}")
    for name, exponent in unit._units.items():
        if abs(exponent) > MAX_UNIT_EXPONENT:
            raise UnitError(
                "INVALID_UNIT",
                f"{label} raises {name!r} to the power {exponent:g}; the maximum "
                f"absolute exponent is {MAX_UNIT_EXPONENT}, because beyond it a "
                f"conversion factor is no longer representable and the result "
                f"would silently lose all precision",
            )
    return unit


def check_magnitude(value: float, label: str = "magnitude") -> float:
    """Reject a non-finite magnitude on the way in."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise UnitError("INVALID_QUANTITY", f"{label} is not a number")
    if not math.isfinite(value):
        raise UnitError(
            "INVALID_QUANTITY", f"{label} must be a finite number, got {value}"
        )
    return value


def check_result(value: float, source: float | None = None) -> float:
    """Reject a magnitude that has lost its value, on the way out.

    Two failure modes, both of which would otherwise be presented as answers:

    * OVERFLOW to infinity — ``1e308 km`` in metres. Emitting ``inf`` would
      dress an overflow up as a result.
    * UNDERFLOW to zero — a conversion whose factor is too small to represent
      collapses a non-zero quantity to exactly 0.0. That is the more dangerous
      of the two, because 0 looks like a perfectly ordinary answer. Pass
      `source` (the pre-conversion magnitude) to catch it.
    """
    value = float(value)
    if not math.isfinite(value):
        raise UnitError(
            "OVERFLOW",
            "the result is not representable as a finite number "
            "(the magnitude overflowed or is undefined)",
        )
    # NOTE: only pass `source` for a MULTIPLICATIVE conversion. On an offset
    # scale a non-zero input legitimately maps to zero — -273.15 degC is
    # exactly 0 K — so the underflow inference does not hold there.
    if source is not None and value == 0.0 and float(source) != 0.0:
        raise UnitError(
            "OVERFLOW",
            "the result underflowed to zero: the conversion factor is too "
            "small to represent, so the magnitude would lose all its value",
        )
    return value


def underflow_source(magnitude: float, *units):
    """The magnitude to pass to `check_result` as `source`, or None.

    Underflow-to-zero can only be inferred when every unit involved is
    multiplicative. On an offset scale zero is a real value that a non-zero
    input maps to (-273.15 degC is exactly 0 K), so the check must be skipped.
    """
    if any(is_offset_unit(unit) for unit in units):
        return None
    return magnitude


def guard_numeric(fn, what: str = "the computation"):
    """Run a Pint computation, turning numeric blow-ups into UnitError.

    Extreme unit exponents make the underlying maths library raise
    ``OverflowError`` rather than return ``inf``, which would otherwise escape
    a node as an unhandled traceback. `MAX_UNIT_EXPONENT` prevents the inputs
    that are known to do this; this is the backstop for the ones that are not.
    """
    try:
        return fn()
    except UnitError:
        raise
    except (OverflowError, ZeroDivisionError, ValueError) as exc:
        raise UnitError(
            "OVERFLOW", f"{what} exceeded the representable numeric range: {exc}"
        )


def quantity_from(msg, label: str = "quantity"):
    """Build a Pint Quantity from a `Quantity` message, validating both halves.

    A Quantity that ALREADY CARRIES AN ERROR is refused, and the upstream error
    is propagated unchanged. This matters because `Quantity` is both an input
    and an output type: in a flow, a failed upstream node emits a Quantity with
    `error` set and magnitude 0, units "". Without this check a downstream node
    reads that as a perfectly valid "0 dimensionless" and returns a confident,
    entirely wrong answer with no error at all — the original failure silently
    becomes the number zero.
    """
    if msg.error.code:
        raise UnitError(
            msg.error.code,
            f"{label} carries an error from an upstream node and cannot be "
            f"used as input: {msg.error.message}",
        )
    magnitude = check_magnitude(msg.magnitude, f"{label}.magnitude")
    unit = parse_unit(msg.units, f"{label}.units")
    return _UREG.Quantity(magnitude, unit)


def quantity_of(magnitude: float, unit):
    """Build a Pint Quantity from an already-validated magnitude and unit."""
    return _UREG.Quantity(magnitude, unit)


def unit_name(unit) -> str:
    """Pint's canonical spelling of a unit; empty string for dimensionless."""
    text = str(unit)
    return "" if text == "dimensionless" else text


def dimensionality_name(unit) -> str:
    """Human-readable dimensionality; empty string for dimensionless."""
    text = str(unit.dimensionality)
    return "" if text == "dimensionless" else text


def base_unit_name(unit) -> str:
    """The SI base units a unit reduces to; empty string for dimensionless."""
    return unit_name(
        guard_numeric(
            lambda: _UREG.Quantity(1.0, unit).to_base_units().units,
            "reducing to base units",
        )
    )


def is_offset_unit(unit) -> bool:
    """True when the unit measures from a non-zero zero point (degC, degF, degR).

    Determined empirically rather than by reading Pint's registry internals: a
    unit is multiplicative exactly when converting to base units is proportional,
    i.e. ``base(2x) == 2 * base(x)``. For degC that is 275.15 K vs 548.30 K, so
    the test fires; for km it is 2000 m vs 2000 m, so it does not. This matches
    the definition documented in the proto, and holds for compound expressions
    too.
    """
    try:
        one = _UREG.Quantity(1.0, unit).to_base_units().magnitude
        two = _UREG.Quantity(2.0, unit).to_base_units().magnitude
    except Exception:
        # A unit whose base conversion is undefined is not something we can
        # scale either; treat it as offset (the conservative answer).
        return True
    if not (math.isfinite(one) and math.isfinite(two)):
        return True
    return not math.isclose(two, 2.0 * one, rel_tol=1e-12, abs_tol=0.0)


def base_factor(unit):
    """(factor, defined) — how many base units 1 of this unit is.

    Undefined for an offset unit, where no single multiplicative factor
    describes the conversion.
    """
    if is_offset_unit(unit):
        return 0.0, False
    try:
        factor = float(_UREG.Quantity(1.0, unit).to_base_units().magnitude)
    except Exception:
        return 0.0, False
    if not math.isfinite(factor):
        return 0.0, False
    return factor, True


def to_error(exc: UnitError):
    """Render a UnitError as an `Error` message kwargs dict."""
    return {"code": exc.code, "message": exc.message}


def convert_quantity(q, target_unit, target_label: str = "to_units"):
    """Convert a Pint Quantity to a target unit, mapping Pint's failures.

    Dimensional mismatch is INCOMPATIBLE_UNITS and names both dimensionalities,
    because "cannot convert metres to seconds" is the answer, not a crash.
    """
    try:
        return q.to(target_unit)
    except pint.DimensionalityError:
        raise UnitError(
            "INCOMPATIBLE_UNITS",
            f"cannot convert {unit_name(q.units) or 'dimensionless'} "
            f"[{dimensionality_name(q.units) or 'dimensionless'}] to "
            f"{unit_name(target_unit) or 'dimensionless'} "
            f"[{dimensionality_name(target_unit) or 'dimensionless'}]: "
            f"they measure different dimensions",
        )
    except pint.OffsetUnitCalculusError as exc:
        raise UnitError("OFFSET_UNIT", f"ambiguous conversion for an offset unit: {exc}")
    except (OverflowError, ZeroDivisionError) as exc:
        raise UnitError(
            "OVERFLOW", f"the conversion exceeded the representable range: {exc}"
        )
    except Exception as exc:
        raise UnitError("INTERNAL", f"conversion failed unexpectedly: {exc}")


def split_quantity_text(text: str):
    """Split free text into (magnitude, unit expression), strictly.

    The magnitude is read here rather than by Pint, so that exactly one
    well-formed number is accepted and everything else is refused instead of
    coerced. The remaining unit expression is charset- and length-checked by
    `parse_unit`.
    """
    if not isinstance(text, str):
        raise UnitError("INVALID_QUANTITY", "text must be a string")
    if len(text) > MAX_TEXT_LEN:
        raise UnitError(
            "INVALID_QUANTITY",
            f"text is {len(text)} characters; the maximum is {MAX_TEXT_LEN}",
        )
    if not text.strip():
        raise UnitError("INVALID_QUANTITY", "text is empty")
    match = _LEADING_NUMBER.match(text)
    if not match:
        raise UnitError(
            "INVALID_QUANTITY",
            f"text {text[:60]!r} does not start with a number; a quantity is "
            f"written as a magnitude followed by an optional unit, e.g. '5 km/h'",
        )
    number_text, rest = match.group(1), match.group(2)
    try:
        magnitude = float(number_text)
    except ValueError:
        raise UnitError("INVALID_QUANTITY", f"{number_text!r} is not a valid number")
    if not math.isfinite(magnitude):
        raise UnitError(
            "INVALID_QUANTITY",
            f"{number_text!r} is out of range for a finite magnitude",
        )
    return magnitude, rest.strip()
