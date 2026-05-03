# Concepts

This document explains *how `eval-fabric` thinks about evaluation*. It is the explanation layer in the [Diátaxis](https://diataxis.fr/) sense — separate from how-to guides (`setup.md`, `testing.md`) and from technical reference (`design.md`).

If you are about to read code, read this first. The code is easier to follow once these mental models are in place.

---

## The four core concepts

There are four things you need to understand. Everything else is built on top of these.

### 1. EvalSpec — the contract

An `EvalSpec` is a versioned, declarative description of an evaluation. It answers four questions:

1. **What is being evaluated?** (an evaluator reference)
2. **How is it being scored?** (one or more judge references and a scoring config)
3. **Under what runtime constraints?** (concurrency, timeouts, retries)
4. **What is the identity of this evaluation?** (a stable ID and a semver version)

A spec is *not* the dataset. The dataset is supplied separately at run time. The same spec can be run against many datasets — that is the point. The spec describes *the evaluation*, not *a particular execution of it*.

A spec is *not* the result. Running a spec against a dataset produces a `RunResult`. The spec is the input, the result is the output. They have separate lifecycles.

#### Mental model

> An EvalSpec is to an evaluation what a `Dockerfile` is to a container image: a declarative recipe, versioned, committed to source control, and reproducibly executable.

### 2. Evaluator — the system under test

An `Evaluator` is a callable that takes an `EvalItem` and produces an `EvaluatorOutput`. It is what you are measuring. Three common shapes:

- **A wrapper around a deployed model or service.** Most production evaluators look like this. The evaluator class holds an HTTP client; `__call__` makes a request.
- **A wrapper around an agent or chain.** The evaluator orchestrates a multi-step LangGraph or LangChain workflow and returns its terminal output.
- **A pure function.** For testing the framework or for evaluating non-ML systems (e.g., a deterministic algorithm whose correctness you are measuring).

An evaluator does not know it is being evaluated. From its perspective, it is just receiving an input and producing an output. This is intentional: it should be the same code path that runs in production.

#### Mental model

> An Evaluator is the unit under test. It is *what you ship*. The framework's job is to call it many times under controlled conditions and capture what it returns.

### 3. Judge — the scorer

A `Judge` takes an `EvalItem` and the `EvaluatorOutput` produced for that item and returns a `Judgment`. The judgment is a structured score, not a free-form string.

Judges come in three flavors:

- **Rule-based.** Exact match, regex, JSON-schema validation, range check. Cheap, fast, deterministic.
- **LLM-as-judge.** A judge model is prompted with the input, the system's output, and a criterion. Returns a score and a rationale.
- **Human-in-the-loop.** The judgment is routed to a human via an annotation queue. The framework can either block (synchronous mode) or persist the trace and resume later when the human's verdict is available (async mode).

A run can have many judges scoring the same evaluator output. Each judge produces its own `Judgment`. Aggregation across judges happens in the aggregator, not in the judges.

A judge declares its **determinism class**: `DETERMINISTIC`, `SAMPLING_DETERMINISTIC`, or `STOCHASTIC`. This is how the framework reasons about replay and caching. See [ADR-0008](decisions/0008-judge-determinism-contract.md).

#### Mental model

> A Judge is to an Evaluator what a teacher is to a student. The student produces work. The teacher scores the work. Many teachers can grade the same paper, and they may disagree, and that is informative.

### 4. Run — one execution

A `Run` is the result of executing an `EvalSpec` against a `Dataset`. It is the persistent record. A run contains:

- The full `EvalSpec` it was created with (snapshot, not reference).
- A `Trace` for every item processed (input, output, status, timings).
- A `Judgment` for every (trace, judge) pair.
- An aggregated `RunResult` (metrics, summary statistics).

A run is **immutable** once written. New evidence about the same evaluator produces a new run with a new ID. There is no "edit run" operation by design — see ADR-0005 on why.

#### Mental model

> A Run is to an EvalSpec what a build is to a Dockerfile. Many builds, one Dockerfile. Many runs, one spec. Builds (and runs) are timestamped, immutable, and addressable by ID.

---

## Things that look the same but are different

A few distinctions that are easy to miss but matter.

### Evaluator vs. Judge

The most common point of confusion. The shorthand:

> **The Evaluator is what you are measuring. The Judge is how you are measuring it.**

If your team writes a chatbot, the chatbot is the evaluator. The thing that says "this answer was good" is the judge. They are different. They have different versions, different lifecycles, and different cost profiles.

A common anti-pattern in eval frameworks is collapsing the two. Then a regression report says "score went down" and you cannot tell whether your chatbot got worse or your judge changed. Don't do that.

See [ADR-0007](decisions/0007-separate-evaluator-and-judge.md).

### EvalSpec vs. Run

A spec is a recipe. A run is a baking. The recipe lives in your repo, versioned with your code. The run lives in your trace store, identified by a UUID, immutable forever.

Do not store run-time state in a spec. Do not edit a run after it is written. These are not the same kind of object.

### EvalItem vs. EvaluatorOutput

An `EvalItem` is what comes from the dataset. It is the input to the evaluator and (optionally) reference data the judge may use.

An `EvaluatorOutput` is what the evaluator produces. It is what the judge scores.

Both are typed Pydantic models. They have different schemas. A judge that accidentally accepts an `EvalItem` where it should accept an `EvaluatorOutput` is a bug; the type system catches it.

### Trace vs. Judgment

A `Trace` is the record of one call to the evaluator on one item. It captures input, output, status, and timing.

A `Judgment` is the record of one call to a judge on one trace. It captures the score and rationale.

One trace, many judgments (one per judge in the spec). One judgment, exactly one trace.

### Schema version vs. framework version

The `eval-fabric` package has a version (e.g., `0.4.2`). The `EvalSpec` schema has a version (e.g., `1`). They move independently. A v1 spec works on framework versions `0.x` through whichever future version drops support; a framework `0.5.0` may add new fields to spec v1 without bumping the spec major version.

We chose this on purpose. Coupling them tightly was tempting and wrong; see [ADR-0004](decisions/0004-eval-spec-versioning-with-semver-and-codegen.md).

---

## How to think about reproducibility

Reproducibility is not "the same numbers come back." It is "given a stored run, I can answer specific questions about what would happen if I ran it again."

The framework gives you three guarantees, calibrated to the judge's determinism class:

1. **Deterministic judges** (rule-based, schema validators): replay is byte-identical. If it's not, something is broken.
2. **Sampling-deterministic judges** (LLM judges with `temperature=0` and a pinned seed): replay is byte-identical *given the same model version and the same seed*. Cross-vendor or cross-version drift is possible and bounded.
3. **Stochastic judges**: replay is statistically similar but not identical. The framework reports distributional comparisons (e.g., KS test) instead of byte-equality.

You will sometimes hear "LLMs are deterministic at temperature 0" stated as fact. It is approximately true and exactly false. Provider infrastructure changes, batching effects, and floating-point determinism mean a `temperature=0` call is not byte-stable across days, hardware, or model micro-versions. Sampling-deterministic acknowledges this honestly.

---

## How to think about cost

Cost in eval is dominated by judge calls, not by evaluator calls. A typical setup has 1 evaluator call and 2–4 judge calls per item, and the judge calls are often more expensive (GPT-4-class judges, multi-turn rationales, etc.).

The framework does not model cost. It does aggregate it: judges that emit a `cost_usd` span attribute are summed automatically into the run's `total_cost_usd` metric. Judges that do not emit cost are simply absent from the total — we do not estimate.

If cost matters to you, your judges should report it. We provide helpers (`@with_cost_tracking`) for the common case of LLM API calls.

---

## Common pitfalls

These are mistakes we see often. Each is a design decision the framework cannot make for you.

### Mistake: using a stochastic judge without acknowledging it

If you want a creative-writing judge or a "rate this on a Likert scale" judge, your judge is going to be stochastic. That is fine — but if your CI gate expects ±1% reproducibility from a stochastic judge, your gate will alarm randomly and lose credibility.

**Fix:** declare your judge `STOCHASTIC` and use a different gate (e.g., a Welch's t-test against a baseline run, with a meaningful effect-size threshold).

### Mistake: putting evaluator-specific config in the EvalSpec

The temptation to add `model: gpt-4o-mini` at the top of every spec is real. Don't. The evaluator owns its configuration. The spec references the evaluator and passes config through `EvaluatorRef.config`, but only config that *the evaluator's interface* exposes.

**Fix:** if `model` should be tunable, the evaluator's config schema should include a `model` field. The spec passes it through. The framework does not know about models.

### Mistake: treating the trace store as a database

The trace store is a write-mostly persistence layer optimized for reproducibility. It is not a query engine for analytics. If you want dashboards, charts, or ad-hoc analysis, export to your data platform (Parquet on S3, Snowflake, BigQuery) and query there.

**Fix:** use `eval_fabric.contrib.parquet` or write a custom adapter that mirrors the SQLite store into your warehouse. Don't grow the trace store interface into a query engine.

### Mistake: a judge that looks at the gold label

A judge that compares the evaluator's output to a gold label in the `EvalItem.reference_output` field is a fine pattern (it is what `ExactMatchJudge` does). A judge that secretly uses gold labels meant only for the evaluator is a bug — and a really hard one to spot.

**Fix:** keep the gold-label channel explicit. Use `EvalItem.reference_output` for judge-visible references; do not stuff them into `EvalItem.input` and hope.

### Mistake: not versioning the judge prompt

If your judge is an LLM judge with a prompt template, **the prompt is part of the judge version**. Changing the prompt without bumping the judge version means two runs have different judges sharing one ID. You cannot diagnose drift, compare runs, or trust your history.

**Fix:** treat the judge prompt as code. Bump the judge version when the prompt changes. The framework will then surface "judge X v1.0" vs "judge X v1.1" comparisons cleanly.

### Mistake: relying on the order of items

Tasks are dispatched concurrently. A run does not process items in dataset order. If your dataset has implicit ordering meaning (e.g., a temporal sequence), encode it into the items themselves. Do not rely on iteration order to encode it.

**Fix:** include a `sequence_id` field in `EvalItem` if you need ordering. Sort during analysis, not during execution.

### Mistake: caching across judge versions

The judgment cache key includes `judge_version`. A judge version bump invalidates the cache automatically. If you find yourself manually clearing the cache, you are probably forgetting to bump the version — see "not versioning the judge prompt" above.

---

## A short glossary

| Term                       | Meaning                                                                          |
| -------------------------- | -------------------------------------------------------------------------------- |
| **EvalSpec**               | The declarative recipe for an evaluation. Versioned. Committed to source control. |
| **Evaluator**              | The system under test, or a wrapper around it.                                   |
| **Judge**                  | A scorer. Produces a `Judgment` from an `EvaluatorOutput`.                       |
| **Run**                    | One execution of an `EvalSpec` against a dataset. Immutable.                     |
| **Trace**                  | The record of one evaluator call: input, output, status.                          |
| **Judgment**               | The record of one judge call: score, rationale, determinism.                      |
| **TraceStore**             | The persistent backend for traces and judgments. Pluggable.                       |
| **Determinism**            | A judge's contract about replay behavior. Three classes; see ADR-0008.            |
| **Sampling-deterministic** | Byte-identical with a pinned seed and unchanged model. The honest description of "temperature=0 LLM judge." |
| **Replay**                 | Re-executing a stored run. Asserts the determinism contract.                     |
| **Aggregator**             | Computes summary metrics over a `JudgmentSet`.                                   |

---

## Further reading

- [`design.md`](design.md) — the implementation-level companion to this doc.
- [`architecture.md`](architecture.md) — system shape and tradeoffs.
- [`decisions/`](decisions/) — the why behind every major choice.
- [Diátaxis documentation framework](https://diataxis.fr/) — the four-quadrant model this doc series follows.