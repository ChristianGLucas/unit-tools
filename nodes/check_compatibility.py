import math

from gen.axiom_context import AxiomContext
from gen.messages_pb2 import Compatibility, CompatibilityRequest
from nodes._units import (
    UnitError,
    dimensionality_name,
    guard_numeric,
    is_offset_unit,
    parse_unit,
    quantity_of,
)


def check_compatibility(ax: AxiomContext, input: CompatibilityRequest) -> Compatibility:
    """Test whether two units measure the same physical dimension and are
    therefore interconvertible, reporting both dimensionalities and — for
    multiplicative units — the factor between them.

    Two valid units that measure different things are not an error: that is the
    answer, returned as compatible=false.
    """
    try:
        unit_a = parse_unit(input.units_a, "units_a")
        unit_b = parse_unit(input.units_b, "units_b")

        dimensionality_a = dimensionality_name(unit_a)
        dimensionality_b = dimensionality_name(unit_b)
        compatible = unit_a.dimensionality == unit_b.dimensionality

        factor, factor_defined = 0.0, False
        if compatible and not is_offset_unit(unit_a) and not is_offset_unit(unit_b):
            candidate = guard_numeric(
                lambda: quantity_of(1.0, unit_a).to(unit_b).magnitude,
                "computing the factor",
            )
            if math.isfinite(candidate):
                factor, factor_defined = float(candidate), True

        return Compatibility(
            compatible=compatible,
            dimensionality_a=dimensionality_a,
            dimensionality_b=dimensionality_b,
            factor=factor,
            factor_defined=factor_defined,
        )
    except UnitError as exc:
        ax.log.info("check_compatibility rejected input", code=exc.code)
        return Compatibility(error={"code": exc.code, "message": exc.message})
