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
            # An offset unit has no zero to add from: "1 degC + 1 degC" could
            # mean 2 degC or 275.3 K. Pint refuses this and so do we, rather
            # than silently picking one reading.
            for label, operand in (("left", left), ("right", right)):
                if is_offset_unit(operand.units):
                    raise UnitError(
                        "OFFSET_UNIT",
                        f"{op} is ambiguous for {label} operand "
                        f"{unit_name(operand.units)!r}, an offset unit; convert "
                        f"to an absolute scale such as 'kelvin' first",
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

        return Quantity(
            magnitude=check_result(result.magnitude),
            units=unit_name(result.units),
        )
    except UnitError as exc:
        ax.log.info("arithmetic rejected input", code=exc.code)
        return Quantity(error={"code": exc.code, "message": exc.message})
    except pint.OffsetUnitCalculusError as exc:
        return Quantity(error={"code": "OFFSET_UNIT", "message": str(exc)})
