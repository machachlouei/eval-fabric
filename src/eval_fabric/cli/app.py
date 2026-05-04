"""Implementation of the ``ef`` CLI commands.

Click is the only CLI toolkit. Argument parsing and pretty-printing live in
this module; the heavy lifting always delegates back to the SDK.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import click

from eval_fabric import __version__
from eval_fabric.dataset import load_jsonl_async
from eval_fabric.errors import EvalFabricError
from eval_fabric.registry import list_evaluators, list_judges
from eval_fabric.runner import Runner
from eval_fabric.spec import EvalSpec, dump_spec, load_spec
from eval_fabric.tracestore import open_trace_store


def _configure_logging() -> None:
    level = os.environ.get("EVAL_FABRIC_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )


@click.group()
@click.version_option(__version__, prog_name="ef")
def main() -> None:
    """eval-fabric CLI."""

    _configure_logging()


# ---------------------------------------------------------------------------
# `ef run`
# ---------------------------------------------------------------------------


@main.command("run")
@click.argument("spec_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--concurrency", type=int, default=None, help="Override runtime.max_concurrent.")
@click.option("--max-items", type=int, default=None, help="Stop after N items.")
@click.option("--output", "output_dir", type=click.Path(path_type=Path), default=Path("./runs"))
@click.option("--trace-store", type=str, default=None, help="Override trace-store URI.")
def run_cmd(
    spec_path: Path,
    dataset_path: Path,
    concurrency: int | None,
    max_items: int | None,
    output_dir: Path,
    trace_store: str | None,
) -> None:
    """Execute SPEC_PATH against the dataset.

    Writes the run to the configured trace store and prints a one-line
    summary plus the new run id.
    """

    spec = load_spec(spec_path)
    if concurrency is not None or trace_store is not None:
        spec = spec.model_copy(
            update={
                "runtime": spec.runtime.model_copy(
                    update={
                        **(
                            {"max_concurrent": concurrency}
                            if concurrency is not None
                            else {}
                        ),
                        **({"trace_store": trace_store} if trace_store else {}),
                    }
                )
            }
        )

    items = anyio.run(load_jsonl_async, dataset_path)
    if max_items is not None:
        items = items[:max_items]

    runner = Runner(spec=spec, dataset=items)
    try:
        result = runner.run()
    except EvalFabricError as exc:
        raise click.ClickException(str(exc)) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{result.id}.json"
    out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    click.echo(
        f"run={result.id} status={result.status} "
        f"items={result.dataset_size} "
        f"counts={json.dumps(result.counts)} "
        f"cost_usd={result.total_cost_usd:.4f}"
    )
    for metric in result.metrics:
        click.echo(f"  metric.{metric.name}: {metric.value}")
    click.echo(str(out_path))


# ---------------------------------------------------------------------------
# `ef show`
# ---------------------------------------------------------------------------


@main.command("show")
@click.argument("run_id", type=str)
@click.option("--store", "store_uri", type=str, default="sqlite:///./runs/runs.db")
@click.option("--metric", "metric_name", type=str, default=None)
@click.option("--traces", is_flag=True, help="Print every persisted trace.")
@click.option("--status", "status_filter", type=str, default=None)
def show_cmd(
    run_id: str,
    store_uri: str,
    metric_name: str | None,
    traces: bool,
    status_filter: str | None,
) -> None:
    """Print a stored run's summary, optionally drilling into traces."""

    async def _show() -> None:
        store = open_trace_store(store_uri)
        await store.open()
        try:
            run = await store.get_run(run_id)
        except EvalFabricError as exc:
            raise click.ClickException(str(exc))

        click.echo(f"id: {run.id}")
        click.echo(f"spec: {run.spec_id}@{run.spec_version}")
        click.echo(f"status: {run.status}")
        click.echo(f"counts: {json.dumps(run.counts)}")
        click.echo(f"total_cost_usd: {run.total_cost_usd}")
        for m in run.metrics:
            if metric_name and m.name != metric_name:
                continue
            click.echo(f"  metric.{m.name}: {m.value} (n={m.n})")

        if traces:
            allowed = set((status_filter or "").split(",")) if status_filter else None
            async for tr in store.query_traces(run_id):
                if allowed and tr.status not in allowed:
                    continue
                click.echo(
                    f"  trace {tr.id} item={tr.item_id} "
                    f"status={tr.status} attempt={tr.attempt}"
                    + (f" error={tr.error}" if tr.error else "")
                )

        await store.close()

    anyio.run(_show)


# ---------------------------------------------------------------------------
# `ef plugins list`
# ---------------------------------------------------------------------------


@main.group("plugins")
def plugins_group() -> None:
    """Inspect the plugin registry."""


@plugins_group.command("list")
@click.option("--health", is_flag=True, help="Imports each plugin and reports load errors.")
def plugins_list_cmd(health: bool) -> None:
    evaluators = list_evaluators()
    judges = list_judges()
    click.echo("evaluators:")
    for record in evaluators:
        suffix = ""
        if health and not record.healthy:
            suffix = f" UNHEALTHY: {record.load_error}"
        click.echo(f"  - {record.id} ({record.source}){suffix}")
    click.echo("judges:")
    for record in judges:
        suffix = ""
        if health and not record.healthy:
            suffix = f" UNHEALTHY: {record.load_error}"
        click.echo(f"  - {record.id} ({record.source}){suffix}")


