# Contributing

Thank you for considering a contribution to `eval-fabric`. This document is the contract between maintainers and contributors. It describes how we work, what we expect from a change, and how reviews are conducted.

It is opinionated. The opinions are how the project stays maintainable as it grows.

---

## Before you start

A few things worth checking before you write code.

### Is this the right place for the change?

The framework is small on purpose. Many things look like they belong in the framework but don't:

- A new metric? It probably belongs in the aggregator's user-defined metrics, not in the framework's metric set.
- A new judge model? It probably belongs in your team's plugin package, not in `eval_fabric.judges.builtin`.
- A new trace-store backend? It probably belongs in `eval_fabric.contrib` or a separate package, depending on its dependency footprint.

If you are not sure, **open an issue first** and describe the change. Discussing in an issue is cheap; rewriting a PR after maintainer feedback is expensive.

### Is there an ADR for this?

Anything that touches the public API surface, the EvalSpec schema, or the core protocols (`Evaluator`, `Judge`, `TraceStore`) needs an ADR before code lands. See [`docs/decisions/0000-madr-template.md`](docs/decisions/0000-madr-template.md). Open the ADR as a draft PR; reviewers focus on the decision before discussing implementation.

Smaller changes — bug fixes, internal refactors, documentation, new tests — do not need an ADR.

### Has this been discussed?

Search existing issues and PRs. If your idea has been raised and rejected, the issue thread will explain why. Reviving a closed discussion is welcome but please reference the prior thread and explain what new information justifies revisiting.

---

## Branching strategy

We use **trunk-based development** with short-lived feature branches.

- `main` is always releasable. Never push directly; always go through a PR.
- Feature branches are named `<author>/<short-description>`, e.g., `mna/add-postgres-batching`.
- Branches live for hours to days, not weeks. Long-lived branches accumulate merge conflicts and reviewer fatigue.
- Merges into `main` are **squash merges**. The PR title becomes the commit message.

Releases are cut from `main` by tagging:

```bash
git tag -a v0.5.2 -m "release: 0.5.2"
git push --tags
```

We do not maintain release branches. Hotfixes are PRs into `main` followed by a new tag.

---

## Pull request expectations

A PR is a unit of review. It should be reviewable in one sitting.

### What a good PR looks like

- **One purpose.** A PR fixes one bug, adds one feature, or refactors one thing. Mixing concerns triples review time.
- **Small.** Aim for under 400 lines of diff (excluding generated files and test fixtures). Larger PRs are sometimes necessary; if so, explain why in the description.
- **Tested.** Code paths exercised by the change should have tests. Test changes should explain *why*, not just *what*.
- **Documented.** If you changed behavior, the docs are part of the PR. If you added a public API, the docstring is part of the PR.
- **Linted.** Pre-commit hooks should leave nothing for the reviewer to flag.

### PR description template

The repo includes a `.github/PULL_REQUEST_TEMPLATE.md`. The fields:

- **What & Why.** A few sentences. What does this change, and what problem does it solve?
- **How.** A few sentences on approach. Helpful when the change is non-obvious.
- **Testing.** What did you run? What edge cases did you consider?
- **Risk.** What could go wrong with this change in production? Be honest.
- **Linked issue / ADR.** If applicable.

We do not require every field to be filled in for trivial changes, but reviewers will ask for the ones that matter.

### Required CI checks

Every PR must pass:

- `lint` (ruff + ruff-format)
- `typecheck` (mypy --strict on `src/`)
- `test-fast` (pytest excluding slow tier)
- `docs` (the docs build cleanly)
- `pip-audit` (no new high-severity CVEs introduced)

The slow test tier (real LLM calls) runs on a label or on `main`-bound merges. PRs touching judge code should include the `run-slow-tests` label.

### Reviewers and approvals

- One approval from a maintainer is required to merge.
- Two approvals are required for changes to: public API surface, EvalSpec schema, core protocols, or any ADR.
- Maintainers cannot self-approve their own PRs.
- A reviewer's "request changes" must be resolved (either by a follow-up commit or by discussion that the reviewer dismisses) before merge.

If you do not get a review within 3 business days, ping the issue or the project Slack channel. We aim for faster but reality intrudes.

---

## Review philosophy

How we review, and what we are looking for.

### What reviewers focus on

In rough priority order:

1. **Is this the right change?** Does it solve a real problem in a way the framework should solve it? An expertly-implemented wrong solution is worse than a clumsy right one.
2. **Are the tradeoffs honest?** Does the PR description acknowledge what gets harder, not just what gets easier?
3. **Will this age well?** Will the next person reading this code in two years understand it without us?
4. **Are the tests load-bearing?** Do they assert invariants, or do they assert implementation?
5. **Style and idiom.** Last priority, but not zero. Consistency matters.

### What reviewers do not do

- We do not block on style nits. The linter handles those. If you find yourself typing "consider renaming this," ask whether it actually matters.
- We do not gatekeep on familiarity. Newcomers' code may look unconventional because they have not absorbed the local idioms yet. We say so kindly and explain the convention.
- We do not require perfect on the first round. A merge-ready PR after three rounds is better than a perfect PR that took two months.

### What contributors should expect

