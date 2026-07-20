import pint

from gen.axiom_context import AxiomContext
from gen.messages_pb2 import ArithmeticRequest, Quantity
from nodes._units import (
    UnitError,
    guard_numeric,
    check_result,
    dimensionality_name,
    is_offset_unit,
    quantity_from,
    unit_name,
)

_OPS = ("add", "sub", "mul", "div")


def _underflow_source_for(op, left, right):
    """A non-zero `source` for check_result iff the result should be non-zero.

    Returns None (guard off) for offset operands, and for the cases where a
    zero result is mathematically legitimate rather than an underflow: an
    operand of zero magnitude. When it returns 1.0, a zero result magnitude can
    only be an underflow and is reported as OVERFLOW.
    """
    if is_offset_unit(left.units) or is_offset_unit(right.units):
        return None
    if op == "mul":
        return 1.0 if (left.magnitude != 0 and right.magnitude != 0) else None
    # div: the right magnitude is already known non-zero at this point.
    return 1.0 if left.magnitude != 0 else None


def arithmetic(ax: AxiomContext, input: ArithmeticRequest) -> Quantity:
    """Add, subtract, multiply or divide two quantities with their units
    carried through — 3 m / 1.5 s becomes 2 m/s — refusing dimensional
    mismatches and the ambiguous arithmetic on temperature scales.
    """
    try:
        left = quantity_from(input.left, "left")
        right = quantity_from(input.right, "right")

        op = input.op
        if op not in _OPS:
            raise UnitError(
                "INVALID_ARGUMENT",
                f"op {op!r} is not supported; use one of {', '.join(_OPS)}",
            )

        if op in ("add", "sub"):
            # A non-linearly-scalable unit has no proportional zero to add
            # from: "1 degC + 1 degC" could mean 2 degC or 275.3 K, and a
            # logarithmic unit like decibel does not add linearly at all. Pint
            # refuses both and so do we, rather than silently picking a reading.
            for label, operand in (("left", left), ("right", right)):
                if is_offset_unit(operand.units):
                    name = unit_name(operand.units)
                    hint = (
                        "convert to an absolute scale such as 'kelvin' first"
                        if "degree" in name
                        else "operate on its underlying linear quantity instead"
                    )
                    raise UnitError(
                        "OFFSET_UNIT",
                        f"{op} is ambiguous for {label} operand {name!r}, which "
                        f"is not linearly scalable (an offset or logarithmic "
                        f"unit); {hint}",
                    )
            try:
                result = guard_numeric(
                    lambda: left + right if op == "add" else left - right,
                    f"the {op}",
                )
            except pint.DimensionalityError:
                raise UnitError(
                    "INCOMPATIBLE_UNITS",
                    f"cannot {op} {unit_name(left.units) or 'dimensionless'} "
                    f"[{dimensionality_name(left.units) or 'dimensionless'}] and "
                    f"{unit_name(right.units) or 'dimensionless'} "
                    f"[{dimensionality_name(right.units) or 'dimensionless'}]: "
                    f"they measure different dimensions",
                )
        elif op == "mul":
            # to_reduced_units cancels units of the same dimension that would
            # otherwise survive as a ratio: without it, 1 km / 500 m returns
            # "0.002 kilometer / meter" instead of the dimensionless 2 the
            # caller asked for. It leaves genuinely distinct dimensions alone,
            # so 3 m / 1.5 s is still 2 m/s.
            result = guard_numeric(
                lambda: (left * right).to_reduced_units(), "the multiplication"
            )
        else:
            if right.magnitude == 0:
                raise UnitError(
                    "OVERFLOW", "division by a right operand with zero magnitude"
                )
            result = guard_numeric(
                lambda: (left / right).to_reduced_units(), "the division"
            )

        # A multiplicative result can underflow to exactly 0.0 just like a
        # conversion can — 1e-200 m * 1e-200 m is 1e-400 m**2 — and emitting
        # that zero with a valid unit and no error is the same silent-wrong-
        # answer the other multiplicative nodes guard against. The result is
        # mathematically zero only when an operand's magnitude is; when both
        # are non-zero (mul) or the left is non-zero (div, right already
        # non-zero) a zero magnitude means it underflowed. Offset operands are
        # skipped, as everywhere else, since there zero is a real value.
        source = _underflow_source_for(op, left, right)
        return Quantity(
            magnitude=check_result(result.magnitude, source=source),
            units=unit_name(result.units),
        )
    except UnitError as exc:
        ax.log.info("arithmetic rejected input", code=exc.code)
        return Quantity(error={"code": exc.code, "message": exc.message})
    except pint.OffsetUnitCalculusError as exc:
        # Multiplying or dividing a non-linearly-scalable unit — "degC * m", or
        # a logarithmic "decibel * m" — is ambiguous for the same reason adding
        # one is, and Pint refuses it. This MUST come before the catch-all
        # below; otherwise it is dead code and the case is mislabelled INTERNAL
        # (the caller's input is perfectly valid). The message stays generic
        # rather than naming 'kelvin', which is meaningless for a decibel.
        ax.log.info("arithmetic rejected non-scalable operand")
        return Quantity(
            error={
                "code": "OFFSET_UNIT",
                "message": (
                    f"ambiguous {input.op} involving a unit that is not "
                    f"linearly scalable (an offset scale like degC, or a "
                    f"logarithmic unit like decibel); operate on its "
                    f"underlying linear quantity instead: {exc}"
                ),
            }
        )
    except Exception as exc:
        # Last resort. A node must never surface a traceback: it would leak
        # internal paths to the caller and break the contract that every
        # failure arrives as a structured Error. INTERNAL says the fault is
        # ours, so the caller does not go debugging their own input.
        ax.log.error("arithmetic faulted", error=str(exc))
        return Quantity(
            error={
                "code": "INTERNAL",
                "message": (
                    f"the node faulted while handling this input "
                    f"({type(exc).__name__}); the input may be valid"
                ),
            }
        )
