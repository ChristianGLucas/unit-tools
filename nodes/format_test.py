import pytest

from gen.messages_pb2 import FormatRequest
from nodes.format import format
from nodes.testkit import assert_error, assert_ok, ax, q


def _format(quantity, style="", precision=None):
    request = FormatRequest(quantity=quantity, style=style)
    if precision is not None:
        request.precision = precision
        request.use_precision = True
    return format(ax(), request)


def test_default_style_spells_the_unit_out():
    result = _format(q(5.0, "km/h"))
    assert_ok(result)
    assert result.text == "5.000000 kilometer / hour"


def test_compact_style_uses_symbols():
    result = _format(q(5.0, "km/h"), style="compact", precision=2)
    assert_ok(result)
    assert result.text == "5.00 km/h"


def test_pretty_style_renders_unicode_exponents():
    result = _format(q(9.81, "m/s**2"), style="pretty", precision=2)
    assert_ok(result)
    assert "²" in result.text
    assert result.text.startswith("9.81")


def test_precision_zero_is_honoured_rather_than_treated_as_unset():
    result = _format(q(5.4, "meter"), precision=0)
    assert_ok(result)
    assert result.text == "5 meter"


def test_a_dimensionless_quantity_renders_with_an_explicit_unit():
    result = _format(q(0.5, "dimensionless"), precision=1)
    assert_ok(result)
    assert result.text == "0.5 dimensionless"


def test_rejects_an_empty_unit_rather_than_assuming_dimensionless():
    assert_error(_format(q(0.5, "")), "INVALID_UNIT")


def test_compact_and_pretty_differ_only_in_exponent_rendering():
    # They are documented as distinct styles; for a unit with no exponent they
    # are identical, and that is worth pinning so the docs stay honest.
    for units in ("km/h", "degC", "percent"):
        compact = _format(q(5.0, units), style="compact", precision=2)
        pretty = _format(q(5.0, units), style="pretty", precision=2)
        assert_ok(compact)
        assert compact.text == pretty.text

    compact = _format(q(9.81, "m/s**2"), style="compact", precision=2)
    pretty = _format(q(9.81, "m/s**2"), style="pretty", precision=2)
    assert compact.text == "9.81 m/s**2"
    assert pretty.text == "9.81 m/s\u00b2"


def test_rejects_an_unknown_style():
    assert_error(_format(q(1.0, "m"), style="latex"), "INVALID_ARGUMENT")


def test_rejects_precision_outside_the_documented_range():
    assert_error(_format(q(1.0, "m"), precision=-1), "INVALID_ARGUMENT")
    assert_error(_format(q(1.0, "m"), precision=16), "INVALID_ARGUMENT")
    assert_ok(_format(q(1.0, "m"), precision=15))


def test_rejects_an_unknown_unit():
    assert_error(_format(q(1.0, "flurbles")), "INVALID_UNIT")


def test_rejects_a_non_finite_magnitude():
    assert_error(_format(q(float("nan"), "m")), "INVALID_QUANTITY")


def test_is_deterministic():
    assert _format(q(5.0, "km/h")) == _format(q(5.0, "km/h"))
