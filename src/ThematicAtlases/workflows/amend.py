"""AmendQueriesWorkflow: application orchestration behind the Atlas facade.

The injected context preserves existing subclass hooks; workflow instances are
operation-local and do not own shared clients or persistent state.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ThematicAtlases.atlas import Atlas

import json
import hashlib
from pathlib import Path
from ThematicAtlases.trace import DevTraceWriter
import logging
logger = logging.getLogger("ThematicAtlases.atlas")


class AmendQueriesWorkflow:
    def __init__(self, context: Atlas):
        self.context = context

    def run(
        self,
        *,
        dev_out_dir: str,
        run_id: str,
        queries: list[str],
        max_publications_per_query: list[int | None],
    ) -> Path:
        context = self.context
        """Amend one trace's queries without discarding completed work."""
        if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
            raise ValueError("queries must contain non-empty strings")
        if len(queries) != len(max_publications_per_query):
            raise ValueError(
                "max_publications_per_query must contain one limit per query"
            )
        if any(
            limit is not None and limit < 1
            for limit in max_publications_per_query
        ):
            raise ValueError(
                "max_publications_per_query limits must be positive integers or None"
            )

        run_dir = context._resume_run_directory(
            dev_out_dir=dev_out_dir,
            run_id=run_id,
        )
        manifest_path = run_dir / "00_run_manifest.json"
        manifest = context._read_checkpoint(manifest_path)
        trace = DevTraceWriter.existing(run_dir)
        store = trace.checkpoint_store
        current = store.get_meta("run_fingerprint")
        if current is None:
            raise ValueError("trace does not contain a run fingerprint")
        current_configuration = current["configuration"]
        current_queries = current_configuration.get("query") or []
        normalized_current = [" ".join(query.split()) for query in current_queries]
        normalized_requested = [" ".join(query.split()) for query in queries]
        if (
            normalized_current == normalized_requested
            and current_configuration.get("max_publications_per_query")
            == list(max_publications_per_query)
            and current_configuration.get("max_publications") is None
            and current_configuration.get("query_file") is None
        ):
            archive = manifest.get("query_archive")
            return run_dir / archive if archive else run_dir
        replacement_configuration = dict(current_configuration)
        replacement_configuration.update(
            {
                "query": list(queries),
                "query_file": None,
                "max_publications": None,
                "max_publications_per_query": list(max_publications_per_query),
            }
        )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "queries": queries,
                    "limits": max_publications_per_query,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        amendment_id = f"query-expansion-{digest}"
        previous = store.amend_fingerprint(
            replacement_configuration,
            amendment_id=amendment_id,
            metadata={"run_id": run_dir.name, "reason": "append complementary searches"},
        )

        archive_directory = run_dir / "query_archives" / amendment_id
        if archive_directory.exists():
            archive_writer = DevTraceWriter.existing(archive_directory)
        else:
            archive_writer = DevTraceWriter(
                root=str(run_dir / "query_archives"),
                run_id=amendment_id,
                manifest={
                    "archive_id": amendment_id,
                    "source_run_id": run_dir.name,
                    "previous_manifest": manifest,
                    "previous_fingerprint": previous,
                },
            )
            archive_writer.write(
                "query_configuration.json",
                {
                    "previous": previous,
                    "replacement": store.get_meta("run_fingerprint"),
                },
            )
        amended_manifest = {
            **manifest,
            "query": list(queries),
            "query_file": None,
            "max_publications": None,
            "max_publications_per_query": list(max_publications_per_query),
            "query_amendment_id": amendment_id,
            "query_archive": str(archive_writer.directory.relative_to(run_dir)),
        }
        trace.write("00_run_manifest.json", amended_manifest)
        logger.info(
            "Atlas query amendment run_id=%s amendment_id=%s queries=%s limits=%s",
            run_dir.name,
            amendment_id,
            len(queries),
            max_publications_per_query,
        )
        return archive_writer.directory

