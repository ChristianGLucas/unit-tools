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
# term might reach 12). It does NOT by itself keep every factor inside float64
# — "angstrom**35" still reduces by 1e-350 — so the bound is a cheap first
# filter, and the underflow checks in `check_result` and `base_factor` are what
# actually guarantee a zero is never returned as an answer.
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

# EXPONENT TOWERS are the one cost bomb a length bound cannot catch, because
# the damage is in the VALUE, not the length. Exponentiation is
# right-associative, so every step SQUARES the exponent: "m**2**2**2**2**2**2"
# is 19 characters and reaches 2**64. Measured on this package before the
# bound: ~8s and ~900MB, and an exponent so large that merely FORMATTING it for
# the error message raised OverflowError.
#
# A first attempt matched the tower SYNTACTICALLY — "**<number>**" adjacency
# plus a cap on each literal — and parentheses walked straight through it:
# "m**(9**(9**(9)))" has no such adjacency and every literal is <= 50, yet it
# never finishes. "(((m**2)**2)**2)**2" evades it from the other side.
#
# So the rule is STRUCTURAL instead: an exponent must be a bare numeric
# literal applied to a bare unit name. Three shapes are refused outright —
# an exponent that opens a group, a group that is itself exponentiated, and
# one exponent applied to another. Together they make it impossible to write
# an exponent that is not a single literal, and the literal bound then holds.
#
# The cost of this strictness is that "(m/s)**2" must be written "m**2/s**2".
# That is a real but small loss, and it is stated in the error message.
_EXPONENT_OPENS_GROUP = re.compile(r"(?:\*\*|\^)\s*\(")
_GROUP_IS_EXPONENTIATED = re.compile(r"\)\s*(?:\*\*|\^)")
_CHAINED_EXPONENT = re.compile(
    r"(?:\*\*|\^)[^*/^()]*(?:\*\*|\^)"
)

# Every numeric literal in a unit expression is an exponent — Pint refuses a
# scaling factor outright ("2*m" is a quantity, not a unit) — so bounding the
# literals on the RAW string stops the parser ever computing a huge power.
_NUMERIC_LITERAL = re.compile(r"\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?")

