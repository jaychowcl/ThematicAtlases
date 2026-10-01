"""Compatibility entrypoint for the deferred trace migration operation."""

from pathlib import Path


def migrate_pre_graph_discovery_trace(
    *,
    dev_out_dir: str,
    run_id: str,
    new_run_id: str,
) -> Path:
    """The old graph-only migration cannot upgrade workflow checkpoint contracts."""
    raise ValueError("Workflow checkpoint migration to contract 2.0 is deferred. Start a new run; existing traces are unchanged.")



__all__ = ["migrate_pre_graph_discovery_trace"]
