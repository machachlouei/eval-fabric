"""``ef`` command-line entry point.

The CLI is a thin shell over the SDK. It exists for two reasons:

1. CI integration. ``ef run`` and ``ef gate`` are called from CI YAML.
2. Quick-start ergonomics. ``ef init`` scaffolds a runnable example.

There is intentionally no plugin system for CLI commands. Forks add commands.
"""

from eval_fabric.cli.app import main

__all__ = ["main"]
