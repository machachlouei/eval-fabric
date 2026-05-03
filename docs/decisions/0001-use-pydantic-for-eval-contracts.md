# 0001. Use Pydantic v2 for eval contracts

* **Status:** Accepted
* **Date:** 2026-01-12
* **Deciders:** Eval-fabric core team
* **Tags:** schema, contracts

## Context and problem statement

Every component in `eval-fabric` operates on shared data structures: `EvalSpec`, `EvalItem`, `Trace`, `Judgment`, `RunResult`. These structures cross many boundaries:

- Loaded from YAML or JSON files written by humans.
- Passed between in-process Python components (runner, registry, judges).
- Persisted to disk in a TraceStore.
- Returned from a CLI command and consumed by CI as JSON.
- Exposed through a Python SDK that many teams will import.

We need a single representation that gives us: runtime validation at the boundaries, IDE/type-checker support, JSON schema generation for downstream consumers, and ergonomic construction for plugin authors.

## Decision drivers

* Validation must happen at every untrusted boundary (file load, HTTP request, plugin output).
* Plugin authors should not be required to learn a foreign serialization framework to define their inputs/outputs.
* Schema must be machine-readable so we can generate JSON Schema for editor autocompletion and documentation.
* Validation overhead must be low (≤ 1 ms for a typical EvalSpec) because validation runs on every command.
* The contracts will evolve. We need a story for forward and backward compatibility.

## Considered options

1. **Plain dataclasses with `__post_init__` validation.** Standard library only.
2. **Pydantic v2 models.** External dependency, mature, widely used in modern Python.
3. **Protobuf with a generated Python client.** Strong typing, cross-language, schema-first.
4. **attrs with cattrs for serialization.** Well-regarded alternative to Pydantic.

## Decision

We chose **Pydantic v2 models** for all eval contracts.

## Consequences

### Positive

- Single source of truth: model definitions are also our schema, our validator, and our JSON Schema generator.
- Plugin authors write idiomatic Python with type annotations and get validation for free.
- IDE support and `mypy` integration are excellent and require no glue code.
- Pydantic v2's Rust core puts validation overhead well under our 1 ms target for typical specs.
- `model_config = ConfigDict(frozen=True, extra="forbid")` enforces immutability and rejects unknown fields, which catches a class of typo bugs at load time.

### Negative

- We take a runtime dependency on Pydantic v2. Major Pydantic releases have historically been disruptive (v1 → v2 was a six-month migration for many projects).
- Pydantic does not give us cross-language schema enforcement. If we later need Java or Go evaluators, we will have to add Protobuf or JSON Schema wire validation.
- Generated JSON Schema is good but not perfect — recursive types and discriminated unions sometimes need manual schema overrides.

### Neutral

- We are now constrained to a particular validation idiom across the codebase. Consistency is good; flexibility is reduced.

## Pros and cons of the options

### Option 1 — Plain dataclasses

* ✅ No external dependency.
* ✅ Stdlib only; trivial to package.
* ❌ No built-in validation; we would have to write `__post_init__` for every model.
* ❌ No JSON Schema generation; we would have to maintain it by hand.
* ❌ Serialization to/from YAML and JSON is manual.

### Option 2 — Pydantic v2 (chosen)

* ✅ Validation, serialization, JSON Schema, and IDE support in one package.
* ✅ Rust-backed performance.
* ✅ Massive community and ecosystem (FastAPI, LangChain, etc.).
* ❌ External dependency with a history of breaking changes.
* ❌ Tighter coupling: removing it later would touch every contract.

### Option 3 — Protobuf

* ✅ Strong typing, cross-language, schema-first.
* ✅ Wire-format efficiency.
* ✅ Battle-tested at scale at Google, Apple, etc.
* ❌ Generated Python code is awkward to use (no real types, ugly attribute access).
* ❌ Adds a build step (`protoc`) to the developer workflow.
* ❌ Plugin authors must learn `.proto` syntax to add fields.
* ❌ JSON Schema is not native; we would still need to translate.
* ❌ Most importantly: this is a Python framework with a JSON-on-the-wire boundary at the optional HTTP API. We do not get the cross-language win until we have non-Python consumers, which we do not have today.

### Option 4 — attrs + cattrs

* ✅ Excellent design, lighter than Pydantic.
* ✅ Good performance.
* ❌ Smaller ecosystem; less community knowledge among prospective users.
* ❌ JSON Schema generation is a separate library and is not as polished.
* ❌ Pydantic v2 closed most of attrs' historical advantages.

## When we would revisit this

- If we add non-Python evaluators or judges (Java, Go, Rust). Cross-language enforcement becomes a hard requirement and Protobuf becomes the right choice.
- If Pydantic v3 forces another major migration. We will reassess at that point.
- If validation overhead becomes a measurable percentage of run time, which is unlikely for our workload.

## Links

* [Pydantic v2 release notes](https://docs.pydantic.dev/latest/migration/)
* [ADR-0004 — Eval-spec versioning with semver and codegen](0004-eval-spec-versioning-with-semver-and-codegen.md)