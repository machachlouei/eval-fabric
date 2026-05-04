"""YAML / JSON loader for EvalSpec.

Loading routes through three steps, every time:

1. Parse YAML/JSON with `yaml.safe_load` (no code execution).
2. Walk the migration chain to the current major.
3. Validate via Pydantic.

Step 1 also resolves `${VAR}` references against the process environment, so
spec files can reference (non-secret) configuration without templating engines.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from eval_fabric.errors import SpecValidationError
from eval_fabric.spec.migrations import current_major, migrate_to_current
from eval_fabric.spec.models import EvalSpec, validate_spec

_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """Replace ${VAR} occurrences in any string within the parsed YAML.

    Unset variables are kept as-is (not replaced with the empty string) so a
    typo is visible rather than silently coerced.
    """

    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            var = match.group(1)
            return os.environ.get(var, match.group(0))

        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_spec_dict(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Read a spec into a dict, expanding env vars and applying migrations.

    Accepts a path, a raw YAML/JSON string, or an already-parsed dict.
    """

    if isinstance(source, dict):
        data: Any = source
    else:
        path = Path(source) if isinstance(source, (str, Path)) else None
        if path is not None and path.exists():
            text = path.read_text(encoding="utf-8")
        elif isinstance(source, str):
            # Treat as inline YAML/JSON content.
            text = source
        else:
            raise SpecValidationError(f"spec path not found: {source!r}")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecValidationError(f"failed to parse spec as YAML/JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SpecValidationError("spec must be a mapping (object)")

    data = _expand_env(data)
    schema_version = str(data.get("schema_version", "1"))
    if schema_version > current_major():
        raise SpecValidationError(
            f"schema_version={schema_version} is not supported by this framework "
            f"(current major: {current_major()})"
        )
    return migrate_to_current(data)


def load_spec(source: str | Path | dict[str, Any]) -> EvalSpec:
    """Load a YAML/JSON file (or dict) into a validated :class:`EvalSpec`."""

    return validate_spec(load_spec_dict(source))


def dump_spec(spec: EvalSpec, *, format: str = "yaml") -> str:
    """Serialize an EvalSpec back to YAML or JSON.

    YAML uses block style by default and is the canonical on-disk form.
    """

    data = spec.model_dump(mode="json", by_alias=True)
    fmt = format.lower()
    if fmt == "json":
        return json.dumps(data, indent=2, sort_keys=False)
    if fmt == "yaml":
        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    raise ValueError(f"unsupported format: {format!r}")
