# 0004. EvalSpec versioning with semver and codegen migrations

* **Status:** Accepted
* **Date:** 2026-01-22
* **Deciders:** Eval-fabric core team
* **Tags:** schema, contracts, versioning, migrations

## Context and problem statement

`EvalSpec` is the most-shared data structure in the framework. Every team writes them. Every CI pipeline consumes them. Every persisted run record references one. Once we ship v1, we cannot change a field without a story for how every existing spec keeps working.

We must answer two related questions:

1. **How is an EvalSpec versioned?** What is the contract between a spec author writing `version: 1.2.0` and the framework reading it?
2. **What happens when we want to add a field, rename a field, or drop a field?**

Specs are committed to version control by every team using the framework. We do not control them. A migration story that requires teams to manually edit thousands of YAML files is a non-starter.

## Decision drivers

* Teams must be able to write specs once and have them keep working across minor framework upgrades.
* Breaking changes must be possible — the schema will be wrong about something — but they must be rare and well-managed.
* Persisted run records (which embed an EvalSpec) must remain readable indefinitely. Old runs are evidence; we cannot retroactively invalidate them.
* Migrations must be tested. Saying "we have a migration" is not enough; the migration must be exercised on real specs in CI.

## Considered options

1. **No versioning.** Spec is whatever the current `EvalSpec` Pydantic model says it is. Any change is a breaking change.
2. **Semver on the framework only.** Spec evolution is handled by Pydantic's `extra="ignore"` defaults.
3. **Semver on the spec schema, separate from framework version. Codegen migrations.** Two version fields. Migrations are versioned scripts.
4. **JSON Schema with `$schema` URL versioning.** Each major version of the schema gets its own URL.

## Decision

We chose **a separate semver on the EvalSpec schema, with codegen migration scripts**.

Concretely:

- `EvalSpec` carries a `schema_version: Literal["1"]` field. The string is the **major** version of the schema.
- Each minor or patch evolution within a major version is backward compatible: new fields have defaults, no field changes meaning.
- Each major version has a codegen migration in `eval_fabric.spec.migrations.v1_to_v2`, exercised in CI on a corpus of test specs.
- The framework version (the `eval-fabric` package version) follows its own semver and may move independently.

```python
class EvalSpecV1(BaseModel):
    schema_version: Literal["1"] = "1"
    # ...

class EvalSpecV2(BaseModel):
    schema_version: Literal["2"] = "2"
    # ...

def migrate_v1_to_v2(spec: EvalSpecV1) -> EvalSpecV2:
    """Promote a v1 spec to v2. Pure, no I/O."""
    ...
```

Loading a YAML file dispatches on `schema_version` and applies any needed migrations to reach the current major version.

## Consequences

### Positive

- **Old specs keep working.** A v1 spec loads, migrates in memory, and runs against the current framework, indefinitely.
- **Persisted runs remain readable.** Each run stores the spec version it was created with. Reading old runs migrates lazily.
- **Migrations are testable.** Every PR runs the migration suite against a frozen corpus of historical specs and rejects regressions.
- **Schema and framework versions are independent.** We can ship six framework releases without changing the spec schema, or vice versa.

### Negative

- **More code.** Every breaking change requires writing and testing a migration. This is the cost of the property we want.
- **Migrations are forward-only.** We do not support v2 → v1. If you persist a run in v2 and then downgrade the framework, it will not load.
- **Schema documentation must be versioned.** The `docs/spec-reference.md` page now needs major-version subsections.

### Neutral

- We need a corpus of test specs. We start with the examples shipped in `examples/` and grow it from real specs contributed by early adopters.

## Migration policy

Three rules govern when a change is breaking:

1. **Renaming a field is breaking.** Add the new name, keep the old as a deprecated alias for one minor version, then remove with a major bump.
2. **Removing a field is breaking.** Same deprecation cycle.
3. **Changing a field's semantics without renaming it is forbidden.** Always rename. The cost of "I think this field used to mean something different" debugging is higher than the cost of a new field name.

Changes that are **not** breaking:

- Adding an optional field with a default.
- Adding a new value to an enum where the framework treats unknown values as a soft error (we do this for evaluator/judge IDs).
- Tightening a constraint where no real spec violates the new constraint (rare but possible).

## Pros and cons of the options

### Option 1 — No versioning

* ✅ Simplest possible thing.
* ❌ Every schema change breaks every existing spec. Unacceptable at multi-team scale.

### Option 2 — Framework-version-only semver

* ✅ One version to think about.
* ❌ Conflates the schema with the framework. We cannot ship a framework patch without implicitly committing to keeping the schema unchanged.
* ❌ Pydantic's `extra="ignore"` is a footgun: misspelled fields silently disappear instead of raising.

### Option 3 — Separate schema semver + migrations (chosen)

* ✅ Clean separation of concerns.
* ✅ Migrations are testable artifacts.
* ✅ Persisted runs remain readable.
* ❌ More code. More tests. More discipline.

### Option 4 — JSON Schema with `$schema` URL

* ✅ Standards-compliant.
* ✅ Works across languages.
* ❌ The migration story is exactly the same as Option 3, with extra ceremony.
* ❌ Pydantic v2 generates JSON Schema for us; we lose nothing by using semver in the model directly.

## Implementation notes

- Migrations live in `eval_fabric/spec/migrations/`.
- The migration suite runs as part of every PR via a `tests/test_migrations.py` that walks a corpus of real specs and asserts each migrates cleanly to the current major version.
- Every migration is pure: it takes a Pydantic model in the old version and returns one in the new version. No I/O, no global state.
- We do not generate migrations automatically. Every migration is hand-written and reviewed because the semantics are not always mechanical.

## Links

* [Semantic Versioning 2.0.0](https://semver.org/)
* [ADR-0001 — Use Pydantic v2 for eval contracts](0001-use-pydantic-for-eval-contracts.md)
* [ADR-0005 — TraceStore as Protocol](0005-trace-store-as-protocol.md)