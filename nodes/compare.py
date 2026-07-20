import math

from gen.axiom_context import AxiomContext
from gen.messages_pb2 import Comparison, CompareRequest
from nodes._units import (
    RELATIVE_TOLERANCE,
    UnitError,
    check_result,
    convert_quantity,
    guard_numeric,
    quantity_from,
    underflow_source,
    unit_name,
)


def compare(ax: AxiomContext, input: CompareRequest) -> Comparison:
    """Order two quantities that may be written in different units — is 1 mile
    more than 1.5 km? — by reducing both to their shared SI base unit and
    reporting the relation and the ratio between them.
    """
    try:
        left = quantity_from(input.left, "left")
        right = quantity_from(input.right, "right")

        # Reduce both to base units so the comparison never depends on which
        # side's unit happened to be chosen as the reference. This also gives
        # offset units (degC vs degF) a shared absolute scale (kelvin).
        left_base = guard_numeric(left.to_base_units, "reducing the left operand")
        right_reduced = guard_numeric(right.to_base_units, "reducing the right operand")
        # convert_quantity turns a dimensional mismatch into INCOMPATIBLE_UNITS
        # naming both dimensionalities, rather than a bare exception.
        right_base = convert_quantity(right_reduced, left_base.units)

        left_magnitude = check_result(
            left_base.magnitude, source=underflow_source(left.magnitude, left.units)
        )
        right_magnitude = check_result(
            right_base.magnitude, source=underflow_source(right.magnitude, right.units)
        )

        # Equality is judged within a relative tolerance, not by ==. Conversion
        # is floating-point: 0 degC reduces to exactly 273.15 K while 32 degF —
        # the same temperature — reduces to 273.15000000000003 K, and an exact
        # comparison would call the second one greater.
        if math.isclose(
            left_magnitude, right_magnitude, rel_tol=RELATIVE_TOLERANCE, abs_tol=0.0
        ):
            relation = "eq"
        elif left_magnitude < right_magnitude:
            relation = "lt"
        else:
            relation = "gt"

        if right_magnitude == 0:
            ratio, ratio_defined = 0.0, False
        else:
            ratio, ratio_defined = check_result(left_magnitude / right_magnitude), True

        return Comparison(
            relation=relation,
            ratio=ratio,
            ratio_defined=ratio_defined,
            common_units=unit_name(left_base.units),
        )
    except UnitError as exc:
        ax.log.info("compare rejected input", code=exc.code)
        return Comparison(error={"code": exc.code, "message": exc.message})
