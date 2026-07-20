"""Hostile-input tests.

Each case here is a MEASURED behaviour of the underlying parser that would be a
defect if it reached a caller — coercion of punctuation into digits, unbounded
recursion on long operator chains, non-finite magnitudes. The guards in
`_units` exist for these inputs; these tests are what keeps them honest.

Every node must answer a hostile input with a structured error, promptly, and
without raising.
"""

import time

import pytest

from gen.messages_pb2 import (
    Quantity,
    ArithmeticRequest,
    CompareRequest,
    CompatibilityRequest,
    ConvertRequest,
    FormatRequest,
    ParseRequest,
    UnitInput,
)
from nodes import _units
from nodes._units import MAX_UNIT_LEN, is_offset_unit, parse_unit
from nodes.arithmetic import arithmetic
from nodes.check_compatibility import check_compatibility
from nodes.compare import compare
from nodes.convert import convert
from nodes.describe_unit import describe_unit
from nodes.format import format as format_node
from nodes.parse import parse
from nodes.testkit import ax, q
from nodes.to_base_units import to_base_units

# Inputs chosen to attack the parser rather than the domain: code injection,
# resource exhaustion, and punctuation the parser coerces.
HOSTILE_UNITS = [
    '__import__("os").system("echo pwned")',
    "open('/etc/passwd').read()",
    "eval('1+1')",
    "meter.__class__.__mro__",
    "[1,2,3]",
    "{'a': 1}",
    "meter; import os",
    "m" + "*m" * 20000,            # drove the parser into RecursionError
    "(" * 5000 + "m" + ")" * 5000,  # deep nesting
    "m" * (MAX_UNIT_LEN + 1),
    "\x00meter",
    "meter\n\nflurbles",
    "1e999 * meter",
]


def _every_node_call(units: str):
    """Every entry point that accepts a caller-supplied unit expression."""
    return (
        lambda: parse(ax(), ParseRequest(text="1 " + units)),
        lambda: convert(ax(), ConvertRequest(quantity=q(1.0, units), to_units="m")),
        lambda: convert(ax(), ConvertRequest(quantity=q(1.0, "m"), to_units=units)),
        lambda: to_base_units(ax(), q(1.0, units)),
        lambda: format_node(ax(), FormatRequest(quantity=q(1.0, units))),
        lambda: arithmetic(
            ax(), ArithmeticRequest(left=q(1.0, units), op="add", right=q(1.0, "m"))
        ),
        lambda: compare(ax(), CompareRequest(left=q(1.0, units), right=q(1.0, "m"))),
        lambda: describe_unit(ax(), UnitInput(units=units)),
        lambda: check_compatibility(
            ax(), CompatibilityRequest(units_a=units, units_b="m")
        ),
    )


@pytest.mark.parametrize("units", HOSTILE_UNITS)
def test_every_node_rejects_hostile_units_with_a_structured_error(units):
    for call in _every_node_call(units):
        result = call()          # must not raise
        assert result.error.code, (
            f"hostile input {units[:40]!r} was ACCEPTED by {call} "
            f"instead of being rejected"
        )
        assert result.error.message


@pytest.mark.parametrize("units", HOSTILE_UNITS)
def test_hostile_input_is_rejected_promptly(units):
    # The 20k-operator chain took ~2.5s inside the parser before failing. The
    # guard must fire on the RAW string, before any parsing, so rejection is
    # effectively instant.
    start = time.monotonic()
    for call in _every_node_call(units):
        call()
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"rejecting {units[:40]!r} took {elapsed:.2f}s"


def test_an_expression_at_exactly_the_length_bound_is_still_accepted():
    # The bound must reject what is over it without rejecting what is under it.
    units = "*".join(["meter"] * 42)          # 251 characters
    assert len(units) <= MAX_UNIT_LEN
    result = describe_unit(ax(), UnitInput(units=units))
    assert not result.error.code, result.error.message
    assert result.dimensionality == "[length] ** 42"


EXTREME_EXPONENT_UNITS = ["m**1e9", "km**1e9", "m**-1e9", "s**200", "meter ** 1e+09"]


def test_an_errored_quantity_input_propagates_instead_of_reading_as_zero():
    # Quantity is both an input and an output type, so in a flow a failed
    # upstream node hands the next node a Quantity with error set, magnitude 0
    # and units "". Read naively that is a valid "0 dimensionless", and the
    # downstream node returns a confident wrong answer with no error at all.
    broken = Quantity(
        magnitude=0.0,
        units="",
        error={"code": "INVALID_UNIT", "message": "'flurbles' is not defined"},
    )
    consumers = (
        lambda: convert(ax(), ConvertRequest(quantity=broken, to_units="meter")),
        lambda: to_base_units(ax(), broken),
        lambda: format_node(ax(), FormatRequest(quantity=broken)),
        lambda: arithmetic(
            ax(), ArithmeticRequest(left=broken, op="add", right=q(1.0, "m"))
        ),
        lambda: arithmetic(
            ax(), ArithmeticRequest(left=q(1.0, "m"), op="add", right=broken)
        ),
        lambda: compare(ax(), CompareRequest(left=broken, right=q(1.0, "m"))),
        lambda: compare(ax(), CompareRequest(left=q(1.0, "m"), right=broken)),
    )
    for call in consumers:
        result = call()
        assert result.error.code == "INVALID_UNIT", (
            f"an errored input Quantity was treated as valid: got "
            f"{result.error.code or '<no error, ACCEPTED>'}"
        )
        # The upstream cause must survive, not be replaced by a generic message.
        assert "flurbles" in result.error.message
        assert "upstream" in result.error.message


