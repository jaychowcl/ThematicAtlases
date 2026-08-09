from __future__ import annotations

import argparse
import inspect
import json
import logging
import sys
from pathlib import Path

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher

REVIEW_FILTER_CHOICES = ("none", "not-relevant", "not-relevant-and-unsure")
REVIEW_STRATEGY_CHOICES = ("direct",)
METADATA_REPOSITORY_CHOICES = ("geo", "arrayexpress")


def _positive_int(value: str) -> int:
    integer = int(value)

    if integer < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")

    return integer


def _resource_override(value: str) -> tuple[str, int | float]:
    name, separator, raw_value = value.partition("=")
    if not separator or not name.strip() or not raw_value.strip():
        raise argparse.ArgumentTypeError("resource override must use FIELD=VALUE")
    try:
        parsed: int | float = (
            float(raw_value)
            if name.strip() == "disk_headroom_fraction"
            else int(raw_value)
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "resource override VALUE must be numeric"
        ) from error
    return name.strip(), parsed


def _add_resource_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--resource-profile",
        choices=("standard", "large"),
        default="standard",
    )
    parser.add_argument(
        "--resource-override",
        action="append",
        default=[],
        type=_resource_override,
        metavar="FIELD=VALUE",
    )


def _add_logging_options(
    parser: argparse.ArgumentParser,
    *,
    verbose_dest: str,
    log_file_dest: str,
) -> None:
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=None,
        dest=verbose_dest,
    )
    parser.add_argument(
        "--log-file",
        default=None,
        dest=log_file_dest,
        metavar="LOG_FILE",
    )


def _add_dev_trace_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dev-trace", action="store_true", default=False)
    parser.add_argument("--dev-out-dir", default=".dev")


