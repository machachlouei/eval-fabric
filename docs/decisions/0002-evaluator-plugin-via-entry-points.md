# 0002. Evaluator and judge plugins via Python entry points

* **Status:** Accepted
* **Date:** 2026-01-15
* **Deciders:** Eval-fabric core team
* **Tags:** plugins, registry, extensibility

## Context and problem statement

A core design goal of `eval-fabric` is that teams can ship their own evaluators and judges without modifying the framework. We need a discovery mechanism — a way for a team to install a Python package and have its plugins become available to `ef run` automatically.

The choice of plugin model has long-tail consequences. It shapes how plugins are tested, how they are versioned, how they are isolated, and how easy it is to write one. Choosing badly here is not easy to undo: every existing plugin would need to be rewritten.

## Decision drivers

* Plugin authors should be able to write a plugin in ≤ 50 lines of code without inheriting from a framework class.
* Plugins should be installable as standard Python packages (`pip install our-evaluators`).
* The framework must not have to be modified to add a plugin.
* Plugin discovery must be lazy — installing a package with 50 plugins should not import all 50 at framework startup.
* Plugins must be testable in isolation, without standing up a runner.
* The mechanism should be one that experienced Python developers already know.

## Considered options

1. **Abstract base class hierarchy.** `class MyJudge(BaseJudge): ...`, with framework providing the base.
2. **Python entry points (`importlib.metadata`).** Same mechanism `pytest`, `flake8`, and `setuptools` use for plugins.
3. **Explicit registration only.** No discovery; every plugin imported and registered manually.
4. **Plugin manifest file.** A YAML file listing plugin paths and import targets.

## Decision

We chose **Python entry points + Protocol typing for plugin discovery**, with **explicit registration** also supported as a secondary path for local plugins.

Concretely:

```toml
# pyproject.toml of a plugin package
[project.entry-points."eval_fabric.evaluators"]
my_team__qa_bot = "my_team.evaluators:qa_bot"

[project.entry-points."eval_fabric.judges"]
my_team__style = "my_team.judges:style_judge"
```

```python
# In application code that has not packaged its plugins
from eval_fabric.registry import register_evaluator
register_evaluator("my_team.qa_bot", factory=qa_bot)
```

Both paths converge on the same registry. The framework duck-types every loaded plugin against the `Evaluator` or `Judge` Protocol at registration time and rejects mismatches with a clear error.

## Consequences

### Positive

- Plugins are standard Python packages. CI, packaging, versioning, and dependency management work out of the box.
- The framework has no special knowledge of any plugin. We can ship a release without touching plugin code.
- `Protocol`-based duck typing means plugins do not import anything from `eval_fabric` to be valid plugins. They can be tested in isolation as plain async functions.
- Entry points are lazy. The framework discovers the plugin's existence at startup but does not import its module until the plugin is actually requested.
- Pattern is familiar: anyone who has written a `pytest` plugin already knows this model.

### Negative

- Entry points require installing the plugin package. For local development, plugin authors need a `pip install -e .` step. We mitigate this with the explicit-registration path for ad-hoc or notebook use.
- Discovery is process-global. Two different plugin packages cannot register the same ID even if they intend to coexist behind feature flags. The fix is namespacing (`team_name.plugin_name`) which we enforce at registration.
- Without inheritance, common functionality (rate limiting, retry decoration, observability) is not provided by a base class. We address this with composable helpers in `eval_fabric.evaluators.helpers` rather than a class hierarchy. This is more flexible but slightly less discoverable to newcomers.

### Neutral

- Plugins do not have a place to put state shared with the framework (e.g., a context manager for setup/teardown). We added optional `setup()` and `teardown()` lifecycle hooks called by the runner if defined. Plugins that do not need them simply do not define them.

## Pros and cons of the options

### Option 1 — Abstract base class hierarchy

* ✅ Familiar to OO developers from Java/C# backgrounds.
* ✅ Base class can offer convenience methods (logging, retry, timing).
* ❌ Couples plugins to a framework version. Major framework releases break every plugin.
* ❌ Harder to test in isolation — instantiating a base class often pulls in framework state.
* ❌ Inheritance hierarchies grow over time. `BaseJudge → LLMJudge → OpenAIJudge → CachedOpenAIJudge` is a real pattern in popular eval frameworks, and it ages badly.
* ❌ Multiple inheritance gets weird fast when plugins want to mix in retry, caching, etc.

### Option 2 — Entry points + Protocols (chosen)

* ✅ Battle-tested at scale in `pytest`, `setuptools`, `flake8`, `pip`.
* ✅ Plugins are decoupled from the framework's class hierarchy.
* ✅ Lazy discovery; minimal startup cost.
* ✅ Standard Python packaging model.
* ❌ Requires `pip install` for non-local plugins; we provide explicit registration as a fallback.
* ❌ Protocols are slightly less guided than base classes — IDEs do not autocomplete a method signature you have not yet written.

### Option 3 — Explicit registration only

* ✅ Simple. No magic. No discovery.
* ❌ Every plugin must be imported by user code before use. Onboarding and sharing a plugin across teams becomes friction-heavy.
* ❌ Does not scale to 50 teams contributing plugins.

### Option 4 — Plugin manifest file

* ✅ Auditable list of installed plugins.
* ❌ A second source of truth alongside the actual installed packages. They drift.
* ❌ Reinvents what entry points already give us, with worse tooling.

## Implementation notes

- Entry-point loading uses `importlib.metadata.entry_points(group="eval_fabric.evaluators")`.
- Each entry point's metadata can declare a compatible major version range via the `eval_fabric_compat` dist-info field. The registry rejects plugins whose declared range excludes the running framework version.
- A plugin failing to import does not crash the framework. The error is captured, logged, and surfaced via `ef plugins list --health`.

## Links

* [Setuptools entry points documentation](https://packaging.python.org/en/latest/specifications/entry-points/)
* [pytest plugin model](https://docs.pytest.org/en/stable/how-to/writing_plugins.html)
* [PEP 660](https://peps.python.org/pep-0660/) — editable installs
* [ADR-0007 — Separate Evaluator and Judge](0007-separate-evaluator-and-judge.md)