from gen.axiom_context import AxiomContext
from gen.messages_pb2 import UnitDescription, UnitInput
from nodes._units import (
    UnitError,
    base_factor,
    base_unit_name,
    dimensionality_name,
    is_offset_unit,
    parse_unit,
    unit_name,
)


def describe_unit(ax: AxiomContext, input: UnitInput) -> UnitDescription:
    """Explain what a unit expression means — its canonical name, its physical
    dimensions, the SI base units it reduces to and by what factor, and whether
    it is an offset unit that cannot be scaled.
    """
    try:
        unit = parse_unit(input.units)
        factor, defined = base_factor(unit)
        dimensionality = dimensionality_name(unit)
        return UnitDescription(
            canonical=unit_name(unit),
            dimensionality=dimensionality,
            base_units=base_unit_name(unit),
            base_factor=factor,
            base_factor_defined=defined,
            dimensionless=(dimensionality == ""),
            offset_unit=is_offset_unit(unit),
        )
    except UnitError as exc:
        ax.log.info("describe_unit rejected input", code=exc.code)
        return UnitDescription(error={"code": exc.code, "message": exc.message})
    except Exception as exc:
        # Last resort. A node must never surface a traceback: it would leak
        # internal paths to the caller and break the contract that every
        # failure arrives as a structured Error. INTERNAL says the fault is
        # ours, so the caller does not go debugging their own input.
        ax.log.error("describe_unit faulted", error=str(exc))
        return UnitDescription(
            error={
                "code": "INTERNAL",
                "message": (
                    f"the node faulted while handling this input "
                    f"({type(exc).__name__}); the input may be valid"
                ),
            }
        )