- Reviews are direct. We say what we mean. If something is wrong, we say it is wrong. Tone aspires to "respectful and clear," not "encouraging at all costs."
- Reviewers explain their reasoning. "This is wrong" without explanation is not acceptable; the reviewer owes you a reason.
- Disagreements are normal. If you think a reviewer is wrong, push back. Reviewers expect to be wrong sometimes; saying so is welcome.
- Final decisions on contested calls go to the maintainers listed in `MAINTAINERS.md`.

### What contributors should not expect

- A reviewer to rewrite your PR for you. We will suggest changes, sometimes very specific ones, but the work is yours.
- A free pass on tests because the change "is small." Small changes break things just as effectively as large ones.

---

## Coding standards

We use modern Python and a small, opinionated set of tools. Most of this is enforced by the linter; the points below are the ones the linter cannot enforce.

### Python

- **Python 3.11+.** No `from __future__ import` boilerplate; no `typing.List` / `typing.Dict` (use lowercase `list` / `dict`).
- **Type-annotate everything in the public API.** Internal helpers can omit annotations if it would obscure the intent, but err on the side of annotating.
- **Use `pathlib.Path`, not `os.path`.**
- **Use `match` statements where they read more clearly than `if/elif`.** Don't force them where they don't.
- **Prefer composition to inheritance.** Inheritance for behavior reuse is rarely the right answer in this codebase.

### Imports

- Sorted by `ruff` (matches `isort` profile=black).
- No `from x import *`.
- No conditional imports inside functions for "lazy load" purposes unless there is a measurable startup-time reason. Leave a comment when you do this.

### Naming

- `snake_case` for functions, methods, variables.
- `PascalCase` for classes.
- `UPPER_SNAKE` for constants.
- Type variables are `T`, `T_co`, `T_contra`. We do not name them descriptively.
- Avoid abbreviations except established ones (`url`, `id`, `pkg`).

### Docstrings

- Public functions, classes, and modules have docstrings.
- Use Google style (sections: `Args`, `Returns`, `Raises`).
- The first line is a sentence ending in a period, fitting on one line.
- Examples in docstrings are great; if you write one, the doctest suite will run it.

### Error messages

This is where staff-level care shows. A good error message:

- States what went wrong.
- States what the user can do about it.
- Includes the relevant identifiers (run ID, plugin ID, file path).

Bad: `ValueError: invalid value`
Good: `SpecValidationError: judges[0].weight=-0.5 is invalid (must be >= 0.0). See spec.yaml line 14.`

### Tests

See [`docs/testing.md`](docs/testing.md). The short version:

- Unit tests are pure and fast.
- Integration tests use fakes for external services.
- Slow tests (real LLM calls) are gated by `EVAL_FABRIC_RUN_SLOW=1`.
- Property tests use `hypothesis` for protocols and aggregator math.
- Test names describe the property being tested, not the function being tested. `test_runner_persists_before_completing` not `test_runner_run`.

### Comments

- Comments explain *why*, not *what*. The code says what it does.
- A comment that restates the next line is noise. A comment that explains a non-obvious choice is gold.
- TODO comments include an owner and a tracking issue: `# TODO(mna): batch trace persistence — see #421`.

---

## Documentation

Documentation is a first-class deliverable. PRs that change behavior without updating docs will be asked to update docs before merge.

- New public API → docstring + a sentence in `docs/design.md` if it touches the public surface.
- New configuration → a row in `docs/setup.md`.
- New observability surface → a row in `docs/observability.md`.
- New ADR-worthy decision → an ADR in `docs/decisions/`.
- Breaking change → an entry in the changelog and a migration note in `ROADMAP.md`.

Docs are markdown. They build with `mkdocs` (`make docs`) but should also read well as plain markdown on GitHub.

---

## Issue triage

If you are reporting a bug:

- **Reproducible test case.** Even better, a failing PR.
- **Framework version.** `pip show eval-fabric`.
- **Python version.** `python --version`.
- **What you did, what you expected, what happened.** In that order.

If you are proposing a feature:

- **What problem are you solving?** Not "I want X" but "I am trying to do Y and X would help."
- **Have you considered alternatives?** Even a brief list helps.
- **What is the cost of *not* doing this?** Sometimes a feature is nice; sometimes it is essential.

We close issues that are off-topic, duplicate, or stale (no reply for 60 days). Closed does not mean unwelcome — feel free to reopen with new information.

---

## Maintainers

Maintainers are listed in `MAINTAINERS.md` with their areas of focus. They have merge rights, can resolve contested PRs, and own release decisions.

The path to becoming a maintainer is contribution. After several substantive merged PRs and demonstrated thoughtful review of others' PRs, current maintainers may invite you to join. There is no formal application.

---

## Code of conduct

We follow the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) v2.1. The summary: be respectful, assume good intent, disagree about ideas not people. Maintainers will enforce this.

Report code-of-conduct concerns to `conduct@<your-org>.example`. Reports are confidential.

---

## License

By contributing, you agree that your contributions are licensed under the project's [Apache 2.0 license](LICENSE). You retain copyright to your contributions; you grant the project the right to distribute them under that license.

We do not require a CLA. The Apache 2.0 license includes the contributor grants we need.