@pytest.mark.parametrize("units", EXTREME_EXPONENT_UNITS)
def test_extreme_unit_exponents_are_rejected_not_silently_miscomputed(units):
    # Converting 2 "m**1e9" to "km**1e9" needs a factor of 1e-3**1e9, which
    # underflows to exactly 0.0 — so without this bound the node returns
    # magnitude 0, a wrong answer that looks entirely ordinary. The reverse
    # direction raises OverflowError out of the maths library, which escaped as
    # an unhandled traceback. Both are refused at the unit expression.
    for call in _every_node_call(units):
        result = call()
        assert result.error.code == "INVALID_UNIT", (
            f"expected INVALID_UNIT for {units!r}, got "
            f"{result.error.code or '<none, ACCEPTED>'}"
        )
        assert "exponent" in result.error.message


def test_exponents_within_the_bound_still_work():
    result = describe_unit(ax(), UnitInput(units="m**50"))
    assert not result.error.code, result.error.message
    assert result.dimensionality == "[length] ** 50"

    result = describe_unit(ax(), UnitInput(units="m**51"))
    assert result.error.code == "INVALID_UNIT"


def test_a_conversion_that_underflows_to_zero_is_an_error_not_a_zero():
    # A non-zero quantity must never convert to exactly 0.0 and be reported as
    # a successful answer.
    result = convert(
        ax(),
        ConvertRequest(quantity=q(1e-320, "meter"), to_units="parsec"),
    )
    assert result.error.code == "OVERFLOW", (
        f"expected OVERFLOW, got {result.error.code or '<none>'} "
        f"with magnitude {result.magnitude}"
    )


def test_a_genuinely_zero_quantity_converts_to_zero_without_error():
    # The underflow check must not fire on an honest zero.
    result = convert(ax(), ConvertRequest(quantity=q(0.0, "meter"), to_units="km"))
    assert not result.error.code, result.error.message
    assert result.magnitude == 0.0


def test_no_node_ever_emits_a_non_finite_magnitude():
    overflowing = (
        lambda: convert(
            ax(), ConvertRequest(quantity=q(1e308, "kilometer"), to_units="meter")
        ),
        lambda: to_base_units(ax(), q(1e308, "kilometer")),
        lambda: arithmetic(
            ax(), ArithmeticRequest(left=q(1e308, "m"), op="mul", right=q(1e308, "m"))
        ),
        lambda: arithmetic(
            ax(), ArithmeticRequest(left=q(1.0, "m"), op="div", right=q(0.0, "s"))
        ),
    )
    for call in overflowing:
        result = call()
        assert result.error.code == "OVERFLOW", (
            f"expected OVERFLOW, got {result.error.code or '<none>'} "
            f"with magnitude {result.magnitude}"
        )
        assert result.magnitude == 0.0


def test_unicode_micro_and_ohm_spellings_are_both_accepted():
    # Real input uses U+00B5 and U+03BC for micro, and U+03A9 and U+2126 for
    # ohm, interchangeably. Both must resolve rather than trip the charset guard.
    for units in ("µm", "μm"):
        result = describe_unit(ax(), UnitInput(units=units))
        assert not result.error.code, f"{units!r}: {result.error.message}"
        assert result.canonical == "micrometer"
    for units in ("Ω", "Ω"):
        result = describe_unit(ax(), UnitInput(units=units))
        assert not result.error.code, f"{units!r}: {result.error.message}"
        assert result.canonical == "ohm"


def test_nodes_are_stateless_across_invocations():
    # A registry shared between calls must not accumulate anything: a hostile
    # call cannot change what a later legitimate call returns.
    before = convert(ax(), ConvertRequest(quantity=q(1.0, "mile"), to_units="km"))
    for units in HOSTILE_UNITS:
        describe_unit(ax(), UnitInput(units=units))
    after = convert(ax(), ConvertRequest(quantity=q(1.0, "mile"), to_units="km"))
    assert before == after


EXPONENT_TOWERS = [
    "m**2**2**2**2**2",
    "m**2**2**2**2**2**2",
    "m**9**9**9",
    "m^2^2^2^2^2",
    "km**3**3**3**3",
]


