import pytest

from gen.messages_pb2 import CompareRequest
from nodes.compare import compare
from nodes.testkit import assert_error, assert_ok, ax, q


def _cmp(left, right):
    return compare(ax(), CompareRequest(left=left, right=right))


def test_orders_quantities_across_different_units():
    # 1 mile is 1.609344 km, so it is greater than 1.5 km.
    result = _cmp(q(1.0, "mile"), q(1.5, "kilometer"))
    assert_ok(result)
    assert result.relation == "gt"
    assert result.common_units == "meter"
    assert result.ratio_defined
    assert result.ratio == pytest.approx(1609.344 / 1500.0)


def test_detects_equality_across_units():
    result = _cmp(q(1000.0, "meter"), q(1.0, "kilometer"))
    assert_ok(result)
    assert result.relation == "eq"
    assert result.ratio == pytest.approx(1.0)


def test_detects_less_than():
    result = _cmp(q(30.0, "minute"), q(1.0, "hour"))
    assert_ok(result)
    assert result.relation == "lt"
    assert result.ratio == pytest.approx(0.5)


def test_compares_offset_temperatures_on_a_shared_absolute_scale():
    # 0 degC is 273.15 K; 32 degF is the same instant, so they are equal.
    result = _cmp(q(0.0, "degC"), q(32.0, "degF"))
    assert_ok(result)
    assert result.relation == "eq"
    assert result.common_units == "kelvin"
    assert result.ratio == pytest.approx(1.0)


def test_refuses_to_order_incompatible_dimensions():
    result = _cmp(q(1.0, "meter"), q(1.0, "kilogram"))
    assert_error(result, "INCOMPATIBLE_UNITS")
    assert "[length]" in result.error.message
    assert "[mass]" in result.error.message


def test_ratio_is_undefined_against_a_zero_right_operand():
    result = _cmp(q(1.0, "meter"), q(0.0, "meter"))
    assert_ok(result)
    assert result.relation == "gt"
    assert not result.ratio_defined
    assert result.ratio == 0.0


def test_rejects_a_non_finite_operand():
    assert_error(_cmp(q(float("inf"), "m"), q(1.0, "m")), "INVALID_QUANTITY")


def test_rejects_an_unknown_unit():
    assert_error(_cmp(q(1.0, "flurbles"), q(1.0, "m")), "INVALID_UNIT")


def test_is_deterministic():
    assert _cmp(q(1.0, "mile"), q(1.5, "km")) == _cmp(q(1.0, "mile"), q(1.5, "km"))
