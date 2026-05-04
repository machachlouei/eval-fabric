"""Dataset loader: tolerates extra fields, fills missing item_id."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_fabric.dataset import load_jsonl


def test_load_jsonl_basic(tmp_path: Path) -> None:
    p = tmp_path / "data.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps({"item_id": "a", "input": "x", "reference_output": "x"}),
                json.dumps({"item_id": "b", "input": "y", "reference_output": "y"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    items = load_jsonl(p)
    assert [i.item_id for i in items] == ["a", "b"]
    assert items[0].reference_output == "x"


def test_load_jsonl_assigns_item_id_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "data.jsonl"
    p.write_text(json.dumps({"input": "x"}) + "\n", encoding="utf-8")
    items = load_jsonl(p)
    assert items[0].item_id.startswith("data:")


def test_load_jsonl_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "broken.jsonl"
    p.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_jsonl(p)
