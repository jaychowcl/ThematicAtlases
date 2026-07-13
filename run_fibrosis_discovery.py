#!/usr/bin/env python3
"""Run human fibrosis dataset discovery and thematic review without harmonization."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.credentials import GoogleCredentialPreflight
from ThematicAtlases.summary import build_atlas_summary


ROOT = Path(__file__).resolve().parent
THEME_FILE = ROOT / "docs" / "theme_fibrosis.txt"
OUTPUT_DIR = ROOT / ".out"

MAX_PUBLICATIONS = 1000
MAX_GENERATED_QUERIES = 3
METADATA_REPOSITORIES = ["geo"]
REVIEW_FILTER = "not_relevant"
COLLECT_METADATA = True
GENERATE_QUERIES = True
LOG_LEVEL = "DEBUG"


def require_project_venv(
    root: Path = ROOT,
    executable: str | Path = sys.executable,
) -> None:
    expected = root / ".env" / "bin" / "python"
    if os.path.abspath(executable) != os.path.abspath(expected):
        raise RuntimeError(
            "Run this workflow with the repository virtual environment: "
            ".env/bin/python run_fibrosis_discovery.py"
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
    return {
        "theme_file": str(THEME_FILE),
        "discovery_out": str(OUTPUT_DIR / "fibrosis_discovery.json"),
        "summary_out": str(OUTPUT_DIR / "fibrosis_discovery.summary.json"),
        "log_out": str(OUTPUT_DIR / "fibrosis_discovery.log"),
        "log_level": LOG_LEVEL,
        "query": None,
        "query_file": None,
        "generate_queries": GENERATE_QUERIES,
        "max_generated_queries": MAX_GENERATED_QUERIES,
        "metadata_repositories": METADATA_REPOSITORIES,
        "max_publications": MAX_PUBLICATIONS,
        "collect_metadata": COLLECT_METADATA,
        "review_filter": REVIEW_FILTER,
        "harmonization": False,
    }


def main() -> int:
    require_project_venv(root=ROOT, executable=sys.executable)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = resolved_configuration()
    configure_logging(Path(config["log_out"]))
    print(json.dumps(config, indent=2))

    theme = THEME_FILE.read_text(encoding="utf-8")
    atlas = Atlas(
        metadata={},
        credential_checker=GoogleCredentialPreflight(),
    )
    result = atlas.collect_datasets(
        query=None,
        file=None,
        out=config["discovery_out"],
        theme=theme,
        review_filter=REVIEW_FILTER,
        metadata_repositories=METADATA_REPOSITORIES,
        max_publications=MAX_PUBLICATIONS,
        collect_metadata=COLLECT_METADATA,
        generate_queries=GENERATE_QUERIES,
        max_generated_queries=MAX_GENERATED_QUERIES,
    )
    summary = build_atlas_summary(
        atlas=result,
        atlas_path=config["discovery_out"],
    )
    Path(config["summary_out"]).write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
