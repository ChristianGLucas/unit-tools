import pytest

from gen.messages_pb2 import UnitInput
from nodes.describe_unit import describe_unit
from nodes.testkit import assert_error, assert_ok, ax


def _describe(units: str):
    return describe_unit(ax(), UnitInput(units=units))


def test_describes_a_prefixed_length():
    result = _describe("km")
    assert_ok(result)
    assert result.canonical == "kilometer"
    assert result.dimensionality == "[length]"
    assert result.base_units == "meter"
    assert result.base_factor == pytest.approx(1000.0)
    assert result.base_factor_defined
    assert not result.dimensionless
    assert not result.offset_unit


def test_describes_a_derived_unit_by_its_canonical_name():
    result = _describe("hp")
    assert_ok(result)
    assert result.canonical == "horsepower"
    assert result.dimensionality == "[length] ** 2 * [mass] / [time] ** 3"
    assert result.base_units == "kilogram * meter ** 2 / second ** 3"
    assert result.base_factor == pytest.approx(745.6998715822702, rel=1e-9)


def test_flags_an_offset_unit_and_leaves_its_factor_undefined():
    result = _describe("degC")
    assert_ok(result)
    assert result.canonical == "degree_Celsius"
    assert result.dimensionality == "[temperature]"
    assert result.offset_unit
    # No single multiplicative factor describes a scale with an offset zero.
    assert not result.base_factor_defined
    assert result.base_factor == 0.0


def test_does_not_flag_an_absolute_temperature_as_an_offset_unit():
    result = _describe("kelvin")
    assert_ok(result)
    assert not result.offset_unit
    assert result.base_factor_defined
    assert result.base_factor == pytest.approx(1.0)


def test_describes_a_dimensionless_unit():
    result = _describe("percent")
    assert_ok(result)
    assert result.dimensionless
    assert result.dimensionality == ""
    # base_units is spelled as a UNIT expression, so it can be fed straight
    # back into another node; "" would be rejected there.
    assert result.base_units == "dimensionless"
    assert result.base_factor == pytest.approx(0.01)


def test_an_empty_expression_is_rejected_rather_than_assumed_dimensionless():
    # "" is what an unset or edge-dropped field looks like, so it must not be
    # a valid unit. Dimensionless is written explicitly.
    assert_error(_describe(""), "INVALID_UNIT")
    assert_error(_describe("   "), "INVALID_UNIT")

    result = _describe("dimensionless")
    assert_ok(result)
    assert result.dimensionless
    assert result.canonical == "dimensionless"
    assert result.base_factor == pytest.approx(1.0)


def test_rankine_is_not_an_offset_unit():
    # degR is an imperial temperature whose zero IS absolute zero, so it is
    # purely multiplicative: 1 degR = 5/9 K exactly.
    result = _describe("degR")
    assert_ok(result)
    assert result.canonical == "degree_Rankine"
    assert result.dimensionality == "[temperature]"
    assert not result.offset_unit
    assert result.base_factor_defined
    assert result.base_factor == pytest.approx(5.0 / 9.0)


def test_an_underflowing_base_factor_is_reported_as_undefined():
    # "angstrom**35" reduces by 1e-350, which underflows to exactly 0.0.
    # Reporting base_factor=0 with base_factor_defined=True would assert that
    # a wrong number is trustworthy.
    result = _describe("angstrom**35")
    assert_ok(result)
    assert result.canonical == "angstrom ** 35"
    assert not result.base_factor_defined
    assert result.base_factor == 0.0


def test_the_documented_unit_length_bound_is_the_actual_bound():
    # LITERAL 256, not the imported constant: asserting "MAX + 1 is rejected"
    # holds for any MAX and so cannot catch the bound being loosened.
    # Space-padded, so raw LENGTH is what is under test rather than the
    # exponent bound a long "m*m*m..." chain would trip first.
    at_limit = "meter" + " " * 251
    assert len(at_limit) == 256
    result = _describe(at_limit)
    assert_ok(result)
    assert result.canonical == "meter"

    over_limit = "meter" + " " * 252
    assert len(over_limit) == 257
    assert_error(_describe(over_limit), "INVALID_UNIT")


def test_rejects_an_unknown_unit():
    assert_error(_describe("flurbles"), "INVALID_UNIT")


def test_is_deterministic():
    assert _describe("kWh") == _describe("kWh")
