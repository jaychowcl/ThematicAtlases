#!/usr/bin/env python3
"""Score thematic-review output against the Leonie 2026 fibrosis references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_ThematicAtlases import ThematicReviewerBenchmark


ROOT = Path(__file__).resolve().parent
REFERENCE_SET = "leonie_2026_fibrosis"
DEFAULT_REPORT = Path(".out") / "leonie_2026_reference_publication_recall.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "thematic_output",
        help="atlas JSON file or development-trace directory to benchmark",
    )
    parser.add_argument(
        "--out",
        help=(
            "benchmark report path (default: "
            ".out/leonie_2026_reference_publication_recall.json)"
        ),
    )
    return parser.parse_args(argv)


def resolved_configuration(*, thematic_output: Path, out: Path) -> dict:
    return {
        "reference_set": REFERENCE_SET,
        "thematic_output": str(thematic_output),
        "report_out": str(out),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    thematic_output = Path(args.thematic_output)
    report_out = Path(args.out) if args.out else ROOT / DEFAULT_REPORT
    config = resolved_configuration(
        thematic_output=thematic_output,
        out=report_out,
    )
    print(json.dumps(config, indent=2))

    report = ThematicReviewerBenchmark().benchmark_reference_publication_recall(
        reference_set=REFERENCE_SET,
        thematic_output=thematic_output,
    )
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
