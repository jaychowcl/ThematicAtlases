from __future__ import annotations

import json
import os
from pathlib import Path


class DevTraceWriter:
    def __init__(self, root: str, run_id: str, manifest: dict, write_manifest: bool = True):
        self.directory = Path(root) / run_id
        self.directory.mkdir(parents=True, exist_ok=True)
        if write_manifest:
            self.write("00_run_manifest.json", {**manifest, "run_id": run_id})

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
        destination = self.directory / name
        temporary = destination.with_name(f".{destination.name}.tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)

    def metadata(self, accessions: list[dict]) -> list[dict]:
        keys = ("datalink_id", "metadata_repository", "metadata_source", "metadata_status", "ontology_harmonization_status", "ontology_harmonization_error")
        return [
            {**{key: item[key] for key in keys if key in item}, "accession_metadata": item.get("accession_metadata")}
            for item in accessions
        ]