def _add_fulltext_accession_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scrape-fulltext-accessions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "scan available Europe PMC full text for repository accessions "
            "(enabled by default)"
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thematic-atlas",
        description="Collect, review, harmonize, and resume thematic biomedical atlases.",
    )
    _add_logging_options(
        parser,
        verbose_dest="global_verbose",
        log_file_dest="global_log_file",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser(
        "collect-datasets",
        help="Collect and review datasets into an Atlas v1 snapshot.",
    )
    _add_logging_options(
        collect,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
    )
    _add_resource_options(collect)
    collect.add_argument("--query", action="append", default=None)
    collect.add_argument("--file", default=None)
    collect.add_argument("--out", default=None)
    collect.add_argument("--unsupported-accessions-out", default=None)
    collect.add_argument("--max-publications", type=_positive_int, default=None)
    collect.add_argument("--skip-metadata", action="store_true", default=False)
    collect.add_argument(
        "--review-before-metadata", action="store_true", default=False
    )
    _add_fulltext_accession_options(collect)
    collect.add_argument(
        "--metadata-repository",
        action="append",
        choices=METADATA_REPOSITORY_CHOICES,
        default=None,
    )
    collect.add_argument("--theme", default=None)
    collect.add_argument("--theme-file", default=None)
    collect.add_argument("--query-generator", action="store_true", default=False)
    collect.add_argument("--max-generated-queries", type=_positive_int, default=3)
    collect.add_argument(
        "--review-filter",
        choices=REVIEW_FILTER_CHOICES,
        default="none",
    )
    collect.add_argument(
        "--review-strategy",
        choices=REVIEW_STRATEGY_CHOICES,
        default="direct",
    )
    collect.add_argument(
        "--prune-accessions",
        action="store_true",
        default=False,
        help="explicitly apply grounded accession exclusions from thematic review",
    )

    create = subparsers.add_parser(
        "create-atlas",
        help="Create and harmonize a complete Atlas v1 document.",
    )
    _add_logging_options(
        create,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
    )
    _add_resource_options(create)
    create.add_argument("--query", action="append", default=None)
    create.add_argument("--file", default=None)
    create.add_argument("--out", default=None)
    create.add_argument("--unsupported-accessions-out", default=None)
    create.add_argument("--max-publications", type=_positive_int, default=None)
    create.add_argument("--skip-metadata", action="store_true", default=False)
    create.add_argument(
        "--review-before-metadata", action="store_true", default=False
    )
    _add_fulltext_accession_options(create)
    _add_dev_trace_options(create)
    create.add_argument(
        "--metadata-repository",
        action="append",
        choices=METADATA_REPOSITORY_CHOICES,
        default=None,
    )
    create.add_argument("--theme", default=None)
    create.add_argument("--theme-file", default=None)
    create.add_argument(
        "--query-generator",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="generate theme-derived queries (enabled by default)",
    )
    create.add_argument(
        "--thematic-review",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="review publication relevance to the theme (enabled by default)",
    )
    create.add_argument("--max-generated-queries", type=_positive_int, default=3)
    create.add_argument("--harmonization-details-out", default=None)
    create.add_argument("--stop-after", choices=("metadata",), default=None)
    create.add_argument(
        "--review-filter",
        choices=REVIEW_FILTER_CHOICES,
        default="none",
    )
    create.add_argument(
        "--review-strategy",
        choices=REVIEW_STRATEGY_CHOICES,
        default="direct",
    )
    create.add_argument(
        "--prune-accessions",
        action="store_true",
        default=False,
        help="explicitly apply grounded accession exclusions from thematic review",
    )

    harmonize = subparsers.add_parser(
        "harmonize-datasets",
        help="Harmonize metadata in an existing Atlas v1 document.",
    )
    _add_logging_options(
        harmonize,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
    )
    _add_resource_options(harmonize)
    harmonize.add_argument("--file", required=True)
    harmonize.add_argument("--out", required=True)
    harmonize.add_argument("--harmonization-details-out", default=None)

    resume = subparsers.add_parser(
        "resume",
        help=(
            "Resume a traced Atlas v1 workflow and optionally requeue "
            "selected failures."
        ),
    )
    _add_logging_options(
        resume,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
    )
    _add_resource_options(resume)
    resume.add_argument("--dev-out-dir", default=".dev")
    resume.add_argument("--run-id", default=None)
    resume.add_argument("--out", default=None)
    resume.add_argument("--stop-before-review", action="store_true", default=False)
    resume.add_argument("--retry-stage", action="append", default=[])
    resume.add_argument("--retry-item", action="append", default=[])
    resume.add_argument("--retry-degraded-stage", action="append", default=[])

    fork = subparsers.add_parser(
        "fork-run",
        help="Fork a paused metadata trace for independent downstream work.",
    )
    _add_resource_options(fork)
    _add_logging_options(
        fork,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
    )
    fork.add_argument("--dev-out-dir", default=".dev")
    fork.add_argument("--run-id", required=True)
    fork.add_argument("--new-run-id", required=True)
    fork.add_argument("--config", required=True)

    return parser


def _configure_logging(verbosity: int, log_file: str | None) -> None:
    level = logging.WARNING

    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging_kwargs = {
        "level": level,
        "format": "%(levelname)s:%(name)s:%(message)s",
        "force": True,
    }

    if log_file is not None:
        logging_kwargs["filename"] = log_file
        logging_kwargs["encoding"] = "utf-8"
    else:
        logging_kwargs["stream"] = sys.stdout

    logging.basicConfig(**logging_kwargs)


def _input_value(value: str | None, file: str | None) -> str | None:
    if file is not None:
        return Path(file).read_text(encoding="utf-8")

    return value


def _review_filter(value: str) -> str:
    return value.replace("-", "_")


def _resolved_logging_options(args: argparse.Namespace) -> tuple[int, str | None]:
    command_verbose = getattr(args, "command_verbose", None)
    global_verbose = getattr(args, "global_verbose", None)
    command_log_file = getattr(args, "command_log_file", None)
    global_log_file = getattr(args, "global_log_file", None)

    verbosity = command_verbose if command_verbose is not None else global_verbose
    log_file = command_log_file if command_log_file is not None else global_log_file

    return verbosity or 0, log_file


def _retry_items(values: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for value in values:
        stage, separator, key = value.partition(":")
        if not separator or not stage.strip() or not key.strip():
            raise ValueError("--retry-item must use STAGE:KEY")
        result.setdefault(stage.strip(), []).append(key.strip())
    return result


def main(argv: list[str] | None = None) -> int:

    parser = _build_parser()
    args = parser.parse_args(argv)
    verbosity, log_file = _resolved_logging_options(args)
    _configure_logging(verbosity=verbosity, log_file=log_file)

    atlas_kwargs = {
        "metadata": {},
        "resource_profile": args.resource_profile,
        "resource_overrides": dict(args.resource_override),
    }
    constructor_parameters = inspect.signature(Atlas).parameters.values()
    if not any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in constructor_parameters
    ):
        accepted = {parameter.name for parameter in constructor_parameters}
        atlas_kwargs = {
            key: value for key, value in atlas_kwargs.items() if key in accepted
        }
    atlas = Atlas(**atlas_kwargs)

    if args.command == "collect-datasets":
        theme = _input_value(value=args.theme, file=args.theme_file)
        atlas.collect_datasets(
            query=args.query,
            file=args.file,
            out=args.out,
            theme=theme,
            review_filter=_review_filter(args.review_filter),
            review_strategy=args.review_strategy,
            prune_accessions=args.prune_accessions,
            metadata_repositories=args.metadata_repository,
            max_publications=args.max_publications,
            collect_metadata=not args.skip_metadata,
            generate_queries=args.query_generator,
            max_generated_queries=args.max_generated_queries,
            review_before_metadata=args.review_before_metadata,
            scrape_fulltext_accessions=args.scrape_fulltext_accessions,
            unsupported_accessions_out=args.unsupported_accessions_out,
        )
    elif args.command == "create-atlas":
        theme = _input_value(value=args.theme, file=args.theme_file)
        if theme is None or not theme.strip():
            parser.error(
                "create-atlas requires a non-empty --theme or --theme-file"
            )
        atlas.create_atlas(
            query=args.query,
            file=args.file,
            out=args.out,
            theme=theme,
            review_filter=_review_filter(args.review_filter),
            review_strategy=args.review_strategy,
            prune_accessions=args.prune_accessions,
            metadata_repositories=args.metadata_repository,
            max_publications=args.max_publications,
            collect_metadata=not args.skip_metadata,
            dev_trace=args.dev_trace,
            dev_out_dir=args.dev_out_dir,
            harmonization_details_out=args.harmonization_details_out,
            generate_queries=args.query_generator,
            max_generated_queries=args.max_generated_queries,
            review_before_metadata=args.review_before_metadata,
            scrape_fulltext_accessions=args.scrape_fulltext_accessions,
            unsupported_accessions_out=args.unsupported_accessions_out,
            thematic_review=args.thematic_review,
            **({"stop_after": args.stop_after} if args.stop_after else {}),
        )
    elif args.command == "harmonize-datasets":
        with open(args.file, encoding="utf-8") as handle:
            datasets = json.load(handle)
        result = atlas.harmonize_datasets(
            datasets=datasets,
            harmonization_details_out=args.harmonization_details_out,
        )
        JsonArtifactBundlePublisher().publish({Path(args.out): result})
    elif args.command == "resume":
        atlas.resume(
            dev_out_dir=args.dev_out_dir,
            run_id=args.run_id,
            out=args.out,
            stop_before_review=args.stop_before_review,
            retry_stages=args.retry_stage,
            retry_items=_retry_items(args.retry_item),
            retry_degraded_stages=args.retry_degraded_stage,
        )
    elif args.command == "fork-run":
        with open(args.config, encoding="utf-8") as handle:
            overrides = json.load(handle)
        if not isinstance(overrides, dict):
            parser.error("fork-run --config must contain a JSON object")
        atlas.fork_run(
            dev_out_dir=args.dev_out_dir,
            run_id=args.run_id,
            new_run_id=args.new_run_id,
            overrides=overrides,
        )
    else:
        parser.error(f"unknown command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
