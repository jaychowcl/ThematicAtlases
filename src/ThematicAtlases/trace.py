from __future__ import annotations

import json
from pathlib import Path


class DevTraceWriter:
    def __init__(self, root: str, run_id: str, manifest: dict):
        self.directory = Path(root) / run_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.write("00_run_manifest.json", {**manifest, "run_id": run_id})

    def write(self, name: str, value) -> None:
        with open(self.directory / name, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)

    def metadata(self, accessions: list[dict]) -> list[dict]:
        keys = ("datalink_id", "metadata_repository", "metadata_source", "metadata_status", "ontology_harmonization_status", "ontology_harmonization_error")
        return [
            {**{key: item[key] for key in keys if key in item}, "accession_metadata": item.get("accession_metadata")}
            for item in accessions
        ]
