import pytest

from gen.messages_pb2 import ParseRequest
from nodes._units import MAX_TEXT_LEN, MAX_UNIT_LEN
from nodes.parse import parse
from nodes.testkit import assert_error, assert_ok, ax


def _parse(text: str):
    return parse(ax(), ParseRequest(text=text))


@pytest.mark.parametrize(
    "text,magnitude,units",
    [
        ("5 km/h", 5.0, "kilometer / hour"),
        ("9.81 m/s**2", 9.81, "meter / second ** 2"),
        ("-3.2e4 J", -32000.0, "joule"),
        ("+7 kg", 7.0, "kilogram"),
        (".5 mile", 0.5, "mile"),
        ("42", 42.0, ""),                      # bare number is dimensionless
        ("1kg", 1.0, "kilogram"),              # no space required
        ("  2.5   degC  ", 2.5, "degree_Celsius"),
        ("100 metres", 100.0, "meter"),        # alias canonicalised
        ("1 kg*m/s**2", 1.0, "kilogram * meter / second ** 2"),
    ],
)
def test_parses_well_formed_quantities(text, magnitude, units):
    result = _parse(text)
    assert_ok(result)
    assert result.magnitude == pytest.approx(magnitude)
    assert result.units == units


def test_rejects_punctuation_the_parser_would_silently_coerce():
    # Pint reads "[1,2,3] meter" as 123 metre. Guessing a magnitude out of
    # punctuation is exactly the failure this node exists to prevent, so it
    # must be an error rather than a plausible wrong answer.
    assert_error(_parse("[1,2,3] meter"), "INVALID_QUANTITY")
    assert_error(_parse("{4} meter"), "INVALID_QUANTITY")


def test_rejects_text_with_no_leading_number():
    for text in ("km/h", "", "   ", "abc", "meter 5"):
        assert_error(_parse(text), "INVALID_QUANTITY")


def test_rejects_an_unknown_unit():
    assert_error(_parse("5 flurbles"), "INVALID_UNIT")


def test_rejects_a_magnitude_that_is_not_finite():
    assert_error(_parse("1e999 meter"), "INVALID_QUANTITY")
    assert_error(_parse("inf meter"), "INVALID_QUANTITY")
    assert_error(_parse("nan meter"), "INVALID_QUANTITY")


def test_rejects_text_beyond_the_documented_length_bound():
    assert_ok(_parse("1 " + "meter"))
    assert_error(_parse("1 " + "m" * (MAX_TEXT_LEN + 1)), "INVALID_QUANTITY")
    # A unit expression inside otherwise-short text is bounded separately.
    assert_error(_parse("1 " + "m" * (MAX_UNIT_LEN + 1)), "INVALID_UNIT")


def test_is_deterministic():
    first = _parse("5 km/h")
    second = _parse("5 km/h")
    assert first == second
