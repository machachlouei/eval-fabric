# Setup

This is the operational guide for getting `eval-fabric` running on a development machine and integrating it into a CI environment. If you are looking for the conceptual model, read [`concepts.md`](concepts.md) first.

---

## System requirements

| Requirement      | Version   | Notes                                                           |
| ---------------- | --------- | --------------------------------------------------------------- |
| Python           | 3.11+     | Uses `ExceptionGroup`, `Self`, `assert_type`. 3.10 will not work. |
| Operating system | macOS, Linux | Windows is not tested. WSL works.                              |
| Disk             | 1 GB free | The default SQLite trace store grows over time.                  |
| Network          | Outbound to your model providers | Required by most evaluators and LLM judges.   |

For the Postgres trace store: any Postgres ≥ 14.
For the Parquet trace store: any S3-compatible object store.

---

## Install

For most users:

```bash
pip install eval-fabric
```

For development (clone and editable install):

```bash
git clone https://github.com/your-org/eval-fabric.git
cd eval-fabric
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Optional extras:

| Extra        | Installs                              | Use                                                    |
| ------------ | ------------------------------------- | ------------------------------------------------------ |
| `postgres`   | `asyncpg`                             | Postgres trace store backend.                          |
| `parquet`    | `pyarrow`, `s3fs`                     | Parquet-on-S3 archival trace store.                    |
| `openai`     | `openai`                              | Reference `OpenAILLMJudge` and evaluator helpers.       |
| `anthropic`  | `anthropic`                           | Reference `AnthropicLLMJudge` and evaluator helpers.    |
| `dev`        | All of the above + test/lint tooling  | What you want for contributing.                         |

```bash
pip install "eval-fabric[postgres,openai]"
```

---

## Verify the install

```bash
ef --version
ef plugins list
ef plugins list --health      # imports all plugins; reports any that fail to load
```

If `ef plugins list` shows no plugins, no third-party plugin packages are installed. The framework's own built-in judges (rule-based, LLM, human-router) are always available under the `eval_fabric.*` namespace.

---

## Environment variables

The framework itself reads only one environment variable directly:

| Variable                  | Default | Meaning                                                       |
| ------------------------- | ------- | ------------------------------------------------------------- |
| `EVAL_FABRIC_LOG_LEVEL`   | `INFO`  | Stdlib log level for the framework's own logger.              |

Everything else flows through OpenTelemetry environment variables (`OTEL_*`) or through evaluator/judge config. We deliberately do not mint our own environment variables for things OTel already covers.

For OTel, the most useful are:

| Variable                          | Example                                  | Meaning                                          |
| --------------------------------- | ---------------------------------------- | ------------------------------------------------ |
| `OTEL_SERVICE_NAME`               | `eval-fabric`                            | Service identity for traces and metrics.         |
| `OTEL_TRACES_EXPORTER`            | `console`, `otlp`, `none`                | Where traces go.                                 |
| `OTEL_METRICS_EXPORTER`           | `console`, `otlp`, `none`                | Where metrics go.                                |
| `OTEL_EXPORTER_OTLP_ENDPOINT`     | `http://localhost:4318`                  | OTLP collector endpoint.                          |
| `OTEL_RESOURCE_ATTRIBUTES`        | `team=qa-platform,env=dev`               | Static labels attached to all telemetry.         |

Evaluators and judges read their own environment variables. The convention we recommend (and follow in shipped plugins) is `<TEAM>_<PURPOSE>_<KEY>`, e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. The framework does not interpret these.

---

## A first-run smoke test

```bash
# Generate an example spec and dataset
ef init --example hello-world ./hello

# Run it (uses the rule-based exact-match judge)
cd hello
ef run spec.yaml --dataset data.jsonl --concurrency 4

# Inspect
ef show ./runs/<run-id> --metric accuracy
```

