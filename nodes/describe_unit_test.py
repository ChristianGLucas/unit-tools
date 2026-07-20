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
    assert result.base_units == ""
    assert result.base_factor == pytest.approx(0.01)


def test_an_empty_expression_is_dimensionless():
    result = _describe("")
    assert_ok(result)
    assert result.dimensionless
    assert result.canonical == ""
    assert result.base_factor == pytest.approx(1.0)


def test_rejects_an_unknown_unit():
    assert_error(_describe("flurbles"), "INVALID_UNIT")


def test_is_deterministic():
    assert _describe("kWh") == _describe("kWh")
