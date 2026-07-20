import pytest

from gen.messages_pb2 import ConvertRequest
from nodes.convert import convert
from nodes.testkit import assert_error, assert_ok, ax, q


def _convert(magnitude, units, to_units):
    return convert(
        ax(), ConvertRequest(quantity=q(magnitude, units), to_units=to_units)
    )


def test_converts_a_simple_length():
    result = _convert(1.0, "mile", "kilometer")
    assert_ok(result)
    assert result.magnitude == pytest.approx(1.609344)
    assert result.units == "kilometer"


def test_converts_an_offset_temperature():
    result = _convert(100.0, "degC", "degF")
    assert_ok(result)
    assert result.magnitude == pytest.approx(212.0)
    assert result.units == "degree_Fahrenheit"


def test_converts_a_compound_unit():
    result = _convert(60.0, "mile/hour", "kilometer/hour")
    assert_ok(result)
    assert result.magnitude == pytest.approx(96.56064)
    assert result.units == "kilometer / hour"


def test_converting_to_the_same_unit_is_the_identity():
    result = _convert(7.5, "kilogram", "kg")
    assert_ok(result)
    assert result.magnitude == pytest.approx(7.5)
    assert result.units == "kilogram"


def test_reports_a_dimensional_mismatch_rather_than_a_number():
    result = _convert(1.0, "meter", "second")
    assert_error(result, "INCOMPATIBLE_UNITS")
    assert "[length]" in result.error.message
    assert "[time]" in result.error.message
    assert result.magnitude == 0.0


def test_rejects_an_unknown_target_unit():
    assert_error(_convert(1.0, "meter", "flurbles"), "INVALID_UNIT")


def test_rejects_a_non_finite_input_magnitude():
    assert_error(_convert(float("inf"), "meter", "km"), "INVALID_QUANTITY")
    assert_error(_convert(float("nan"), "meter", "km"), "INVALID_QUANTITY")


def test_reports_overflow_instead_of_emitting_infinity():
    # 1e308 km is 1e311 m, past the range of a float64.
    result = _convert(1e308, "kilometer", "meter")
    assert_error(result, "OVERFLOW")


def test_rejects_a_unit_expression_carrying_a_scaling_factor():
    # "2*m" is a quantity, not a unit; accepting it would silently double the
    # caller's magnitude.
    assert_error(_convert(1.0, "meter", "2*m"), "INVALID_UNIT")


def test_is_deterministic():
    assert _convert(1.0, "mile", "km") == _convert(1.0, "mile", "km")