If this completes successfully, your install is healthy. If not, see [Common failures](#common-failures).

---

## Dev workflow

We use `make` as the canonical interface to dev tasks. The Makefile is short and the targets do exactly what they say.

```bash
make help           # list targets
make test           # run pytest
make test-fast      # skip slow integration tests
make lint           # ruff + mypy
make format         # ruff format
make typecheck      # mypy only
make docs           # build docs locally
make clean          # remove .venv, .mypy_cache, .pytest_cache, etc.
```

If you are not a Makefile person, every target is a one-liner you can run directly. See `make help` for the equivalent commands.

### Typical inner loop

```bash
# 1. Edit code
# 2. Run focused tests
pytest tests/test_runner.py::test_concurrency_is_bounded -x

# 3. Lint and format on save (your editor or pre-commit handles this)
ruff check . && ruff format --check .

# 4. Run the full fast suite before pushing
make test-fast
```

### Pre-commit

We ship a `.pre-commit-config.yaml`. Install it once:

```bash
pre-commit install
```

It runs `ruff`, `ruff-format`, and a fast subset of `mypy` on every commit. A push will run the full suite in CI.

### Editor setup

The repo includes `.editorconfig` and editor settings as `editor/` subdirectories for VS Code and (sketch) JetBrains. The summary:

- Format with `ruff format` on save.
- Check with `ruff check` on save.
- Type-check with `mypy --strict` on save (or on demand if your machine is slow).
- Use Python 3.11 in the active interpreter.

We use 4-space indents and a 100-column line width. `ruff` enforces both.

---

## Running the test suite

```bash
pytest                              # everything
pytest -k runner                    # just runner tests
pytest -m "not slow"                # skip slow tests
pytest --cov=eval_fabric            # coverage
pytest -x --ff                      # exit on first failure, run failed-first
```

Most tests are fast (< 100 ms). The slow tier is gated behind `@pytest.mark.slow` and runs against real LLM providers. To run the slow tier locally:

```bash
EVAL_FABRIC_RUN_SLOW=1 pytest -m slow
```

You will need API keys exported. CI runs the slow tier on a schedule and on PRs that touch judge code.

For the testing philosophy, see [`testing.md`](testing.md).

---

## Connecting to a Postgres trace store

```bash
pip install "eval-fabric[postgres]"
```

Set the trace store URI in your spec or via environment:

```yaml
runtime:
  trace_store: postgres://user:pass@host:5432/eval_fabric
```

Initialize the schema once per database:

```bash
ef tracestore init postgres://user:pass@host:5432/eval_fabric
```

Subsequent runs will write to the database. The schema version is checked on every `open()`; mismatches block with a clear migration command.

---

## Common failures

### `ModuleNotFoundError: No module named 'eval_fabric'`

The package is not in your active environment. Activate the venv (`source .venv/bin/activate`) or reinstall.

### `ef: command not found`

The `ef` entry point is installed but not on PATH. Either activate the venv where you installed it, or run `python -m eval_fabric` instead.

### `SpecValidationError: schema_version=2 is not supported by this framework`

The spec is newer than the framework. Upgrade the framework (`pip install -U eval-fabric`).

### `SpecValidationError: schema_version=1 is supported; current major is 2`

The spec is older than the framework's current major. Migrate it:

```bash
ef migrate spec.yaml --to 2 --output spec.v2.yaml
```

The migration is reversible-by-checkout: your old file is unchanged.

### `OSError: [Errno 24] Too many open files`

You have a high `max_concurrent` and your OS file-descriptor limit is the typical 1024 default. Either lower concurrency or raise the limit (`ulimit -n 8192` on macOS/Linux).

### `RuntimeError: This event loop is already running`

You are calling `runner.run()` (sync) from inside an async context. Use `await runner.run_async()` instead.

### `httpx.RemoteProtocolError` from an LLM judge

Almost always a 429 rate-limit pretending to be a connection error. Lower the judge's `max_concurrent` or add backoff. See the troubleshooting section in `observability.md`.

### `TraceStoreError: schema mismatch (store=3, framework=4)`

The trace store was initialized by an older framework version. Run the migration:

```bash
ef tracestore migrate <store-uri> --to 4
```

### Telemetry not showing up

The most common cause is `OTEL_TRACES_EXPORTER` defaulting to `none` in production. Set it explicitly. For local debugging:

```bash
export OTEL_TRACES_EXPORTER=console
ef run spec.yaml --dataset data.jsonl
```

You should see span output on stderr.

---

## CI integration

A typical CI configuration:

```yaml
# .github/workflows/eval.yml
name: eval

on:
  pull_request:
    paths:
      - "src/**"
      - "evals/**"

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install eval-fabric
      - run: ef run evals/qa_bot.yaml --dataset evals/qa_bot.jsonl --output ./runs
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      - run: ef gate ./runs --baseline main --metric accuracy --min 0.85
```

`ef gate` exits non-zero if the metric falls below the threshold (or below the baseline run by more than a configured delta). This is the primary CI integration.

---

## Where things live on disk

```
<your-repo>/
  evals/
    qa_bot.yaml           # EvalSpec
    qa_bot.jsonl          # Dataset
  runs/                   # Default trace store location (gitignored)
    runs.db
    <run-id>/
      result.json
      traces.parquet      # If using Parquet backend
```

The `runs/` directory should be gitignored. Trace data is large and your VCS is the wrong place for it.