@pytest.mark.parametrize("units", EXPONENT_TOWERS)
def test_exponent_towers_are_refused_before_the_parser_sees_them(units):
    # Exponentiation is right-associative, so each "**2" SQUARES the exponent.
    # Measured before this guard: "m**2**2**2**2**2**2" burned ~8s and ~900MB,
    # and "m**2**2**2**2**2" produced an exponent so large that FORMATTING it
    # for the error message raised an uncaught OverflowError. The guard must
    # fire on the raw string, so rejection is instant.
    start = time.monotonic()
    for call in _every_node_call(units):
        result = call()                      # must not raise
        assert result.error.code == "INVALID_UNIT", (
            f"exponent tower {units!r} was ACCEPTED "
            f"(got {result.error.code or '<none>'})"
        )
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"rejecting {units!r} took {elapsed:.2f}s"


def test_an_unevaluable_unit_is_not_mistaken_for_an_offset_unit():
    # is_offset_unit used to answer True when the base conversion blew up
    # numerically — "conservative", but it silently DISABLED the underflow
    # guard (skipped for offset units, where zero is a real value). The result:
    # Convert on 1 "m**50" to "light_year**50" returned magnitude 0 with no
    # error, and Arithmetic refused a length with OFFSET_UNIT. An extreme
    # multiplicative unit is not an offset unit.
    assert not is_offset_unit(parse_unit("light_year**50"))
    assert not is_offset_unit(parse_unit("angstrom**35"))
    # ...while genuine offset units still register.
    assert is_offset_unit(parse_unit("degC"))
    assert is_offset_unit(parse_unit("degF"))
    # ...and Rankine, whose zero IS absolute zero, does not.
    assert not is_offset_unit(parse_unit("degR"))


def test_no_node_returns_a_silently_underflowed_zero():
    # Table-driven across every node that performs a multiplicative
    # conversion, because the "no silent zeros" claim is package-wide.
    underflowing = (
        ("Convert", lambda: convert(
            ax(), ConvertRequest(quantity=q(1.0, "m**50"), to_units="light_year**50")
        )),
        ("Convert", lambda: convert(
            ax(), ConvertRequest(quantity=q(12345.0, "m**50"), to_units="light_year**50")
        )),
        ("Convert", lambda: convert(
            ax(), ConvertRequest(quantity=q(1e-320, "meter"), to_units="parsec")
        )),
        ("ToBaseUnits", lambda: to_base_units(ax(), q(1e-320, "angstrom"))),
    )
    for name, call in underflowing:
        result = call()
        assert result.error.code == "OVERFLOW", (
            f"{name} returned magnitude {result.magnitude} with error "
            f"{result.error.code or '<none>'} instead of OVERFLOW"
        )


# Parenthesised towers, which defeated the first (syntactic) guard: no
# "**<number>**" adjacency, and every literal is within the exponent bound.
PARENTHESISED_TOWERS = [
    "m**(9**(9**(9)))",
    "m**(50)**(50)**(50)**(50)",
    "m**(2**(2**(2**(2**(2**(2))))))",
    "(((m**2)**2)**2)**2",
    "(m/s)**2",
]


@pytest.mark.parametrize("units", PARENTHESISED_TOWERS)
def test_grouped_exponents_cannot_smuggle_a_tower_past_the_guard(units):
    # The guard is structural, not syntactic: an exponent must be a bare
    # number applied to a bare unit. "(m/s)**2" is legitimate notation and is
    # refused too — a deliberate, documented cost of closing this hole, since
    # "m**2/s**2" expresses the same thing.
    start = time.monotonic()
    for call in _every_node_call(units):
        result = call()
        assert result.error.code == "INVALID_UNIT", (
            f"grouped tower {units!r} was ACCEPTED "
            f"(got {result.error.code or '<none>'})"
        )
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"rejecting {units!r} took {elapsed:.2f}s"


def test_the_shared_registry_cache_stays_bounded():
    # Pint memoises parsed expressions in a process-wide dict keyed by the
    # caller's string, with nothing evicting. 20,000 distinct valid
    # expressions grew it to 20,000 entries and RSS from ~44MB to ~53MB.
    for i in range(6000):
        describe_unit(ax(), UnitInput(units=f"m**{i % 50}/s**{(i * 7) % 50}"))
    cache = _units._UREG._cache.parse_unit
    assert len(cache) <= _units.MAX_PARSE_CACHE_ENTRIES, (
        f"cache grew to {len(cache)} entries, past the "
        f"{_units.MAX_PARSE_CACHE_ENTRIES} bound"
    )
    # Dropping the cache must not disturb correctness.
    result = convert(ax(), ConvertRequest(quantity=q(1.0, "mile"), to_units="km"))
    assert not result.error.code
    assert result.magnitude == pytest.approx(1.609344)


def test_a_node_fault_becomes_a_structured_internal_error(monkeypatch):
    # No traceback may ever reach the caller: it leaks internal paths and
    # breaks the contract that every failure arrives as a structured Error.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated internal fault")

    monkeypatch.setattr("nodes.describe_unit.base_factor", boom)
    result = describe_unit(ax(), UnitInput(units="meter"))
    assert result.error.code == "INTERNAL"
    assert "RuntimeError" in result.error.message
    # The message must not carry a traceback or a filesystem path.
    assert "Traceback" not in result.error.message
    assert "/" not in result.error.message
