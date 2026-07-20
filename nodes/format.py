from gen.axiom_context import AxiomContext
from gen.messages_pb2 import FormatRequest, FormattedQuantity
from nodes._units import MAX_PRECISION, UnitError, guard_numeric, quantity_from

# Style name -> Pint format spec for the unit half. "D" is Pint's default
# (spelled-out) spelling, "~C" the compact symbol form, "~P" the pretty form
# with unicode exponents.
_STYLES = {
    "": "D",
    "default": "D",
    "compact": "~C",
    "pretty": "~P",
}


def format(ax: AxiomContext, input: FormatRequest) -> FormattedQuantity:
    """Render a quantity as human-readable text at a chosen precision and unit
    style — spelled out ("kilometer / hour"), compact ("km/h"), or pretty with
    unicode exponents. Precision defaults to 6, so 5 km/h renders
    "5.000000 kilometer / hour".
    """
    try:
        quantity = quantity_from(input.quantity)

        style = input.style or ""
        if style not in _STYLES:
            raise UnitError(
                "INVALID_ARGUMENT",
                f"style {style!r} is not supported; use one of "
                f"'default', 'compact', 'pretty'",
            )

        precision = input.precision if input.use_precision else 6
        if precision < 0 or precision > MAX_PRECISION:
            raise UnitError(
                "INVALID_ARGUMENT",
                f"precision must be between 0 and {MAX_PRECISION}, got {precision}",
            )

        return FormattedQuantity(
            text=guard_numeric(
                lambda: f"{quantity:.{precision}f{_STYLES[style]}}", "rendering"
            ),
        )
    except UnitError as exc:
        ax.log.info("format rejected input", code=exc.code)
        return FormattedQuantity(error={"code": exc.code, "message": exc.message})
    except Exception as exc:
        # Last resort. A node must never surface a traceback: it would leak
        # internal paths to the caller and break the contract that every
        # failure arrives as a structured Error. INTERNAL says the fault is
        # ours, so the caller does not go debugging their own input.
        ax.log.error("format faulted", error=str(exc))
        return FormattedQuantity(
            error={
                "code": "INTERNAL",
                "message": (
                    f"the node faulted while handling this input "
                    f"({type(exc).__name__}); the input may be valid"
                ),
            }
        )