# ---------------------------------------------------------------------------
# `ef init`
# ---------------------------------------------------------------------------


@main.command("init")
@click.argument("target", type=click.Path(path_type=Path))
@click.option("--example", type=click.Choice(["hello-world"]), default="hello-world")
@click.option("--evaluator", "evaluator_id", type=str, default=None)
@click.option("--judge", "judge_id", type=str, default=None)
def init_cmd(
    target: Path,
    example: str,
    evaluator_id: str | None,
    judge_id: str | None,
) -> None:
    """Scaffold a minimal eval at TARGET.

    The default example pairs a built-in echo evaluator with the
    ``eval_fabric.exact_match`` judge, runnable end-to-end with no API keys.
    """

    target.mkdir(parents=True, exist_ok=True)
    spec_path = target / "spec.yaml"
    data_path = target / "data.jsonl"
    eid = evaluator_id or "eval_fabric.examples.echo"
    jid = judge_id or "eval_fabric.exact_match"

    spec_yaml = (
        "schema_version: '1'\n"
        f"id: examples/{example}\n"
        "version: 0.1.0\n"
        f"description: Generated by `ef init` for the {example} example.\n"
        "evaluator:\n"
        f"  id: {eid}\n"
        "judges:\n"
        f"  - id: {jid}\n"
        "scoring:\n"
        "  metrics:\n"
        "    - name: accuracy\n"
        "      from: judges\n"
        "      aggregator: mean\n"
        "runtime:\n"
        "  max_concurrent: 4\n"
        f"  trace_store: sqlite:///{(target / 'runs.db').as_posix()}\n"
    )
    spec_path.write_text(spec_yaml, encoding="utf-8")

    data_path.write_text(
        "\n".join(
            json.dumps({"item_id": f"item-{i}", "input": s, "reference_output": s})
            for i, s in enumerate(["hello", "world", "eval-fabric"])
        )
        + "\n",
        encoding="utf-8",
    )

    click.echo(f"wrote {spec_path}")
    click.echo(f"wrote {data_path}")
    click.echo(f"next: ef run {spec_path} --dataset {data_path}")


# ---------------------------------------------------------------------------
# `ef gate`
# ---------------------------------------------------------------------------


@main.command("gate")
@click.argument("run_path", type=click.Path(exists=True, path_type=Path))
@click.option("--metric", "metric_name", type=str, required=True)
@click.option("--min", "min_value", type=float, required=True)
def gate_cmd(run_path: Path, metric_name: str, min_value: float) -> None:
    """Exit non-zero if the named metric on the most recent run is below threshold.

    The run is loaded from a JSON artifact written by ``ef run``. CI pipelines
    point this at the file emitted by their previous step.
    """

    if run_path.is_dir():
        candidates = sorted(run_path.glob("run_*.json"))
        if not candidates:
            raise click.ClickException(f"no run artifacts found in {run_path}")
        run_path = candidates[-1]
    data: Any = json.loads(run_path.read_text(encoding="utf-8"))
    metrics = data.get("metrics", [])
    matched = next((m for m in metrics if m["name"] == metric_name), None)
    if matched is None:
        raise click.ClickException(
            f"metric {metric_name!r} not present in {run_path}"
        )
    value = matched["value"]
    if not isinstance(value, (int, float)):
        raise click.ClickException(
            f"metric {metric_name!r}={value!r} is not numeric; cannot gate"
        )
    if float(value) < min_value:
        click.echo(f"FAIL {metric_name}={value} < min={min_value}", err=True)
        sys.exit(1)
    click.echo(f"OK {metric_name}={value} >= min={min_value}")


# ---------------------------------------------------------------------------
# `ef tracestore init`
# ---------------------------------------------------------------------------


@main.group("tracestore")
def tracestore_group() -> None:
    """Trace-store administration."""


@tracestore_group.command("init")
@click.argument("uri", type=str)
def tracestore_init_cmd(uri: str) -> None:
    """Open the trace store, creating any missing schema."""

    async def _go() -> None:
        store = open_trace_store(uri)
        await store.open()
        await store.close()

    anyio.run(_go)
    click.echo(f"trace store ready at {uri}")


# ---------------------------------------------------------------------------
# `ef migrate`
# ---------------------------------------------------------------------------


@main.command("migrate")
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
@click.option("--to", "to_version", type=str, required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
def migrate_cmd(spec_path: Path, to_version: str, output_path: Path) -> None:
    """Migrate a spec file to a target schema major version.

    The framework currently knows about one major version, so this is mostly
    a forward-looking command. It still validates the input spec, which is
    useful before committing.
    """

    spec = load_spec(spec_path)
    if to_version != spec.schema_version:
        raise click.ClickException(
            f"only schema_version={spec.schema_version!r} is currently "
            f"supported; cannot migrate to {to_version!r}"
        )
    output_path.write_text(dump_spec(spec, format="yaml"), encoding="utf-8")
    click.echo(f"wrote {output_path}")
