from gen.axiom_context import AxiomContext
from gen.messages_pb2 import ConvertRequest, Quantity
from nodes._units import (
    UnitError,
    check_result,
    convert_quantity,
    parse_unit,
    quantity_from,
    underflow_source,
    unit_name,
)


def convert(ax: AxiomContext, input: ConvertRequest) -> Quantity:
    """Express a quantity in a different unit of the same dimension — 1 mile as
    kilometres, 100 degC as degF — reporting a dimensional mismatch as a
    structured error instead of a wrong number.
    """
    try:
        quantity = quantity_from(input.quantity)
        target = parse_unit(input.to_units, "to_units")
        converted = convert_quantity(quantity, target)
        return Quantity(
            magnitude=check_result(
                converted.magnitude,
                source=underflow_source(quantity.magnitude, quantity.units, target),
            ),
            units=unit_name(converted.units),
        )
    except UnitError as exc:
        ax.log.info("convert rejected input", code=exc.code)
        return Quantity(error={"code": exc.code, "message": exc.message})
    except Exception as exc:
        # Last resort. A node must never surface a traceback: it would leak
        # internal paths to the caller and break the contract that every
        # failure arrives as a structured Error. INTERNAL says the fault is
        # ours, so the caller does not go debugging their own input.
        ax.log.error("convert faulted", error=str(exc))
        return Quantity(
            error={
                "code": "INTERNAL",
                "message": (
                    f"the node faulted while handling this input "
                    f"({type(exc).__name__}); the input may be valid"
                ),
            }
        )
