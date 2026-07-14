#!/usr/bin/env python3
"""Run human fibrosis dataset discovery and thematic review without harmonization."""

from __future__ import annotations

import argparse
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

MAX_PUBLICATIONS = 5000
MAX_GENERATED_QUERIES = 3
METADATA_REPOSITORIES = ["geo"]
REVIEW_FILTER = "not_relevant"
REVIEW_STRATEGY = "direct"
COLLECT_METADATA = True
DEV_TRACE = True
REVIEW_BEFORE_METADATA = True
STOP_BEFORE_REVIEW = True
LOG_LEVEL = "DEBUG"

FIBROSIS_DISCOVERY_QUERY = """\
(
  TITLE_ABS:(
    human OR humans OR patient OR patients OR donor OR donors OR "Homo sapiens"
  )
  AND TITLE_ABS:(
    "gene expression" OR "RNA sequencing" OR "RNA-seq" OR transcriptome
    OR transcriptomic OR "bulk RNA-seq" OR "bulk transcriptomics"
    OR "single cell RNA-seq" OR scRNA-seq OR "single nucleus RNA-seq"
    OR snRNA-seq OR "single cell transcriptomics"
    OR "single nucleus transcriptomics" OR "spatial transcriptomics"
    OR "spatial RNA-seq" OR "spatial gene expression" OR Visium OR GeoMx
    OR CosMx OR Xenium OR MERFISH OR seqFISH OR "Slide-seq" OR "Stereo-seq"
    OR microarray OR "gene chip" OR NanoString
  )
  AND TITLE_ABS:(
    fibrosis OR fibrotic OR fibrosed OR fibrogenesis OR fibrogenic
    OR cirrhosis OR cirrhotic OR "systemic sclerosis" OR scleroderma
    OR keloid OR keloids OR "hypertrophic scar" OR "hypertrophic scars"
    OR "tissue scarring" OR "organ scarring"
  )
)
AND (HAS_DATA:y OR HAS_LABSLINKS:y)
NOT PUB_TYPE:review
""".strip()


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run fibrosis discovery and thematic review without harmonization."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--generate-query",
        action="store_true",
        help=(
            "Generate Europe PMC queries from the fibrosis theme with the LLM "
            "instead of using the embedded static query."
        ),
    )
    modes.add_argument(
        "--resume",
        nargs="?",
        const="",
        metavar="RUN_ID",
        help="resume RUN_ID, or the latest incomplete discovery trace when omitted",
    )
    return parser


def resolved_configuration(*, generate_query: bool = False) -> dict:
    return {
        "theme_file": str(THEME_FILE),
        "discovery_out": str(OUTPUT_DIR / "fibrosis_discovery.json"),
        "summary_out": str(OUTPUT_DIR / "fibrosis_discovery.summary.json"),
        "log_out": str(OUTPUT_DIR / "fibrosis_discovery.log"),
        "log_level": LOG_LEVEL,
        "query_mode": "generated" if generate_query else "static",
        "query": None if generate_query else [FIBROSIS_DISCOVERY_QUERY],
        "query_file": None,
        "generate_queries": generate_query,
        "max_generated_queries": MAX_GENERATED_QUERIES,
        "metadata_repositories": METADATA_REPOSITORIES,
        "max_publications": MAX_PUBLICATIONS,
        "collect_metadata": COLLECT_METADATA,
        "review_filter": REVIEW_FILTER,
        "review_strategy": REVIEW_STRATEGY,
        "harmonization": False,
        "dev_trace": DEV_TRACE,
        "dev_out_dir": str(OUTPUT_DIR / "dev_trace_discovery"),
        "review_before_metadata": REVIEW_BEFORE_METADATA,
        "stop_before_review": STOP_BEFORE_REVIEW,
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    require_project_venv(root=ROOT, executable=sys.executable)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = resolved_configuration(generate_query=args.generate_query)
    configure_logging(Path(config["log_out"]))
    print(json.dumps(config, indent=2))

    theme = THEME_FILE.read_text(encoding="utf-8")
    atlas = Atlas(
        metadata={},
        credential_checker=GoogleCredentialPreflight(),
    )
    if args.resume is not None:
        atlas.resume(
            dev_out_dir=config["dev_out_dir"],
            run_id=args.resume or None,
            out=config["discovery_out"],
            stop_before_review=STOP_BEFORE_REVIEW,
        )
        return 0
    result = atlas.collect_datasets(
        query=config["query"],
        file=None,
        out=config["discovery_out"],
        theme=theme,
        review_filter=REVIEW_FILTER,
        review_strategy=REVIEW_STRATEGY,
        metadata_repositories=METADATA_REPOSITORIES,
        max_publications=MAX_PUBLICATIONS,
        collect_metadata=COLLECT_METADATA,
        generate_queries=config["generate_queries"],
        max_generated_queries=MAX_GENERATED_QUERIES,
        dev_trace=DEV_TRACE,
        dev_out_dir=config["dev_out_dir"],
        review_before_metadata=REVIEW_BEFORE_METADATA,
        stop_before_review=STOP_BEFORE_REVIEW,
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
