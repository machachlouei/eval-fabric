# 0008. Judges declare a determinism contract

* **Status:** Accepted
* **Date:** 2026-02-05
* **Deciders:** Eval-fabric core team
* **Tags:** contracts, replay, reproducibility

## Context and problem statement

Reproducibility is the framework's most important promise. Given a stored run, an operator must be able to ask: "if I replay this with the same evaluator and judge, what should I expect?"

The honest answer depends on the judge.

- A regex-based rule judge produces the same answer every time. Replay is byte-identical.
- A judge that calls an LLM with `temperature=0` and a fixed seed is *mostly* deterministic — but model providers do not actually guarantee bit-identical outputs across infrastructure changes.
- A judge that samples diverse rationales at `temperature=0.7` is genuinely stochastic. Replay will produce statistically similar but not identical scores.

If we treat all three the same, we either over-promise (claim replay is exact when it is not) or under-promise (warn about drift on judges that do not drift, training operators to ignore the warning). Both fail.

## Decision drivers

* The framework must not lie about reproducibility. If replay is approximate, that must be visible.
* Replay tooling must know what guarantees to enforce.
* Judge authors must be the ones to declare the contract; the framework cannot infer it.
* The contract must be small and easy to explain.

## Considered options

1. **Treat all judges as stochastic.** Always assume drift on replay.
2. **Treat all judges as deterministic.** Pretend nothing changes.
3. **A boolean `deterministic: bool` field per judge.**
4. **A three-valued `Determinism` enum: deterministic, sampling-deterministic, stochastic.**

## Decision

We chose **a three-valued `Determinism` enum** declared by each judge.

```python
class Determinism(StrEnum):
    DETERMINISTIC = "deterministic"
    # The judge produces byte-identical output for the same input,
    # in the same process and across processes, indefinitely.
    # Examples: rule-based judges, schema validators.

    SAMPLING_DETERMINISTIC = "sampling_deterministic"
    # The judge produces byte-identical output for the same input
    # *if* a seed is pinned and the underlying model/version is unchanged.
    # Cross-version, cross-vendor drift is possible but bounded.
    # Examples: LLM judges with temperature=0 and seed pinned.

    STOCHASTIC = "stochastic"
    # The judge does not promise byte-identical output even with seed pinning.
    # Replay produces statistically similar results.
    # Examples: temperature>0 LLM judges, judges with internal sampling.
```

Each judge declares its determinism class as a class attribute. The framework uses this to:

1. Set replay expectations: replay tooling reports drift only when it exceeds the contract.
2. Drive caching: deterministic judgments can be cached aggressively; stochastic ones cannot.
3. Inform users at run time when a judge is stochastic, so they can interpret variance correctly.

## Consequences

### Positive

- **Replay reports become honest.** "Judge `team.style_judge` is sampling-deterministic; observed drift is 0.04 (within tolerance)." This is information operators can act on.
- **Caching is safe.** A deterministic judge's output can be memoized by `(judge_id, judge_version, item_hash, evaluator_output_hash)`. We do not enable this for stochastic judges.
- **Test infrastructure benefits.** CI can assert byte-identical replay for deterministic judges and known-tolerance replay for sampling-deterministic ones. Stochastic judges get statistical assertions.
- **Judge authors are forced to think about it.** Declaring `Determinism.STOCHASTIC` is a small but real act of communication.

### Negative

- **Authors can lie.** A judge can declare `DETERMINISTIC` and not be. We mitigate with a `ef judge verify <judge_id>` tool that runs the judge a few hundred times on a fixed input set and reports observed variance. We cannot prevent dishonesty; we can make it detectable.
- **The middle category requires explanation.** "Sampling-deterministic" is not a phrase most operators have heard. We define it clearly in `concepts.md` and link to that definition in error messages.
- **There is no fourth category for "deterministic in this version, but might change next version."** That is just sampling-deterministic with a wider tolerance, in practice.

### Neutral

- We do not enforce the contract at runtime. We trust the declaration and provide tools to verify it. Defensive enforcement (e.g., wrapping every judge call to detect violations) would impose a large performance cost for marginal benefit.

## Pros and cons of the options

### Option 1 — Treat all judges as stochastic

* ✅ Simple. Honest by default.
* ❌ Loses the win of cacheable replay for genuinely deterministic judges.
* ❌ Trains users to ignore drift warnings ("everything always drifts").

### Option 2 — Treat all judges as deterministic

* ✅ Simple. Lets the framework cache aggressively.
* ❌ Lies about LLM judges. Drift is real and operators discover it during incident response, when trust is lowest.

### Option 3 — Boolean

* ✅ Simpler than three values.
* ❌ Cannot distinguish between "rule-based, byte-identical" and "LLM, almost-identical-with-seed." These have different cache and replay semantics. A boolean forces both into "deterministic" or both into "stochastic" — neither is right.

### Option 4 — Three-valued enum (chosen)

* ✅ Captures the three real categories of judges we ship and that exist in the wild.
* ✅ Matches how operators actually think about replay.
* ❌ One more concept to explain.

## How this interacts with caching

Cacheability is derived from determinism, not declared separately:

| Determinism class           | Cacheable across runs? | Cacheable across processes?         |
| --------------------------- | ---------------------- | ----------------------------------- |
| `DETERMINISTIC`             | Yes                    | Yes                                 |
| `SAMPLING_DETERMINISTIC`    | Yes if seed unchanged  | Yes if seed unchanged + same model  |
| `STOCHASTIC`                | No                     | No                                  |

The trace store includes a `cache_key` field on each judgment that captures the inputs that determine the output: `(judge_id, judge_version, model_version, seed, item_hash, output_hash)`. Lookups use this key.

## How this interacts with replay tooling

`ef replay <run_id>` reports per-judge drift:

```
Run abc-123 replayed.
  judge eval_fabric.judges.exact_match (deterministic):
    drift: 0/2400 (0.00%)  ✓ within tolerance
  judge team.style (sampling_deterministic, seed=42):
    drift: 24/2400 (1.00%)  ✓ within tolerance (max 2%)
  judge team.creativity (stochastic):
    drift: not measured (stochastic)
    distributional comparison: KS p=0.31 (not significantly different)
```

## Links

* [ADR-0005 — TraceStore as Protocol](0005-trace-store-as-protocol.md)
* [ADR-0007 — Separate Evaluator and Judge](0007-separate-evaluator-and-judge.md)