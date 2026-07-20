"""Independent-oracle tests.

These do NOT round-trip through Pint. Every expected value here is derived
from scratch from the defining relations of the units involved — the exact
international definitions (1 inch = 0.0254 m, 1 lb = 0.45359237 kg) and the
SI-coherent formulas — and then checked against what the nodes actually return.

A round trip (convert km->mi->km) would only show that Pint is self-consistent.
These show that Pint, as this package wraps it, agrees with the definitions.
"""

import math

from gen.messages_pb2 import ConvertRequest, CompatibilityRequest, UnitInput
from nodes.check_compatibility import check_compatibility
from nodes.convert import convert
from nodes.describe_unit import describe_unit
from nodes.testkit import assert_ok, ax, q
from nodes.to_base_units import to_base_units

# ── Defining relations, written out from first principles ──────────────────
# The international yard-and-pound agreement (1959) fixes these EXACTLY.
INCH_M = 0.0254
FOOT_M = 12 * INCH_M                      # 0.3048
YARD_M = 3 * FOOT_M                       # 0.9144
MILE_M = 5280 * FOOT_M                    # 1609.344
POUND_KG = 0.45359237
# 1 lbf is the weight of 1 lb under standard gravity, itself defined exactly.
STANDARD_GRAVITY = 9.80665                # m/s**2, exact by definition
POUND_FORCE_N = POUND_KG * STANDARD_GRAVITY
# Mechanical horsepower is DEFINED as 550 foot-pounds-force per second.
HORSEPOWER_W = 550 * FOOT_M * POUND_FORCE_N
# The US liquid gallon is defined as exactly 231 cubic inches.
GALLON_M3 = 231 * INCH_M ** 3
# Standard atmosphere, exact by definition.
ATM_PA = 101325.0
# The calorie (thermochemical) is exact by definition.
CALORIE_J = 4.184


def _close(actual: float, expected: float, rel: float = 1e-12) -> None:
    assert math.isclose(actual, expected, rel_tol=rel), (
        f"expected {expected!r}, got {actual!r} "
        f"(relative error {abs(actual - expected) / abs(expected):.3e})"
    )


def test_length_conversions_match_the_1959_definitions():
    for units, expected_metres in (
        ("inch", INCH_M),
        ("foot", FOOT_M),
        ("yard", YARD_M),
        ("mile", MILE_M),
    ):
        result = convert(ax(), ConvertRequest(quantity=q(1.0, units), to_units="meter"))
        assert_ok(result)
        assert result.units == "meter"
        _close(result.magnitude, expected_metres)


def test_mass_force_power_and_volume_match_their_definitions():
    cases = (
        ("pound", "kilogram", POUND_KG),
        ("force_pound", "newton", POUND_FORCE_N),
        ("horsepower", "watt", HORSEPOWER_W),
        ("gallon", "meter**3", GALLON_M3),
        ("atmosphere", "pascal", ATM_PA),
        ("calorie", "joule", CALORIE_J),
    )
    for units, target, expected in cases:
        result = convert(ax(), ConvertRequest(quantity=q(1.0, units), to_units=target))
        assert_ok(result)
        _close(result.magnitude, expected, rel=1e-9)


def test_temperature_conversion_matches_the_closed_form_formula():
    # F = C * 9/5 + 32, and K = C + 273.15. Both exact by definition.
    for celsius in (-273.15, -40.0, 0.0, 37.0, 100.0, 1000.0):
        fahrenheit = convert(
            ax(), ConvertRequest(quantity=q(celsius, "degC"), to_units="degF")
        )
        assert_ok(fahrenheit)
        _close(fahrenheit.magnitude, celsius * 9.0 / 5.0 + 32.0, rel=1e-9)

        kelvin = convert(
            ax(), ConvertRequest(quantity=q(celsius, "degC"), to_units="kelvin")
        )
        assert_ok(kelvin)
        _close(kelvin.magnitude, celsius + 273.15, rel=1e-9)


def test_compound_speed_conversion_composes_the_base_definitions():
    # 1 mile/hour in metres/second is MILE_M / 3600, derived independently.
    result = convert(
        ax(), ConvertRequest(quantity=q(1.0, "mile/hour"), to_units="meter/second")
    )
    assert_ok(result)
    _close(result.magnitude, MILE_M / 3600.0)


def test_base_unit_reduction_matches_the_si_coherent_derivation():
    # 1 kWh = 1000 W * 3600 s = 3.6e6 J, and a joule is coherent in SI base
    # units, so the reduced magnitude must be exactly 3_600_000.
    result = to_base_units(ax(), q(1.0, "kilowatt_hour"))
    assert_ok(result)
    _close(result.magnitude, 1000.0 * 3600.0)
    assert result.units == "kilogram * meter ** 2 / second ** 2"


def test_describe_unit_factor_matches_the_hand_derived_factor():
    result = describe_unit(ax(), UnitInput(units="mile"))
    assert_ok(result)
    assert result.canonical == "mile"
    assert result.dimensionality == "[length]"
    assert result.base_units == "meter"
    assert result.base_factor_defined
    _close(result.base_factor, MILE_M)


def test_compatibility_factor_matches_the_hand_derived_factor():
    result = check_compatibility(
        ax(), CompatibilityRequest(units_a="mile", units_b="kilometer")
    )
    assert_ok(result)
    assert result.compatible
    assert result.factor_defined
    _close(result.factor, MILE_M / 1000.0)
