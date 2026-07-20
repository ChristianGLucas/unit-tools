from gen.axiom_context import AxiomContext
from gen.messages_pb2 import Quantity
from nodes._units import (
    UnitError,
    check_result,
    guard_numeric,
    quantity_from,
    underflow_source,
    unit_name,
)


def to_base_units(ax: AxiomContext, input: Quantity) -> Quantity:
    """Reduce a quantity to SI base units — 1 horsepower becomes
    745.7 kg*m**2/s**3 — giving any two quantities of the same dimension a
    common form to be compared or combined in.
    """
    try:
        quantity = quantity_from(input)
        reduced = guard_numeric(quantity.to_base_units, "reducing to base units")
        return Quantity(
            magnitude=check_result(
                reduced.magnitude,
                source=underflow_source(quantity.magnitude, quantity.units),
            ),
            units=unit_name(reduced.units),
        )
    except UnitError as exc:
        ax.log.info("to_base_units rejected input", code=exc.code)
        return Quantity(error={"code": exc.code, "message": exc.message})
    except Exception as exc:
        # Last resort. A node must never surface a traceback: it would leak
        # internal paths to the caller and break the contract that every
        # failure arrives as a structured Error. INTERNAL says the fault is
        # ours, so the caller does not go debugging their own input.
        ax.log.error("to_base_units faulted", error=str(exc))
        return Quantity(
            error={
                "code": "INTERNAL",
                "message": (
                    f"the node faulted while handling this input "
                    f"({type(exc).__name__}); the input may be valid"
                ),
            }
        )
