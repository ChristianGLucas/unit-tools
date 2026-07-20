from gen.axiom_context import AxiomContext
from gen.messages_pb2 import ParseRequest, Quantity
from nodes._units import UnitError, parse_unit, split_quantity_text, unit_name


def parse(ax: AxiomContext, input: ParseRequest) -> Quantity:
    """Read a written quantity such as "5 km/h" or "9.81 m/s**2" into a
    magnitude and a canonical unit, rejecting anything that is not exactly one
    number followed by a unit rather than guessing at malformed text.
    """
    try:
        magnitude, unit_text = split_quantity_text(input.text)
        # A bare number ("42") is dimensionless. Unlike an empty `units` FIELD
        # — which is indistinguishable from unset or edge-dropped, and so is
        # refused — this emptiness is an explicit statement by the caller: they
        # wrote a number and no unit. Parse resolves it to the explicit
        # spelling, so the Quantity it emits is valid input downstream.
        unit = parse_unit(unit_text or "dimensionless", "text unit")
        return Quantity(magnitude=magnitude, units=unit_name(unit))
    except UnitError as exc:
        ax.log.info("parse rejected input", code=exc.code)
        return Quantity(error={"code": exc.code, "message": exc.message})
    except Exception as exc:
        # Last resort. A node must never surface a traceback: it would leak
        # internal paths to the caller and break the contract that every
        # failure arrives as a structured Error. INTERNAL says the fault is
        # ours, so the caller does not go debugging their own input.
        ax.log.error("parse faulted", error=str(exc))
        return Quantity(
            error={
                "code": "INTERNAL",
                "message": (
                    f"the node faulted while handling this input "
                    f"({type(exc).__name__}); the input may be valid"
                ),
            }
        )
