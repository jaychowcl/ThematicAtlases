#!/usr/bin/env python3
"""Score thematic-review output against packaged and custom reference sets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_ThematicAtlases import ThematicReviewerBenchmark


ROOT = Path(__file__).resolve().parent
DEFAULT_REPORT = Path(".out") / "reference_publication_recall.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "thematic_output",
        help="atlas JSON file or development-trace directory to benchmark",
    )
    parser.add_argument(
        "--reference-set-file",
        action="append",
        default=[],
        metavar="JSON",
        help="add one custom reference-set JSON file; may be repeated",
    )
    parser.add_argument(
        "--out",
        help="aggregate report path (default: .out/reference_publication_recall.json)",
    )
    return parser.parse_args(argv)


def resolved_configuration(
    *,
    thematic_output: Path,
    out: Path,
    packaged_reference_sets: tuple[str, ...],
    reference_set_files: list[Path],
) -> dict:
    return {
        "thematic_output": str(thematic_output),
        "report_out": str(out),
        "packaged_reference_sets": list(packaged_reference_sets),
        "reference_set_files": [str(path) for path in reference_set_files],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    thematic_output = Path(args.thematic_output)
    report_out = Path(args.out) if args.out else ROOT / DEFAULT_REPORT
    reference_set_files = [Path(value) for value in args.reference_set_file]
    benchmark = ThematicReviewerBenchmark()
    packaged_reference_sets = benchmark.available_reference_sets()
    config = resolved_configuration(
        thematic_output=thematic_output,
        out=report_out,
        packaged_reference_sets=packaged_reference_sets,
        reference_set_files=reference_set_files,
    )
    print(json.dumps(config, indent=2))

    reports = {}
    for reference_set in packaged_reference_sets:
        report = benchmark.benchmark_reference_publication_recall(
            reference_set=reference_set,
            thematic_output=thematic_output,
        )
        reports[reference_set] = report
    for reference_set_file in reference_set_files:
        report = benchmark.benchmark_reference_publication_recall(
            reference_set_file=reference_set_file,
            thematic_output=thematic_output,
        )
        reference_id = report["benchmark"]["reference_set"]["id"]
        if reference_id in reports:
            raise ValueError(f"duplicate reference set id {reference_id!r}")
        reports[reference_id] = report

    aggregate = {
        "schema_version": "1.0",
        "thematic_output": str(thematic_output),
        "reports": reports,
    }
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {reference_id: report["summary"] for reference_id, report in reports.items()},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