# One number: optional sign, digits with an optional decimal point (or a bare
# leading point), and an optional exponent. Anchored at the start so `Parse`
# reads the magnitude itself instead of letting Pint's permissive parser do it.
#
# [0-9] rather than \d, deliberately: \d is Unicode-aware and would accept
# Arabic-Indic "٥" or Devanagari "५" as a magnitude while the unit half of the
# same string is held to a strict ASCII charset. One half-strict contract is
# worse than either consistent choice.
_LEADING_NUMBER = re.compile(
    r"^\s*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*(.*)$", re.DOTALL
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
    # Both of the following fire BEFORE the parser sees the string, because the
    # cost and the overflow both happen inside parsing.
    for pattern, shape in (
        (_EXPONENT_OPENS_GROUP, "an exponent that opens a group ('m**(2)')"),
        (_GROUP_IS_EXPONENTIATED, "a group raised to a power ('(m/s)**2')"),
        (_CHAINED_EXPONENT, "one exponent applied to another ('m**2**2')"),
    ):
        if pattern.search(expr):
            raise UnitError(
                code,
                f"{label} contains {shape}. An exponent must be a bare number "
                f"applied to a bare unit, because chained or grouped exponents "
                f"square the exponent at every step and make the expression "
                f"unboundedly expensive to evaluate. Write 'm**2/s**2' rather "
                f"than '(m/s)**2'",
            )
    for literal in _NUMERIC_LITERAL.findall(expr):
        try:
            value = float(literal)
        except (ValueError, OverflowError):
            raise UnitError(code, f"{label} contains an unreadable number {literal!r}")
        if not math.isfinite(value) or abs(value) > MAX_UNIT_EXPONENT:
            raise UnitError(
                code,
                f"{label} uses the exponent {literal}; the maximum absolute "
                f"exponent is {MAX_UNIT_EXPONENT}, because beyond it a "
                f"conversion factor is no longer representable and the result "
                f"would silently lose all its precision",
            )
    return expr


# Pint memoises parsed expressions in a plain dict keyed by the caller's
# string, and the registry is a process-wide singleton, so distinct
# expressions accumulate for the life of the worker with nothing evicting
# them. Measured: 20,000 distinct valid expressions grew the cache from 0 to
# 20,000 entries and RSS from ~44MB to ~53MB, linear and unbounded.
#
# Correctness never depended on the cache, so dropping it wholesale when it
# grows past this bound is both safe and cheap — the next lookups simply
# re-parse. This keeps a long-lived worker's memory flat under adversarial
# input without touching the hot path for ordinary traffic.
MAX_PARSE_CACHE_ENTRIES = 4096

# Marks an error that originated upstream, so a Quantity relayed across several
# nodes is annotated once rather than once per hop.
UPSTREAM_MARKER = "carries an error from an upstream node and cannot be used as input"


def _bound_parse_cache() -> None:
    """Keep the shared registry's expression cache from growing without limit."""
    try:
        cache = _UREG._cache.parse_unit
    except AttributeError:  # pragma: no cover - Pint internals moved
        return
    if len(cache) > MAX_PARSE_CACHE_ENTRIES:
        cache.clear()


def parse_unit(units: str, label: str = "units"):
    """Resolve a unit expression to a Pint Unit, or raise UnitError.

    An EMPTY expression is refused. Dimensionless must be written explicitly as
    "dimensionless", and that is a load-bearing decision rather than pedantry:

    proto3 has no field presence for scalars, so an unset — or edge-dropped —
    `Quantity` arrives as ``{magnitude: 0, units: ""}``. If "" meant
    dimensionless, that value would be a perfectly valid measurement of zero,
    and any upstream failure would silently become the number 0. A flow edge
    adapter that maps only `magnitude` and `units` (the natural way to write
    one) drops the `error` field entirely, so checking `error` alone cannot
    catch it. Making "" invalid is what closes that hole: the default value is
    no longer a plausible answer.

    An expression carrying a scaling factor (``"2*m"``, ``"5"``) is refused by
    Pint itself — a unit is not a quantity — surfaced as INVALID_UNIT.
    """
    units = _check_expression(units, "INVALID_UNIT", label)
    stripped = units.strip()
    if not stripped:
        raise UnitError(
            "INVALID_UNIT",
            f"{label} is empty; write 'dimensionless' explicitly for a "
            f"dimensionless quantity. An empty value is also what an unset or "
            f"dropped field looks like, so it is not treated as a valid unit",
        )
    try:
        unit = _UREG.Unit(stripped)
    except UnitError:
        raise
    except Exception as exc:  # pint raises a wide family of parse errors
        raise UnitError("INVALID_UNIT", f"{label} {units!r} is not a valid unit: {exc}")
    _bound_parse_cache()
    for name, exponent in unit._units.items():
        if abs(exponent) > MAX_UNIT_EXPONENT:
            raise UnitError(
                "INVALID_UNIT",
                f"{label} raises {name!r} to the power {str(exponent)[:40]}; the maximum "
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
        # Propagate the ROOT cause, annotated exactly once. Re-wrapping at
        # every hop would nest the prefix linearly with chain length, burying
        # the actual failure under repeated boilerplate in a long flow.
        message = msg.error.message
        if UPSTREAM_MARKER not in message:
            message = f"{label} {UPSTREAM_MARKER}: {message}"
        raise UnitError(msg.error.code, message)
    magnitude = check_magnitude(msg.magnitude, f"{label}.magnitude")
    unit = parse_unit(msg.units, f"{label}.units")
    return _UREG.Quantity(magnitude, unit)


def quantity_of(magnitude: float, unit):
    """Build a Pint Quantity from an already-validated magnitude and unit."""
    return _UREG.Quantity(magnitude, unit)


def unit_name(unit) -> str:
    """Pint's canonical spelling of a unit, for a Quantity's `units` field.

    Dimensionless is spelled "dimensionless", never "" — an emitted Quantity
    must be valid input to the next node, and `parse_unit` refuses "" so that a
    dropped or defaulted field cannot masquerade as a measurement of zero.
    """
    return str(unit)


def dimensionality_name(unit) -> str:
    """Human-readable dimensionality; empty string for dimensionless."""
    text = str(unit.dimensionality)
    return "" if text == "dimensionless" else text


def base_unit_name(unit) -> str:
    """The SI base units a unit reduces to; "dimensionless" if it has none.

    Spelled the same way a Quantity's `units` field is, so it can be fed
    straight back into another node.
    """
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
        # A unit whose base conversion blows up numerically is not thereby an
        # OFFSET unit — it is an extreme MULTIPLICATIVE one. Answering True
        # here used to be "conservative", but it silently disabled the
        # underflow guard (which is skipped for offset units, where zero is a
        # real value), so converting 1 "m**50" to "light_year**50" returned
        # magnitude 0 with no error at all. False is the correct answer: the
        # unit is multiplicative, and the underflow guard must stay armed.
        return False
    if not (math.isfinite(one) and math.isfinite(two)):
        return False
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
    # Zero is not a factor. "angstrom**35" reduces by 1e-350, which underflows
    # to exactly 0.0 — reporting that as base_factor=0 with
    # base_factor_defined=True would assert a wrong number is trustworthy.
    if not math.isfinite(factor) or factor == 0.0:
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
