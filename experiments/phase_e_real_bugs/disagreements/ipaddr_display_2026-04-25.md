# Disagreement: `ip` extension wire/Display divergence

**Date:** 2026-04-25
**Filed by:** platform agent (`phase_e_real_bugs`)
**Severity:** wire-format divergence (NOT a policy-decision divergence)

---

## Versions under test

| Impl | Version | Source |
| --- | --- | --- |
| cedar-policy (Rust) | 4.10.0 | `/work/cedar-spec/cedar` workspace pin, commit `6e0f25b` (2026-04-21) |
| cedar-go (Go) | HEAD on `main` | `/work/cedar-go`, commit `a9a4b1b` (2026-03-20) |
| Lean evaluator | n/a | **not yet wired into this repro** |

## Inputs

`ip(<lit>)` for `lit ∈ {"127.0.0.1", "127.0.0.1/32", "10.0.0.0/8", "::1", "::1/128", "2001:db8::/32"}`.

## Recon-claim status check

The recon agent claimed Rust's `IPAddr::Display` (`cedar-policy-core/src/extensions/ipaddr.rs:236-240`)
always emits `addr/prefix`. **The line-level claim is correct** — that `fmt::Display` impl
unconditionally writes `"{}/{}"`. **But:** the standard `EvalResult` and entity-JSON
serialisation paths in cedar-policy 4.10.0 do **not** call this `Display`; they echo the
original constructor argument (see source attribution below). So Rust's *observable*
output for `ip("127.0.0.1")` is `ip("127.0.0.1")`, not `ip("127.0.0.1/32")` —
contrary to the recon agent's prediction.

The `addr/prefix` form fires only via `canonical_repr()` (TPE residual normalisation).

## Rust output (cedar-policy 4.10.0)

`EvalResult::ExtensionValue` (verbatim):

```
127.0.0.1              EvalResult::Display="ip(\"127.0.0.1\")"
127.0.0.1/32           EvalResult::Display="ip(\"127.0.0.1/32\")"
10.0.0.0/8             EvalResult::Display="ip(\"10.0.0.0/8\")"
::1                    EvalResult::Display="ip(\"::1\")"
::1/128                EvalResult::Display="ip(\"::1/128\")"
2001:db8::/32          EvalResult::Display="ip(\"2001:db8::/32\")"
```

Entity-store JSON round-trip:

```
round-trip      127.0.0.1: ...{"__extn":{"fn":"ip","arg":"127.0.0.1"}}...
round-trip   127.0.0.1/32: ...{"__extn":{"fn":"ip","arg":"127.0.0.1/32"}}...
round-trip     10.0.0.0/8: ...{"__extn":{"fn":"ip","arg":"10.0.0.0/8"}}...
round-trip            ::1: ...{"__extn":{"fn":"ip","arg":"::1"}}...
round-trip        ::1/128: ...{"__extn":{"fn":"ip","arg":"::1/128"}}...
```

Rust echoes the **original constructor argument string** verbatim — including any
explicit `/N`.

## Go output (cedar-go a9a4b1b)

```
v4-bare    input="127.0.0.1"      String()="127.0.0.1"     MarshalJSON()={"__extn":{"fn":"ip","arg":"127.0.0.1"}}
v4-32      input="127.0.0.1/32"   String()="127.0.0.1"     MarshalJSON()={"__extn":{"fn":"ip","arg":"127.0.0.1"}}
v4-net     input="10.0.0.0/8"     String()="10.0.0.0/8"    MarshalJSON()={"__extn":{"fn":"ip","arg":"10.0.0.0/8"}}
v6-bare    input="::1"            String()="::1"           MarshalJSON()={"__extn":{"fn":"ip","arg":"::1"}}
v6-128     input="::1/128"        String()="::1"           MarshalJSON()={"__extn":{"fn":"ip","arg":"::1"}}
v6-net     input="2001:db8::/32"  String()="2001:db8::/32" MarshalJSON()={"__extn":{"fn":"ip","arg":"2001:db8::/32"}}
```

Go normalises: when `prefix.Bits() == addr.BitLen()` (i.e. /32 for v4, /128 for v6),
it strips the `/N` from both `String()` and `MarshalJSON()`.

## Wire round-trip (cedar-go)

Replaying Rust-emitted wire bytes through `json.Unmarshal` + `MarshalJSON`:

