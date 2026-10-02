"""Run resumption, publication, and checkpoint-contract lifecycle policy."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import secrets
from typing import Any

from ThematicAtlases.runtime.contracts import validate_trace
from ThematicAtlases.runtime.views import CheckpointViews
from ThematicAtlases.runtime.metadata_recovery import retryable_provider_issues
from ThematicAtlases.application import AtlasDocumentService
from ThematicAtlases.domain import AtlasDocument, RunStatus
from ThematicAtlases.filterer.review import REVIEW_CONTRACT_VERSION
from ThematicAtlases.run_archive import archive_existing_runs as archive_runs
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.unsupported_accessions import (
    build_unsupported_accessions_report,
)
from ThematicAtlases.wrappers.epmc import PUBLICATION_TEXT_CONTRACT_VERSION


def resolve_resume_run_directory(
    dev_out_dir: str | Path,
    run_id: str | None,
) -> Path:
    """Resolve an explicit trace or the latest incomplete valid trace."""

    root = Path(dev_out_dir)
    if run_id is not None:
        candidate = Path(run_id)
        run_dir = candidate if candidate.is_dir() else root / run_id
        validate_trace(run_dir)
        return run_dir

    candidates = []
    for run_dir in root.iterdir() if root.is_dir() else []:
        manifest_path = run_dir / "00_run_manifest.json"
        if not run_dir.is_dir() or not manifest_path.exists():
            continue
        try:
            views = CheckpointViews.from_directory(run_dir)
        except (OSError, ValueError):
            continue
        position = views.store.get_meta("pipeline_position", {})
        if position.get("published") and not any(item['status'] in {'pending', 'retryable_error', 'terminal_error'} or (stage == 'metadata_conversion' and retryable_provider_issues(item)) for stage in ('metadata_conversion','thematic_review','harmonization','publication_text','search_queries','datalinks','pubmed_gds_links','gds_summaries') for item in views.store.items(stage)):
            continue
        candidates.append(run_dir)
    if not candidates:
        raise FileNotFoundError(f"No incomplete valid trace found under {root}")
    return max(candidates, key=lambda path: path.name)


class AtlasRunLifecycle:
    """Own run identity, resumption selection, and output publication policy."""

    def __init__(
        self,
        *,
        metadata: dict[str, Any],
        documents: AtlasDocumentService,
    ) -> None:
        self._metadata = metadata
        self._documents = documents

    @staticmethod
    def final_run_status(result: dict, checkpoint_store=None) -> RunStatus:
        failed = any(
            record.get("ontology_harmonization_run_status") == "error"
            or (
                isinstance(record.get("ontology_harmonization_status"), dict)
                and record["ontology_harmonization_status"].get("execution")
                in {"degraded", "failed"}
            )
            or str(record.get("metadata_status") or "").lower()
            in {"error", "failed", "partial"}
            for record in result.get("accessions", [])
            if isinstance(record, dict)
        )
        incomplete = bool(
            checkpoint_store is not None and checkpoint_store.has_incomplete()
        )
        return RunStatus.PARTIAL if failed or incomplete else RunStatus.COMPLETE

    @staticmethod
    def checkpoint_keyword(
        callable_object,
        checkpoint_store,
        name: str = "checkpoint_store",
    ) -> dict[str, Any]:
        if checkpoint_store is None:
            return {}
        parameters = inspect.signature(callable_object).parameters
        if name in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return {name: checkpoint_store}
        return {}

    def write_resumed_outputs(
        self,
        result: dict,
        out: str | None,
        trace: DevTraceWriter,
        artifact_role: str = "final_atlas",
    ) -> dict:
        manifest = self.read_checkpoint(trace.directory / "00_run_manifest.json")
        if result.get("schema_version") == "1.0":
            document = AtlasDocument.from_mapping(result)
        else:
            from ThematicAtlases.runtime.views import CheckpointViews
            _, details = CheckpointViews(trace.checkpoint_store, manifest).harmonization()
            run_status = (
                RunStatus.RUNNING
                if artifact_role == "collection_snapshot"
                else self.final_run_status(result, trace.checkpoint_store)
            )
            document = self._documents.assemble(
                result,
                atlas_metadata=self._metadata,
                run_id=trace.directory.name,
                created_at=str(manifest.get("created_at") or trace.directory.name),
                theme=str(manifest.get("theme") or ""),
                config={
                    "queries": list(
                        CheckpointViews(trace.checkpoint_store, manifest).resolved_queries()
                        or manifest.get("query")
                        or ()
                    ),
                    "metadata_repositories": list(
                        manifest.get("metadata_repositories") or ()
                    ),
                    **{key: manifest.get(key) for key in (
                        "query_file", "review_filter", "review_strategy", "prune_accessions",
                        "collect_metadata", "generate_queries", "review_before_metadata",
                        "scrape_fulltext_accessions", "thematic_review", "harmonization_options",
                        "resource_profile", "runtime_provenance")},
                    "harmonization_options": dict(manifest.get("harmonization_options") or {}),
                },
                run_status=run_status,
                harmonization_details=details,
            )
        unsupported_report = build_unsupported_accessions_report(
            list(result.get("unsupported_accessions", [])), atlas_id=document.atlas.atlas_id,
            run_id=document.run.run_id)
        unsupported_output_path = manifest.get("unsupported_accessions_out")
        published = document.to_mapping()
        if out is not None:
            summary = self._documents.publish(
                document,
                out,
                include_summary=True,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_output_path,
            )
        else:
            summary = self._documents.summary(
                document,
                None,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_output_path,
            )
            if unsupported_output_path is not None:
                self._documents.publish_unsupported_accessions(
                    unsupported_report,
                    unsupported_output_path,
                )
        atlas_name = (
            "collection_snapshot.json"
            if artifact_role == "collection_snapshot"
            else "06_final_atlas.json"
        )
        summary_name = (
            "collection_snapshot.summary.json"
            if artifact_role == "collection_snapshot"
            else "07_summary.json"
        )
        trace.write(atlas_name, published)
        trace.write(summary_name, summary)
        trace.write("08_retry_report.json", trace.checkpoint_store.retry_report())
        trace.write("unsupported_accessions.json", unsupported_report)
        trace.register_artifact(artifact_role, atlas_name)
        trace.register_artifact(
            "collection_summary" if artifact_role == "collection_snapshot" else "summary",
            summary_name,
        )
        trace.register_artifact("retry_report", "08_retry_report.json")
        trace.register_artifact("unsupported_accessions", "unsupported_accessions.json")
        if artifact_role == "collection_snapshot":
            trace.run_store.set_stage_state(
                trace.directory.name, "collection", "complete"
            )
            trace.run_store.set_run_status(trace.directory.name, "running")
        else:
            trace.run_store.set_stage_state(
                trace.directory.name,
                "harmonization",
                "partial" if trace.checkpoint_store.has_incomplete() else "complete",
            )
            trace.run_store.set_run_status(
                trace.directory.name, document.run.status.value
            )
        trace.run_store.record_event(
            trace.directory.name,
            "artifact_published",
            detail={"artifact_role": artifact_role},
        )
        if artifact_role != "collection_snapshot":
            trace.checkpoint_store.set_meta("pipeline_position", {"stage":"harmonization", "state":"complete", "published":True})
        return published

    def resume_run_directory(self, dev_out_dir: str, run_id: str | None) -> Path:
        return resolve_resume_run_directory(dev_out_dir, run_id)

    @staticmethod
    def reconcile_checkpoint_contracts(checkpoint_store) -> None:
        """Requeue cached work whose decision/fetch contract has changed."""

        for item in checkpoint_store.items("thematic_review"):
            payload = item.get("payload") or {}
            if payload.get("review_contract_version") == REVIEW_CONTRACT_VERSION:
                continue
            checkpoint_store.put(
                "thematic_review",
                item["key"],
                item["ordinal"],
                "retryable_error",
                payload=payload,
                error=f"stale review contract; expected {REVIEW_CONTRACT_VERSION}",
                error_type="StaleCheckpointContract",
                failure_category="contract_upgrade",
            )
        for item in checkpoint_store.items("publication_text"):
            payload = item.get("payload") or {}
            publication = payload.get("publication") or {}
            if (
                payload.get("contract_version") == PUBLICATION_TEXT_CONTRACT_VERSION
                or publication.get("full_text_status") != "unavailable"
            ):
                continue
            checkpoint_store.put(
                "publication_text",
                item["key"],
                item["ordinal"],
                "retryable_error",
                payload=payload,
                error="stale publication-text contract; retry known PMCID fetch",
                error_type="StaleCheckpointContract",
                failure_category="contract_upgrade",
            )

    @staticmethod
    def read_checkpoint(path: Path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def dev_run_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{timestamp}-{secrets.token_hex(4)}"

    @staticmethod
    def archive_existing_runs(
        *,
        dev_out_dir: str,
        archive_root: str,
        workflow: str,
        artifact_paths: list[str] | tuple[str, ...] = (),
    ) -> list[Path]:
        return archive_runs(
            dev_out_dir=dev_out_dir,
            archive_root=archive_root,
            workflow=workflow,
            artifact_paths=artifact_paths,
        )
