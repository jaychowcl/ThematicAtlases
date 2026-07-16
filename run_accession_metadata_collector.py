#!/usr/bin/env python3
"""Collect metadata for the current datalink snapshot in an active trace."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from ThematicAtlases.collector import AtlasCollector


ROOT = Path(__file__).resolve().parent


def require_project_venv(
    root: Path = ROOT,
    executable: str | Path = sys.executable,
) -> None:
    expected = root / ".env" / "bin" / "python"
    if os.path.abspath(executable) != os.path.abspath(expected):
        raise RuntimeError(
            "Run this workflow with the repository virtual environment: "
            ".env/bin/python run_accession_metadata_collector.py TRACE_DIR"
        )


def configure_logging(verbosity: int, path: Path) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(path, mode="a", encoding="utf-8"),
        ],
        force=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "trace_dir",
        type=Path,
        help="run directory containing 00_run_manifest.json and resume_state.sqlite",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--audit-enrichment-only",
        action="store_true",
        help="audit cached legacy enrichment without network calls",
    )
    actions.add_argument(
        "--retry-tags",
        type=Path,
        help="explicit PubMed/SRA/ENA identifiers to retry",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_project_venv(root=ROOT, executable=sys.executable)
    log_path = args.trace_dir / "resume_metadata.log"
    configure_logging(args.verbose, log_path)
    logging.getLogger(__name__).info(
        "Metadata worker start trace_dir=%s progress_artifact=%s log_path=%s",
        args.trace_dir,
        args.trace_dir / "resume_metadata_progress.json",
        log_path,
    )
    resume_options = {}
    if args.audit_enrichment_only:
        resume_options["audit_enrichment_only"] = True
    if args.retry_tags is not None:
        resume_options["retry_tags"] = args.retry_tags
    result = AtlasCollector().resume_metadata(args.trace_dir, **resume_options)
    if args.audit_enrichment_only:
        print(
            json.dumps(
                {
                    "trace_dir": str(args.trace_dir),
                    "candidates": result.get("counts", {}),
                    "candidate_artifact": str(
                        args.trace_dir / "resume_enrichment_candidates.json"
                    ),
                    "retry_tag_template": str(
                        args.trace_dir / "resume_enrichment_retry_tags.json"
                    ),
                    "log_path": str(log_path),
                },
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            {
                "trace_dir": str(args.trace_dir),
                "accessions": len(result.get("accessions", [])),
                "progress_artifact": str(
                    args.trace_dir / "resume_metadata_progress.json"
                ),
                "log_path": str(log_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