```
in={"__extn":{"fn":"ip","arg":"127.0.0.1/32"}}     out={"__extn":{"fn":"ip","arg":"127.0.0.1"}}     byte-equal=false
in={"__extn":{"fn":"ip","arg":"::1/128"}}          out={"__extn":{"fn":"ip","arg":"::1"}}           byte-equal=false
in={"__extn":{"fn":"ip","arg":"10.0.0.0/8"}}       out={"__extn":{"fn":"ip","arg":"10.0.0.0/8"}}    byte-equal=true
in={"__extn":{"fn":"ip","arg":"127.0.0.1"}}        out={"__extn":{"fn":"ip","arg":"127.0.0.1"}}     byte-equal=true
```

So a Rust → Go pipeline that ever emits the explicit-/32 or /128 form (e.g. via
TPE residual normalisation, or via a user constructing entities with explicit prefix)
will see the JSON change shape after a single Go hop.

## Upstream source attribution

* **Rust** `cedar-policy-core/src/extensions/ipaddr.rs:236-240` — `IPAddr::Display`
  always emits `{}/{}`.
* **Rust** `cedar-policy-core/src/extensions/ipaddr.rs:252-258` — `canonical_repr()`
  returns the `Display` form (used by TPE).
* **Rust** `cedar-policy-core/src/extensions/ipaddr.rs:328-346` — `ip_from_str`
  constructor stores the original argument literal in `ev.args`. This is what gets
  echoed by `EvalResult::ExtensionValue` and JSON entity serialisation.
* **Rust** `cedar-policy-core/src/entities/json/value.rs:523-543` — JSON
  serialisation echoes `ev.args[0]` verbatim, NOT the canonical form.
* **Go** `cedar-go/types/ipaddr.go:42-47` — `String()` strips `/N` when `Bits() == BitLen()`.
* **Go** `cedar-go/types/ipaddr.go:122-138` — `MarshalJSON()` strips `/N` when
  `Bits() == BitLen()` (using `Addr().String()` instead of `String()` in that branch,
  but functionally identical to the trim).

## Does this affect policy decisions?

**No.** IP `==` compares the internal struct `(addr, prefix)`. Both Rust and Go
parse bare `"127.0.0.1"` to `(127.0.0.1, prefix=32)` and explicit `"127.0.0.1/32"`
to the same internal value. Tested via:

* `policy_eval_ip.cedar`: `permit when resource.src == ip("127.0.0.1/32")`
* `entities_ip_bare.json` (arg `"127.0.0.1"`) and `entities_ip_explicit32.json` (arg `"127.0.0.1/32"`)

```
== Rust: bare 127.0.0.1 ==      ALLOW
== Rust: explicit /32   ==      ALLOW
bare-arg "127.0.0.1"             decision=allow   (cedar-go)
explicit-arg "127.0.0.1/32"      decision=allow   (cedar-go)
```

All four combinations agree.

## Why this is still publishable

1. **Wire-format byte-inequality on /32 and /128.** Concrete demonstration: the
   Rust-emitted JSON `{"fn":"ip","arg":"127.0.0.1/32"}` round-trips through Go to
   `{"fn":"ip","arg":"127.0.0.1"}`. Audit-log diff tools will flag this as drift.
2. **Spec ambiguity.** The Cedar formal model has not (per `cedar-spec`) pinned
   down whether the wire form should preserve or canonicalise the prefix. Both
   impls disagree, and neither is provably "correct" against the Lean spec — that
   gap is itself the contribution.
3. **Recon-agent claim partially refuted.** The recon agent predicted Rust would
   *emit* `addr/prefix`. The actual behaviour is: Rust *can* emit it (via
   `Display`/`canonical_repr`) but the user-facing `EvalResult` and entity-JSON paths
   echo the constructor literal. This nuance matters for any downstream paper claim.

## Reproducer paths

* `experiments/phase_e_real_bugs/ipaddr_repro/rust/{Cargo.toml,main.rs}`
* `experiments/phase_e_real_bugs/ipaddr_repro/go/{go.mod,main.go}`
* `experiments/phase_e_real_bugs/ipaddr_repro/go_eval/{go.mod,main.go}` — policy
  decision check.
* `experiments/phase_e_real_bugs/ipaddr_repro/go_wire/{go.mod,main.go}` — wire
  round-trip showing byte-inequality on /32, /128.

---

**Honest classification:** purely cosmetic at the evaluator level; concrete
wire-format divergence on JSON round-trip for full-bitlen prefixes; not a
policy-decision divergence.
