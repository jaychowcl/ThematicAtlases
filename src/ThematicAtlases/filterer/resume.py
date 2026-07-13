from __future__ import annotations

import json
from pathlib import Path

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.filterer.filterer import AtlasFilterer
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


class TracePublicationReviewResumer:
    """Review a stable snapshot of publications in an evolving trace."""

    def __init__(
        self,
        publication_text_reviewer,
        *,
        collector_factory=None,
        filterer_factory=None,
        epmc_wrapper_factory=None,
    ):
        self._publication_text_reviewer = publication_text_reviewer
        self._collector_factory = collector_factory or AtlasCollector
        self._filterer_factory = filterer_factory or AtlasFilterer
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper

    def resume(
        self,
        trace_dir: str | Path,
        *,
        theme: str | None = None,
        strategy: str = "direct",
        reviewer=None,
        allow_theme_override: bool = False,
    ) -> dict:
        directory = Path(trace_dir)
        manifest = self._read_manifest(directory)
        resolved_theme = self._resolved_theme(
            theme=theme,
            manifest=manifest,
            allow_theme_override=allow_theme_override,
        )
        store = CheckpointStore(directory / "resume_state.sqlite")

        datalink_rows = [
            row
            for item in store.items("datalinks")
            if item["status"] == "available"
            for row in (item.get("payload") or {}).get("rows", [])
        ]
        accessions = self._epmc_wrapper_factory().accessions_from_datalinks(
            datalinks=datalink_rows
        )
        accessions = self._collector_factory().filter_accessions(
            accessions=accessions,
            metadata_repositories=manifest.get("metadata_repositories"),
        )
        filterer = self._filterer_factory(
            publication_text_reviewer=self._publication_text_reviewer,
        )
        publication_texts = filterer.collect_publication_texts(
            jsons=accessions,
            checkpoint_store=store,
        )
        accessions_with_refs = filterer.accessions_with_publication_text_refs(
            jsons=accessions,
            publication_texts=publication_texts,
        )
        trace = DevTraceWriter.existing(directory)

        def write_progress(reviewed_texts: dict) -> None:
            trace.write(
                "resume_review_progress.json",
                {
                    "accessions": filterer.accessions_with_publication_text_refs(
                        jsons=accessions,
                        publication_texts=reviewed_texts,
                    ),
                    "publication_texts": reviewed_texts,
                },
            )

        reviewed_texts = self._publication_text_reviewer.review_publication_texts(
            publication_texts=publication_texts,
            contexts=self._publication_text_reviewer.publication_review_contexts(
                accessions=accessions_with_refs
            ),
            theme=resolved_theme,
            strategy=strategy,
            reviewer=reviewer,
            progress_callback=write_progress,
            checkpoint_store=store,
        )
        result = {
            "accessions": filterer.accessions_with_publication_text_refs(
                jsons=accessions,
                publication_texts=reviewed_texts,
            ),
            "publication_texts": reviewed_texts,
        }
        trace.write("resume_review_progress.json", result)
        return result

    @staticmethod
    def _read_manifest(directory: Path) -> dict:
        path = directory / "00_run_manifest.json"
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise ValueError("trace manifest must contain a JSON object")
        return manifest

    @staticmethod
    def _resolved_theme(
        theme: str | None,
        manifest: dict,
        allow_theme_override: bool = False,
    ) -> str:
        manifest_theme = str(manifest.get("theme") or "")
        explicit_theme = None if theme is None else str(theme)
        if (
            explicit_theme is not None
            and explicit_theme.strip()
            and manifest_theme.strip()
            and explicit_theme.strip() != manifest_theme.strip()
            and not allow_theme_override
        ):
            raise ValueError("requested theme does not match the trace manifest theme")
        resolved = (
            explicit_theme
            if allow_theme_override and explicit_theme and explicit_theme.strip()
            else manifest_theme if manifest_theme.strip() else explicit_theme
        )
        if resolved is None or not resolved.strip():
            raise ValueError("incremental publication review requires a non-empty theme")
        return resolved
