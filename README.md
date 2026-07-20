# unit-tools

Composable physical-unit nodes for the [Axiom](https://axiom.dev) marketplace,
published as `christiangeorgelucas/unit-tools`.

Unit arithmetic is a place where plausible-looking wrong answers are easy to
produce and hard to notice. This package does it properly: every node runs on
[Pint](https://github.com/hgrecco/pint), which owns the algorithmically hard
parts — parsing unit expressions, dimensional analysis, its ~800-entry unit
registry, and offset-scale conversion — while this package supplies a single
canonical envelope, a strict input contract, and a consistent error vocabulary.

Fully offline, stateless, deterministic. No API keys, no network, no secrets.

## The envelope

Every node consumes and emits the same `Quantity`: a finite `magnitude` and a
`units` expression written the way Pint spells it.

```
"km"           kilometre
"m/s"          metre per second
"kg*m/s**2"    newton, spelled out
"degC"         degree Celsius (an offset unit)
""             dimensionless
```

A dimensionless quantity is spelled `"dimensionless"`, never `""`. That is
load-bearing rather than pedantic — see *Composing these nodes* below.

## Composing these nodes

The envelope is shared, so the value flowing between nodes is always a
`Quantity`. Edges still need an adapter wherever the shapes differ: `Parse`
emits a bare `Quantity`, while `Convert` and `Format` want it nested under
`quantity` alongside their own arguments. Only bare-`Quantity` → bare-`Quantity`
hops (`Parse` → `ToBaseUnits`) chain with no adapter at all.

**Carry the `error` field across every edge.** An adapter that maps only
`magnitude` and `units` — the natural way to write one — drops `error`
structurally:

```yaml
- from: parse
  to: convert
  adapter:
    "magnitude": quantity.magnitude
    "units": quantity.units
    "error.code": quantity.error.code        # do not omit
    "error.message": quantity.error.message  # do not omit
    "'mile/hour'": to_units
```

Two independent things then protect you, which is why forgetting the two lines
above degrades to a clear error rather than a wrong number:

1. A node handed a `Quantity` whose `error` is set refuses it and propagates
   that error unchanged.
2. A failed node emits `units: ""`, and `""` is **not** a valid unit. This is
   the reason dimensionless must be written out. proto3 has no field presence
   for scalars, so a dropped or unset `Quantity` arrives as
   `{magnitude: 0, units: ""}` — and if `""` meant dimensionless, that would be
   a perfectly valid measurement of zero. An upstream failure would silently
   become the number `0`. Making `""` invalid is what stops a defaulted message
   from impersonating an answer.

## Nodes

| Node | Does |
|---|---|
| `Parse` | `"5 km/h"` → magnitude 5.0, units `kilometer / hour` |
| `Convert` | Express a quantity in another unit of the same dimension |
| `ToBaseUnits` | Reduce to SI base units (1 hp → 745.7 kg·m²/s³) |
| `Format` | Render as text at a chosen precision and unit style |
| `Arithmetic` | `add` / `sub` / `mul` / `div`, units carried through |
| `Compare` | Order two quantities written in different units |
| `DescribeUnit` | Canonical name, dimensions, base units, base factor |
| `CheckCompatibility` | Are two units interconvertible, and by what factor? |

## Behaviour worth knowing

**Offset temperature scales.** degC and degF measure from a non-zero zero.
Converting them is well defined and fully supported (0 degC → 32 degF). Adding
them is *not* — "1 degC + 1 degC" could mean 2 degC or 275.3 K — so `Arithmetic`
refuses it with an `OFFSET_UNIT` error rather than picking a reading. `Compare`
handles them by reducing both sides to kelvin first, so 0 degC and 32 degF
compare equal.

`degR` (Rankine) is **not** in that group, despite being an imperial
temperature: its zero *is* absolute zero, so it is purely multiplicative
(1 degR = 5/9 K) and its arithmetic is unambiguous and permitted. A compound
expression such as `degC/m` is likewise multiplicative — Pint reads the degC
there as a temperature *difference*, and the result comes back spelled
`delta_degree_Celsius / meter`, naming that reading explicitly.

**Cancelling units.** `mul` and `div` reduce their result, so 1 km / 500 m is
the dimensionless `2` rather than `0.002 kilometer / meter`. Genuinely distinct
dimensions are left alone: 3 m / 1.5 s stays 2 m/s.

**Equality is within tolerance.** `Compare` calls two magnitudes equal when
they agree to a relative tolerance of 1e-12, because conversion is
floating-point: 0 degC reduces to exactly 273.15 K while 32 degF — the same
temperature — reduces to 273.15000000000003 K.

**Strict input.** Pint's expression parser is permissive enough to read
`"[1,2,3] meter"` as 123 metre, and a long operator chain drives it into
unbounded recursion. Both are rejected here, before the string reaches the
parser: unit expressions are capped at 256 characters and restricted to a
conservative character set, and `Parse` reads the magnitude itself so that
exactly one well-formed number is accepted. Unicode is NFC-normalised first, so
both the OHM SIGN and GREEK CAPITAL OMEGA spellings of `Ω` resolve.

Unit exponents are capped at an absolute value of 50 — far above any real
expression — because beyond that a conversion factor stops being representable
and fails *silently*: converting 2 `m**1e9` to `km**1e9` needs a factor of
1e-3^1e9, which underflows to exactly 0.0, so the answer would be `0`. Chained or
grouped exponents are refused outright: exponentiation is right-associative, so
each step *squares* the exponent, and 19 characters reached ~8s and ~900MB
before this bound existed. The rule is structural rather than a pattern match —
an exponent must be a bare number applied to a bare unit — and it is enforced
on the form Pint will actually parse, after its word-exponent syntax is
desugared. A raw-string check is walked straight through two ways: by
parentheses (`m**(9**(9**(9)))`), and by Pint's own words — `sq square cubic
meter cubed squared` becomes `meter**2**2**3**3**2` with no operator in sight
(16.9s, 1.7GB before this was closed). A single word exponent like `m squared`
is fine; only stacking them is refused. The cost is that `(m/s)**2` must be
written `m**2/s**2`.

The exponent cap alone is not sufficient — `angstrom**35` still reduces by
1e-350 — so the underflow checks below are what actually guarantee it.

**No non-finite values, ever, and no silent zeros.** A NaN or infinite input
magnitude is rejected with `INVALID_QUANTITY`; a computation that overflows
returns `OVERFLOW` instead of emitting `inf`; and a non-zero quantity that
would underflow to exactly zero through a multiplicative conversion returns
`OVERFLOW` rather than a plausible-looking `0`. Offset scales are exempt from
that last rule, because there −273.15 °C really is 0 K. Correspondingly,
`DescribeUnit` and `CheckCompatibility` report `base_factor_defined` /
`factor_defined` as **false** when the factor underflows, rather than asserting
that a zero factor is trustworthy.

**Ordering survives an unrepresentable ratio.** `Compare` answers 1e200 m vs
1e-200 m with `relation: "gt"` and `ratio_defined: false`. The ordering is well
defined even though the quotient is 1e400, so failing the whole comparison
would refuse an ordinary question.

## Errors

Nodes never raise. Every output carries an `error` field, unset on success:

`INVALID_UNIT` · `INVALID_QUANTITY` · `INCOMPATIBLE_UNITS` · `OFFSET_UNIT` ·
`INVALID_ARGUMENT` · `OVERFLOW` · `INTERNAL`

A traceback never reaches the caller. If a node faults unexpectedly it returns
`INTERNAL`, which says the fault is ours so you do not go debugging your own
input.

Note that two valid but incompatible units are **not** an error from
`CheckCompatibility` — that is the answer, returned as `compatible: false`.

## Tests

```bash
axiom test
```

165 tests, including an independent-oracle suite that checks conversions
against values derived from scratch from the defining relations (1 inch =
0.0254 m, 1 hp = 550 ft·lbf/s, F = C·9/5 + 32) rather than round-tripping
through Pint, and a hostile-input suite covering injection strings, resource
exhaustion and overflow across every node.

The suite is mutation-tested: every documented constant (512, 256, 50, 15,
1e-12) and every guard described above is pinned by a test that fails when the
constant is loosened or the guard removed. Bound tests assert the literal
documented numbers rather than importing the constant, so an assertion cannot
drift along with the value it checks.

## Licence

MIT — see [LICENSE](LICENSE).

Wraps [Pint](https://github.com/hgrecco/pint) (BSD-3-Clause). The full
dependency tree — Pint, flexcache, flexparser, platformdirs, typing_extensions
— is permissive with no copyleft; see [requirements.txt](requirements.txt). The
verbatim license texts are reproduced in
[THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt), as BSD-3-Clause clause 2
requires of a redistribution.

Built for the Axiom marketplace.
