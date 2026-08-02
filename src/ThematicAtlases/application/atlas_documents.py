"""Application service for the public Atlas v1 document boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher
from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.domain import AtlasDocument, RunStatus
from ThematicAtlases.ports import ArtifactPublisherPort
from ThematicAtlases.summary import summary_path


class AtlasDocumentService:
    """Assemble, project, summarize, and publish Atlas v1 documents."""

    def __init__(
        self,
        *,
        adapter: AtlasDocumentAdapter | None = None,
        publisher: ArtifactPublisherPort | None = None,
    ) -> None:
        self._adapter = adapter or AtlasDocumentAdapter()
        self._publisher = publisher or JsonArtifactBundlePublisher()

    def assemble(
        self,
        stage_result: Mapping[str, Any],
        *,
        atlas_metadata: Mapping[str, Any],
        run_id: str,
        created_at: str,
        theme: str,
        config: Mapping[str, Any],
        run_status: RunStatus,
        harmonization_details: list[Mapping[str, Any]] | None = None,
    ) -> AtlasDocument:
        return self._adapter.assemble(
            stage_result,
            atlas_metadata=atlas_metadata,
            run_id=run_id,
            created_at=created_at,
            theme=theme,
            config=config,
            run_status=run_status,
            harmonization_details=harmonization_details,
        )

    def to_legacy(self, document: AtlasDocument) -> dict[str, Any]:
        return self._adapter.to_legacy(document)

    @staticmethod
    def summary(
        document: AtlasDocument,
        atlas_path: str | Path | None,
        *,
        unsupported_accessions_report: Mapping[str, Any] | None = None,
        unsupported_accessions_path: str | Path | None = None,
    ) -> dict:
        unsupported_summary = dict(
            (unsupported_accessions_report or {}).get("summary") or {}
        )
        return {
            "schema_version": document.schema_version,
            "atlas_id": document.atlas.atlas_id,
            "run_id": document.run.run_id,
            "atlas_path": None if atlas_path is None else str(atlas_path),
            "dataset_count": document.summary.dataset_count,
            "publication_count": document.summary.publication_count,
            "completed_dataset_count": document.summary.completed_dataset_count,
            "failed_dataset_count": document.summary.failed_dataset_count,
            "unsupported_accession_count": int(
                unsupported_summary.get("accession_count", 0)
            ),
            "unsupported_accession_repository_counts": dict(
                unsupported_summary.get("repository_counts") or {}
            ),
            "unsupported_accessions_path": None
            if unsupported_accessions_path is None
            else str(unsupported_accessions_path),
        }

    def publish(
        self,
        document: AtlasDocument,
        out: str | Path,
        *,
        include_summary: bool,
        unsupported_accessions_report: Mapping[str, Any] | None = None,
        unsupported_accessions_path: str | Path | None = None,
    ) -> dict:
        destination = Path(out)
        summary = self.summary(
            document,
            destination,
            unsupported_accessions_report=unsupported_accessions_report,
            unsupported_accessions_path=unsupported_accessions_path,
        )
        artifacts: dict[Path, Any] = {destination: document.to_mapping()}
        if include_summary:
            artifacts[summary_path(destination)] = summary
        if unsupported_accessions_path is not None:
            artifacts[Path(unsupported_accessions_path)] = dict(
                unsupported_accessions_report or {}
            )
        self._publisher.publish(artifacts)
        return summary

    def publish_unsupported_accessions(
        self,
        report: Mapping[str, Any],
        out: str | Path,
    ) -> None:
        self._publisher.publish({Path(out): dict(report)})


__all__ = ["AtlasDocumentService"]
