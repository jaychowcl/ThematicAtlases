from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
from uuid import uuid4

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.run_store import AtlasRunStore, IncompatibleRunStoreError
from ThematicAtlases.runtime.contracts import WORKFLOW_CHECKPOINT_CONTRACT, validate_trace


_PATH_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


DEBUG_SNAPSHOTS = {"01_collected_accessions.json", "02_reviewed_datasets.json",
                       "03_pre_harmonization_accession_metadata.json", "04_harmonization_details.json",
                       "05_post_harmonization_accession_metadata.json", "resume_harmonized_datasets.json",
                       "resume_metadata_enriched_datasets.json", "resume_publication_collection.json",
                       "resume_review_progress.json"}


def _safe_path_component(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a filesystem-safe non-empty identifier")
    normalized = value
    if not _PATH_COMPONENT_PATTERN.fullmatch(normalized) or normalized in {".", ".."}:
        raise ValueError(f"{name} must be a filesystem-safe non-empty identifier")
    return normalized


class DevTraceWriter:
    def __init__(self, root: str, run_id: str, manifest: dict, write_manifest: bool = True):
        run_id = _safe_path_component(run_id, "run_id")
        self.directory = Path(root) / run_id
        if self.directory.exists() and (self.directory / "00_run_manifest.json").exists():
            validate_trace(self.directory)
        self.debug_snapshots = bool(manifest.get("debug_snapshots", False))
        if not write_manifest:
            self.debug_snapshots = bool(validate_trace(self.directory).get("debug_snapshots", False))
        self.directory.mkdir(parents=True, exist_ok=True)
        self._checkpoint_store = None
        self._run_store = None
        if write_manifest:
            full_manifest = {**manifest, "run_id": run_id, "workflow_checkpoint_contract": WORKFLOW_CHECKPOINT_CONTRACT}
            self.write("00_run_manifest.json", full_manifest)
            self._run_store = AtlasRunStore(
                self.directory / "atlas_run.sqlite3"
            )
            self._run_store.create_run(
                run_id=run_id,
                atlas_id=str(manifest.get("atlas_id") or f"atlas-{run_id}"),
                schema_version="1.0",
                config={
                    key: value
                    for key, value in full_manifest.items()
                    if key not in {"artifacts", "run_id"}
                },
            )
            self._run_store.record_event(
                run_id, "run_created", detail={"command": manifest.get("command")}
            )
            self._checkpoint_store = CheckpointStore(self.directory / "atlas_run.sqlite3")

    @property
    def manager(self):
        """Supported run operations bound to this trace's identity."""
        from ThematicAtlases.runtime.manager import AtlasRunManager
        return AtlasRunManager(self)

    @property
    def checkpoint_store(self) -> CheckpointStore:
        if self._checkpoint_store is None:
            _ = self.run_store
            self._checkpoint_store = CheckpointStore(
                self.directory / "atlas_run.sqlite3"
            )
        return self._checkpoint_store

    @property
    def run_store(self) -> AtlasRunStore:
        if self._run_store is None:
            path = self.directory / "atlas_run.sqlite3"
            if not path.exists():
                raise IncompatibleRunStoreError(
                    f"trace does not contain required atlas_run.sqlite3: {self.directory}"
                )
            self._run_store = AtlasRunStore(path)
            if self._run_store.get_run(self.directory.name) is None:
                raise IncompatibleRunStoreError(
                    "atlas_run.sqlite3 does not contain the selected run"
                )
        return self._run_store

    @classmethod
    def existing(cls, directory: str | Path) -> "DevTraceWriter":
        directory = Path(directory)
        return cls(
            root=str(directory.parent),
            run_id=directory.name,
            manifest={},
            write_manifest=False,
        )

    def write(self, name: str, value) -> None:
        name = _safe_path_component(name, "artifact name")
        if name in DEBUG_SNAPSHOTS and not self.debug_snapshots:
            return
        if "progress" in name and isinstance(value, dict) and not self.debug_snapshots and ("accessions" in value or "publication_texts" in value):
            value = {**{k: v for k, v in value.items() if k not in {"accessions", "publication_texts"}},
                     "accession_count": len(value.get("accessions", [])),
                     "publication_count": len(value.get("publication_texts", {}))}
        destination = self.directory / name
        temporary = destination.with_name(
            f".{destination.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def register_artifact(
        self,
        role: str,
        name: str,
        media_type: str = "application/json",
    ) -> int:
        name = _safe_path_component(name, "artifact name")
        path = self.directory / name
        if not path.exists() and not self.debug_snapshots and name in DEBUG_SNAPSHOTS:
            return 0
        content = path.read_bytes()
        return self.run_store.register_artifact(
            self.directory.name,
            role,
            name,
            media_type,
            hashlib.sha256(content).hexdigest(),
            len(content),
        )

    def metadata(self, accessions: list[dict]) -> list[dict]:
        keys = (
            "datalink_id",
            "metadata_repository",
            "metadata_source",
            "metadata_status",
            "ontology_harmonization_run_status",
            "ontology_harmonization_status",
            "ontology_harmonization_error",
        )
        return [
            {**{key: item[key] for key in keys if key in item}, "accession_metadata": item.get("accession_metadata")}
            for item in accessions
        ]
