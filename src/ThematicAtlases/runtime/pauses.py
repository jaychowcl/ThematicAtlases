"""AtlasPauseController: application orchestration behind the Atlas facade.

The injected context preserves existing subclass hooks; workflow instances are
operation-local and do not own shared clients or persistent state.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ThematicAtlases.atlas import Atlas

from ThematicAtlases.checkpoint import STAGE_POLICIES
from ThematicAtlases.pipeline import STOP_AFTER_STAGES
from ThematicAtlases.trace import DevTraceWriter


class AtlasPauseController:
    def __init__(self, context: Atlas):
        self.context = context

    def pause(
        self,
        *,
        trace: DevTraceWriter | None,
        stage: str,
        result: dict,
    ) -> dict:
        context = self.context
        if trace is None:
            raise ValueError("stage pauses require a development trace")
        normalized = {
            "accessions": list(result.get("accessions", [])),
            "publication_texts": dict(result.get("publication_texts", {})),
            **{
                key: value
                for key, value in result.items()
                if key not in {"accessions", "publication_texts", "publications"}
            },
        }
        stage_key = stage.replace("-", "_")
        checkpoint_status_counts = context._checkpoint_status_counts(
            trace.checkpoint_store,
        )
        frontier_counts = context._pause_frontier_counts(
            stage,
            checkpoint_status_counts,
        )
        run = trace.run_store.get_run(trace.directory.name) or {}
        fingerprint = trace.checkpoint_store.get_meta("run_fingerprint", {})
        invocation_sequence = trace.run_store.record_event(
            trace.directory.name,
            "pause_requested",
            stage=stage,
            detail={"stage": stage, "status": "pausing"},
        )
        summary = {
            "contract_version": "1.0",
            "run_id": trace.directory.name,
            "stage": stage,
            "accession_count": len(normalized["accessions"]),
            "publication_text_count": len(normalized["publication_texts"]),
            "frontier_counts": frontier_counts,
            "checkpoint_status_counts": checkpoint_status_counts,
            "invocation_identity": {
                "event_sequence": invocation_sequence,
                "requested_stop_after": stage,
            },
            "hashes": {
                "run_config_sha256": run.get("config_sha256"),
                "run_fingerprint_sha256": fingerprint.get("sha256"),
            },
        }
        trace.write(f"pause_{stage_key}_summary.json", summary)
        execution_state = {
            "stage": stage,
            "state": "paused",
            "contract_version": "1.0",
            "frontier_counts": frontier_counts,
            "invocation_identity": summary["invocation_identity"],
            "hashes": summary["hashes"],
        }
        trace.checkpoint_store.set_meta(
            "main_pipeline_stage",
            execution_state,
        )
        trace.checkpoint_store.set_meta("pipeline_execution_state", execution_state)
        published = context._write_resumed_outputs(
            result=normalized,
            out=None,
            trace=trace,
            artifact_role="collection_snapshot",
        )
        trace.run_store.set_stage_state(
            trace.directory.name,
            "harmonization" if stage == "harmonization" else "collection",
            "paused",
        )
        trace.run_store.set_run_status(trace.directory.name, "running")
        trace.run_store.record_event(
            trace.directory.name,
            "run_paused",
            stage=stage,
            detail=summary,
        )
        return published

    def completed(
        self,
        trace: DevTraceWriter,
        stop_after: str | None,
    ) -> dict | None:
        context = self.context
        if stop_after is None:
            return None
        current = trace.checkpoint_store.get_meta("main_pipeline_stage", {})
        current_stage = current.get("stage")
        if current_stage not in STOP_AFTER_STAGES:
            return None
        if STOP_AFTER_STAGES.index(current_stage) < STOP_AFTER_STAGES.index(stop_after):
            return None
        snapshot_path = next(
            (
                path
                for path in (
                    trace.directory / "collection_snapshot.json",
                    trace.directory / "06_final_atlas.json",
                )
                if path.is_file()
            ),
            None,
        )
        if snapshot_path is None:
            return None
        stage_key = stop_after.replace("-", "_")
        summary = {
            "contract_version": "1.0",
            "run_id": trace.directory.name,
            "stage": stop_after,
            "current_stage": current_stage,
            "already_complete": True,
            "snapshot_artifact": snapshot_path.name,
            "checkpoint_status_counts": trace.checkpoint_store.stage_status_counts(),
        }
        trace.write(f"pause_{stage_key}_summary.json", summary)
        trace.run_store.record_event(
            trace.directory.name,
            "run_pause_noop",
            stage=stop_after,
            detail=summary,
        )
        return context._read_checkpoint(snapshot_path)

    @staticmethod
    def frontier_counts(
        stage: str,
        status_counts: dict[str, dict[str, int]],
    ) -> dict[str, int]:
        explicit = {
            "query-results": ("search_queries", "search_pages"),
            "datalinks": ("datalinks",),
            "publication-text": ("publication_text",),
            "fulltext-accessions": ("fulltext_accession_discovery",),
            "accession-graph": ("pubmed_gds_links", "gds_summaries"),
            "review": ("thematic_review",),
        }
        if stage == "metadata":
            checkpoint_stages = tuple(
                key for key, boundary in STAGE_POLICIES.items()
                if boundary == "metadata"
            )
        elif stage == "harmonization":
            checkpoint_stages = tuple(
                key for key, boundary in STAGE_POLICIES.items()
                if boundary == "harmonization"
            )
        else:
            checkpoint_stages = explicit.get(stage, ())
        combined: dict[str, int] = {}
        for checkpoint_stage in checkpoint_stages:
            for status, count in status_counts.get(checkpoint_stage, {}).items():
                combined[status] = combined.get(status, 0) + count
        terminal = sum(
            combined.get(status, 0)
            for status in ("available", "no_data", "terminal_error")
        )
        retryable = combined.get("retryable_error", 0)
        pending = combined.get("pending", 0)
        return {
            "total": sum(combined.values()),
            "terminal": terminal,
            "retryable": retryable,
            "pending": pending,
            "partial": retryable + pending,
        }

