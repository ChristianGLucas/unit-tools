import pytest

from gen.messages_pb2 import ArithmeticRequest
from nodes.arithmetic import arithmetic
from nodes.testkit import assert_error, assert_ok, ax, q


def _op(left, op, right):
    return arithmetic(ax(), ArithmeticRequest(left=left, op=op, right=right))


def test_adds_quantities_written_in_different_units():
    # 1 km + 500 m = 1.5 km, expressed in the LEFT operand's unit.
    result = _op(q(1.0, "kilometer"), "add", q(500.0, "meter"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(1.5)
    assert result.units == "kilometer"


def test_subtracts_quantities():
    result = _op(q(1.0, "hour"), "sub", q(30.0, "minute"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(0.5)
    assert result.units == "hour"


def test_multiplication_combines_the_units():
    result = _op(q(3.0, "meter"), "mul", q(4.0, "meter"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(12.0)
    assert result.units == "meter ** 2"


def test_division_produces_a_rate():
    result = _op(q(3.0, "meter"), "div", q(1.5, "second"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(2.0)
    assert result.units == "meter / second"


def test_division_of_compatible_units_is_dimensionless():
    result = _op(q(1.0, "kilometer"), "div", q(500.0, "meter"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(2.0)
    assert result.units == "dimensionless"


def test_multiplication_reduces_units_of_the_same_dimension():
    # 3 m * 4 m = 12 m**2 is a no-op for reduction, so it cannot show that
    # reduction happens. These can: without .to_reduced_units() the first
    # returns 500.0 "kilometer * meter" and the second 6.0 "hour * second".
    result = _op(q(1.0, "kilometer"), "mul", q(500.0, "meter"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(500000.0)
    assert result.units == "meter ** 2"

    result = _op(q(2.0, "hour"), "mul", q(3.0, "second"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(21600.0)
    assert result.units == "second ** 2"


def test_rankine_is_absolute_and_so_its_arithmetic_is_permitted():
    # degR is an imperial temperature, but its zero IS absolute zero, so it is
    # purely multiplicative and adding it is unambiguous. Grouping it with
    # degC/degF would be wrong.
    result = _op(q(1.0, "degR"), "add", q(1.0, "degR"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(2.0)
    assert result.units == "degree_Rankine"


def test_refuses_to_add_incompatible_dimensions():
    result = _op(q(1.0, "meter"), "add", q(1.0, "second"))
    assert_error(result, "INCOMPATIBLE_UNITS")
    assert "[length]" in result.error.message
    assert "[time]" in result.error.message


def test_refuses_ambiguous_arithmetic_on_offset_units():
    # "1 degC + 1 degC" could mean 2 degC or 275.3 K. Neither reading may be
    # picked silently.
    assert_error(_op(q(1.0, "degC"), "add", q(1.0, "degC")), "OFFSET_UNIT")
    assert_error(_op(q(1.0, "kelvin"), "add", q(1.0, "degF")), "OFFSET_UNIT")
    assert_error(_op(q(20.0, "degC"), "sub", q(5.0, "degC")), "OFFSET_UNIT")


def test_absolute_temperatures_add_normally():
    result = _op(q(1.0, "kelvin"), "add", q(1.0, "kelvin"))
    assert_ok(result)
    assert result.magnitude == pytest.approx(2.0)
    assert result.units == "kelvin"


def test_rejects_an_unknown_operator():
    for op in ("pow", "", "ADD", "__import__"):
        assert_error(_op(q(1.0, "m"), op, q(1.0, "m")), "INVALID_ARGUMENT")


def test_division_by_zero_is_an_overflow_not_an_infinity():
    # Asserts the CONTRACT, not the explicit guard branch: removing the
    # `right.magnitude == 0` check leaves this passing, because check_result
    # catches the resulting infinity by another route. Both paths are
    # deliberate, and this pins the caller-visible outcome of either.
    result = _op(q(1.0, "meter"), "div", q(0.0, "second"))
    assert_error(result, "OVERFLOW")


def test_rejects_a_non_finite_operand():
    assert_error(_op(q(float("nan"), "m"), "add", q(1.0, "m")), "INVALID_QUANTITY")
    assert_error(_op(q(1.0, "m"), "add", q(float("inf"), "m")), "INVALID_QUANTITY")


def test_reports_overflow_instead_of_emitting_infinity():
    result = _op(q(1e308, "meter"), "mul", q(1e308, "meter"))
    assert_error(result, "OVERFLOW")


def test_is_deterministic():
    a = _op(q(3.0, "m"), "div", q(1.5, "s"))
    b = _op(q(3.0, "m"), "div", q(1.5, "s"))
    assert a == b
