#!/usr/bin/env python3
"""Run the fixed, full human fibrosis atlas workflow."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys

from agentic_curator.curators.ontology_harmonizer import OntoStore

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.credentials import GoogleCredentialPreflight


ROOT = Path(__file__).resolve().parent
THEME_FILE = ROOT / "docs" / "theme_fibrosis.txt"
OUTPUT_DIR = ROOT / ".out"

MAX_PUBLICATIONS = 50
MAX_GENERATED_QUERIES = 3
METADATA_REPOSITORIES = ["geo"]
REVIEW_FILTER = "not_relevant"
COLLECT_METADATA = True
GENERATE_QUERIES = True
DEV_TRACE = True
LOG_LEVEL = "DEBUG"
MAX_WORKERS = 1
REMOVED_ONTOLOGY_FRAMEWORKS = ["snomed"]
HARMONIZATION_OPTIONS = {
    "strategy": "websearch",
    "lookup_llm_judge": True,
    "lookup_llm_threshold": 2,
    "search_llm_judge": True,
    "llm": True,
}


def require_project_venv(
    root: Path = ROOT,
    executable: str | Path = sys.executable,
) -> None:
    expected = root / ".env" / "bin" / "python"
    if os.path.abspath(executable) != os.path.abspath(expected):
        raise RuntimeError(
            "Run this workflow with the repository virtual environment: "
            ".env/bin/python run_fibrosis_atlas.py"
        )


def configure_logging(path: Path) -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(path, encoding="utf-8"),
        ],
        force=True,
    )


def resolved_configuration() -> dict:
    output_dir = OUTPUT_DIR
    return {
        "theme_file": str(THEME_FILE),
        "atlas_out": str(output_dir / "fibrosis_atlas.json"),
        "summary_out": str(output_dir / "fibrosis_atlas.summary.json"),
        "harmonization_details_out": str(
            output_dir / "fibrosis_harmonization_details.json"
        ),
        "log_out": str(output_dir / "fibrosis_atlas.log"),
        "log_level": LOG_LEVEL,
        "dev_trace": DEV_TRACE,
        "dev_out_dir": str(output_dir / "dev_trace"),
        "ontology_storage_dir": str(output_dir / "ontology_store"),
        "removed_ontology_frameworks": REMOVED_ONTOLOGY_FRAMEWORKS,
        "query": None,
        "query_file": None,
        "generate_queries": GENERATE_QUERIES,
        "max_generated_queries": MAX_GENERATED_QUERIES,
        "metadata_repositories": METADATA_REPOSITORIES,
        "max_publications": MAX_PUBLICATIONS,
        "collect_metadata": COLLECT_METADATA,
        "review_filter": REVIEW_FILTER,
        "max_workers": MAX_WORKERS,
        "harmonization_options": HARMONIZATION_OPTIONS,
    }


def main() -> int:
    require_project_venv(root=ROOT, executable=sys.executable)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = resolved_configuration()
    configure_logging(Path(config["log_out"]))
    print(json.dumps(config, indent=2))

    theme = THEME_FILE.read_text(encoding="utf-8")
    store = OntoStore(storage_dir=config["ontology_storage_dir"])
    for framework in REMOVED_ONTOLOGY_FRAMEWORKS:
        store.configure_framework(framework, remove=True)

    credential_checker = GoogleCredentialPreflight()
    atlas = Atlas(
        metadata={},
        ontostore=store,
        cache_ontologies=True,
        credential_checker=credential_checker,
    )
    atlas.create_atlas(
        query=None,
        file=None,
        out=config["atlas_out"],
        theme=theme,
        review_filter=REVIEW_FILTER,
        metadata_repositories=METADATA_REPOSITORIES,
        max_publications=MAX_PUBLICATIONS,
        collect_metadata=COLLECT_METADATA,
        dev_trace=DEV_TRACE,
        dev_out_dir=config["dev_out_dir"],
        harmonization_details_out=config["harmonization_details_out"],
        generate_queries=GENERATE_QUERIES,
        max_generated_queries=MAX_GENERATED_QUERIES,
        harmonization_options=HARMONIZATION_OPTIONS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
