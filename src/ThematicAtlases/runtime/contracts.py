"""Read-only admission of workflow traces before any writable SQLite open."""
import json
from pathlib import Path

WORKFLOW_CHECKPOINT_CONTRACT = "2.0"


def validate_trace(directory, *, required=True):
    manifest_path = Path(directory) / "00_run_manifest.json"
    if not manifest_path.exists() and not required:
        return {}
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or manifest.get("workflow_checkpoint_contract") != WORKFLOW_CHECKPOINT_CONTRACT:
        raise ValueError("trace requires checkpoint migration to workflow contract 2.0; existing files were not changed")
    return manifest
