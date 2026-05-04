"""CLI smoke tests via Click's testing harness."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from eval_fabric.cli import main


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "ef" in result.output


def test_init_creates_spec_and_data(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "hello"
    result = runner.invoke(main, ["init", str(target), "--example", "hello-world"])
    assert result.exit_code == 0, result.output
    assert (target / "spec.yaml").exists()
    assert (target / "data.jsonl").exists()


def test_init_then_run(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "hello"
    res = runner.invoke(main, ["init", str(target), "--example", "hello-world"])
    assert res.exit_code == 0, res.output

    out_dir = tmp_path / "runs"
    res = runner.invoke(
        main,
        [
            "run",
            str(target / "spec.yaml"),
            "--dataset",
            str(target / "data.jsonl"),
            "--output",
            str(out_dir),
        ],
    )
    assert res.exit_code == 0, res.output
    artifacts = list(out_dir.glob("run_*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["dataset_size"] == 3


def test_gate_passes_above_threshold(tmp_path: Path) -> None:
    artifact = tmp_path / "run_x.json"
    artifact.write_text(
        json.dumps(
            {
                "id": "run_x",
                "metrics": [{"name": "accuracy", "value": 0.95, "n": 100}],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    res = runner.invoke(main, ["gate", str(artifact), "--metric", "accuracy", "--min", "0.9"])
    assert res.exit_code == 0, res.output


def test_gate_fails_below_threshold(tmp_path: Path) -> None:
    artifact = tmp_path / "run_y.json"
    artifact.write_text(
        json.dumps(
            {
                "id": "run_y",
                "metrics": [{"name": "accuracy", "value": 0.5}],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    res = runner.invoke(main, ["gate", str(artifact), "--metric", "accuracy", "--min", "0.9"])
    assert res.exit_code != 0
