# 0007. Separate Evaluator and Judge as distinct roles

* **Status:** Accepted
* **Date:** 2026-02-02
* **Deciders:** Eval-fabric core team
* **Tags:** contracts, design

## Context and problem statement

Every eval framework has to define what is being measured and what is doing the measuring. The two most common designs are:

1. **One abstraction.** A single `Evaluator` interface that takes an input, calls a model, and returns a score. The "evaluator" is responsible for both producing an output and judging it.
2. **Two abstractions.** An `Evaluator` produces an output (it *is* the system under test, or a wrapper around it). A separate `Judge` scores that output.

The first is more compact and feels simpler. Several popular frameworks (notably some early LLM eval libraries) use it. The second is what `eval-fabric` does. This ADR explains why we accepted the additional concept.

## Decision drivers

* The framework must make auto-evaluator drift diagnosable. If the eval score moves, we must be able to answer "did the system regress, or did the judge change?"
* Judges and systems-under-test have different lifecycles: a judge may be reused across many evaluators, and an evaluator may be scored by many judges.
* Judges and systems-under-test have different cost profiles. A judge LLM call may cost 10x what a system-under-test call costs, or vice versa. Concurrency limits should be settable independently.
* Reproducibility requires versioning. We need to know which version of the system was scored by which version of the judge.

## Considered options

1. **One `Evaluator` interface that returns a score directly.**
2. **Two interfaces: `Evaluator` (produces output) and `Judge` (scores output).**
3. **Three interfaces: `System` (produces output), `Judge` (scores), `Aggregator` (combines).** A taxonomy from some academic eval frameworks.

## Decision

We chose **two interfaces: `Evaluator` and `Judge`**.

```python
class Evaluator(Protocol):
    id: str
    version: str
    async def __call__(self, item: EvalItem) -> EvaluatorOutput: ...

class Judge(Protocol):
    id: str
    version: str
    determinism: Determinism
    async def judge(self, item: EvalItem, output: EvaluatorOutput) -> Judgment: ...
```

A run pairs one evaluator with one or more judges. Each judge produces its own judgment. Aggregation across judges is the aggregator's job, not the judges'.

## Consequences

### Positive

- **Auto-evaluator drift is diagnosable.** A regression report can break out: "system A scored 0.82 by judge X v1.0; system A scored 0.79 by judge X v1.1." We can see whether the system or the judge changed.
- **Judges are reusable.** A "factuality judge" can score many systems. A "style judge" can be applied to anything. We do not have to write a new evaluator for every (system, judge) pair.
- **Cost and concurrency are separately tunable.** A run with `RuntimeConfig(max_concurrent=64)` calling a `LLMJudge` with `max_concurrent=8` lets the judge respect its API rate limits independently of the evaluator's.
- **Versioning is precise.** A run record stores `(evaluator_id, evaluator_version, judge_id, judge_version)` and we know exactly what was measured by what.
- **Multi-judge runs are first-class.** Scoring the same output with two different judges (for cross-validation, or to track judge drift) is just listing two judges in the spec.

### Negative

- **One more concept for users to learn.** A team that just wants "score my chatbot's accuracy" has to understand they are configuring a chatbot evaluator and an accuracy judge, not a single thing.
- **Some tasks fit awkwardly.** Tasks where the evaluator already returns a structured score (e.g., a classifier returning probabilities) require a trivial pass-through judge. We provide `IdentityJudge` for this case.
- **More files in a typical config.** A small amount of additional ceremony.

### Neutral

- We added a fourth concept: the **Reference**. An EvalSpec contains `EvaluatorRef` and `JudgeRef` — typed references with config — rather than embedding evaluator/judge implementations in the spec. This is necessary regardless of the one-vs-two-interface choice.

## Pros and cons of the options

### Option 1 — One `Evaluator` interface

* ✅ Compact. Fewer concepts.
* ✅ Familiar from early LLM eval frameworks.
* ❌ Makes auto-evaluator drift impossible to reason about cleanly. The single most important diagnostic question in eval ops becomes hard.
* ❌ Forces every (system, judge) combination to be a new "evaluator." Code reuse suffers.
* ❌ Conflates "what am I measuring?" with "how am I measuring it?" These are different questions and conflating them confuses every conversation about results.

### Option 2 — Two interfaces (chosen)

* ✅ Separates "what is being measured" from "how it is being measured."
* ✅ Reusability across both axes.
* ✅ Independent versioning, cost, concurrency.
* ❌ One more concept to learn.

### Option 3 — Three interfaces (System / Judge / Aggregator)

* ✅ Most precise taxonomy.
* ❌ Aggregation is rarely complex enough to deserve its own pluggable interface. Most teams want mean/median/rate-above-threshold and bootstrap CIs. We provide these as scoring config in the spec, not a plugin.
* ❌ More ceremony for marginal gain.

## Examples

A typical eval looks like:

```yaml
# spec.yaml
id: team/customer-support-bot
version: 1.0.0

evaluator:
  id: team.customer_support_bot
  config:
    model: gpt-4o-mini
    temperature: 0.0

judges:
  - id: eval_fabric.judges.llm_judge
    config:
      criterion: "Did the answer correctly address the customer's issue?"
      judge_model: claude-sonnet-4-5
    weight: 0.7
  - id: team.brand_voice
    weight: 0.3

scoring:
  metrics:
    - name: helpfulness
      from: judges
      aggregator: weighted_mean
```

Here, the `customer-support-bot` evaluator is what we are measuring. Two judges (`llm_judge` and `brand_voice`) score its outputs along different dimensions. The two-role split makes the structure of the eval visible at the spec level.

## Links

* [ADR-0002 — Plugin model via entry points](0002-evaluator-plugin-via-entry-points.md)
* [ADR-0008 — Determinism contract](0008-judge-determinism-contract.md)