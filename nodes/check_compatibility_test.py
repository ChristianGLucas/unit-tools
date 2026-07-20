import pytest

from gen.messages_pb2 import CompatibilityRequest
from nodes.check_compatibility import check_compatibility
from nodes.testkit import assert_error, assert_ok, ax


def _check(a: str, b: str):
    return check_compatibility(ax(), CompatibilityRequest(units_a=a, units_b=b))


def test_reports_compatible_units_with_their_factor():
    result = _check("mile", "kilometer")
    assert_ok(result)
    assert result.compatible
    assert result.dimensionality_a == "[length]"
    assert result.dimensionality_b == "[length]"
    assert result.factor_defined
    assert result.factor == pytest.approx(1.609344)


def test_recognises_a_derived_unit_as_compatible_with_its_expansion():
    result = _check("newton", "kg*m/s**2")
    assert_ok(result)
    assert result.compatible
    assert result.factor == pytest.approx(1.0)


def test_incompatible_units_are_an_answer_not_an_error():
    result = _check("meter", "second")
    assert_ok(result)
    assert not result.compatible
    assert result.dimensionality_a == "[length]"
    assert result.dimensionality_b == "[time]"
    assert not result.factor_defined
    assert result.factor == 0.0


def test_offset_units_are_compatible_but_have_no_single_factor():
    result = _check("degC", "degF")
    assert_ok(result)
    assert result.compatible
    assert result.dimensionality_a == "[temperature]"
    # A scale with an offset zero is not described by one multiplicative factor.
    assert not result.factor_defined


def test_dimensionless_units_are_compatible_with_each_other():
    result = _check("percent", "")
    assert_ok(result)
    assert result.compatible
    assert result.dimensionality_a == ""
    assert result.factor == pytest.approx(0.01)


def test_rejects_an_unknown_unit():
    assert_error(_check("flurbles", "meter"), "INVALID_UNIT")
    assert_error(_check("meter", "flurbles"), "INVALID_UNIT")


def test_is_deterministic():
    assert _check("mile", "km") == _check("mile", "km")
