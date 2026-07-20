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
        unit = parse_unit(unit_text, "text unit")
        return Quantity(magnitude=magnitude, units=unit_name(unit))
    except UnitError as exc:
        ax.log.info("parse rejected input", code=exc.code)
        return Quantity(error={"code": exc.code, "message": exc.message})
