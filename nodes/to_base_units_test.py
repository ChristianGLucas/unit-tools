import pytest

from nodes.testkit import assert_error, assert_ok, ax, q
from nodes.to_base_units import to_base_units


def test_reduces_a_derived_unit_to_si_base_units():
    result = to_base_units(ax(), q(1.0, "newton"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(1.0)
    assert result.units == "kilogram * meter / second ** 2"


def test_reduces_a_prefixed_unit_and_scales_the_magnitude():
    result = to_base_units(ax(), q(2.5, "kilometer"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(2500.0)
    assert result.units == "meter"


def test_reduces_an_offset_temperature_to_absolute_kelvin():
    result = to_base_units(ax(), q(0.0, "degC"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(273.15)
    assert result.units == "kelvin"


def test_a_dimensionless_quantity_reduces_to_an_empty_unit():
    result = to_base_units(ax(), q(5.0, "percent"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(0.05)
    assert result.units == ""


def test_rejects_an_unknown_unit():
    assert_error(to_base_units(ax(), q(1.0, "flurbles")), "INVALID_UNIT")


def test_rejects_a_non_finite_magnitude():
    assert_error(to_base_units(ax(), q(float("inf"), "meter")), "INVALID_QUANTITY")


def test_is_deterministic():
    assert to_base_units(ax(), q(1.0, "hp")) == to_base_units(ax(), q(1.0, "hp"))
