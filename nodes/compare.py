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

        # The RELATION is well defined for any two finite magnitudes, but their
        # ratio need not be representable: 1e200 m vs 1e-200 m orders perfectly
        # well, while the ratio is 1e400. Failing the whole comparison over an
        # unrepresentable ratio would refuse an ordinary question, so an
        # overflowing ratio is reported as undefined and the relation stands.
        ratio, ratio_defined = 0.0, False
        if right_magnitude != 0:
            candidate = left_magnitude / right_magnitude
            if math.isfinite(candidate) and candidate != 0.0:
                ratio, ratio_defined = candidate, True

        return Comparison(
            relation=relation,
            ratio=ratio,
            ratio_defined=ratio_defined,
            common_units=unit_name(left_base.units),
        )
    except UnitError as exc:
        ax.log.info("compare rejected input", code=exc.code)
        return Comparison(error={"code": exc.code, "message": exc.message})
    except Exception as exc:
        # Last resort. A node must never surface a traceback: it would leak
        # internal paths to the caller and break the contract that every
        # failure arrives as a structured Error. INTERNAL says the fault is
        # ours, so the caller does not go debugging their own input.
        ax.log.error("compare faulted", error=str(exc))
        return Comparison(
            error={
                "code": "INTERNAL",
                "message": (
                    f"the node faulted while handling this input "
                    f"({type(exc).__name__}); the input may be valid"
                ),
            }
        )
