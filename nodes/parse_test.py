import pytest

from gen.messages_pb2 import ParseRequest
from nodes import _units
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
        ("42", 42.0, "dimensionless"),         # bare number is dimensionless
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


def test_the_documented_length_bounds_are_the_actual_bounds():
    # LITERAL numbers on purpose. Importing the constant and asserting
    # "MAX + 1 is rejected" holds for any value of MAX, so it would pass even
    # if the bound were loosened to 100000 — it tests that a comparison exists,
    # not that the documented bound is enforced.
    at_limit = "1" + " " * 511                       # exactly 512 characters
    assert len(at_limit) == 512
    assert_ok(_parse(at_limit))

    over_limit = "1" + " " * 512                     # exactly 513 characters
    assert len(over_limit) == 513
    assert_error(_parse(over_limit), "INVALID_QUANTITY")

    # A unit expression inside otherwise-short text is bounded separately, at
    # 256 — see describe_unit_test, which measures that bound directly.
    assert_error(_parse("1 " + "m" * 257), "INVALID_UNIT")


def test_the_documented_constants_have_not_drifted():
    # Pins the numbers the proto and README state, so code and docs cannot
    # diverge silently.
    assert _units.MAX_TEXT_LEN == 512
    assert _units.MAX_UNIT_LEN == 256
    assert _units.MAX_UNIT_EXPONENT == 50
    assert _units.MAX_PRECISION == 15
    assert _units.RELATIVE_TOLERANCE == 1e-12


def test_rejects_non_ascii_digits_in_the_magnitude():
    # The unit half is held to a strict ASCII charset; the magnitude must be
    # too, or the contract is strict in one half and lax in the other.
    assert_error(_parse("٥ m"), "INVALID_QUANTITY")      # Arabic-Indic five
    assert_error(_parse("५ m"), "INVALID_QUANTITY")      # Devanagari five


def test_is_deterministic():
    first = _parse("5 km/h")
    second = _parse("5 km/h")
    assert first == second
