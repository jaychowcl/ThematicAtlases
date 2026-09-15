"""HarmonizeDatasetsWorkflow: application orchestration behind the Atlas facade.

The injected context preserves existing subclass hooks; workflow instances are
operation-local and do not own shared clients or persistent state.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ThematicAtlases.atlas import Atlas

from ThematicAtlases.domain import AtlasDocument


class HarmonizeDatasetsWorkflow:
    def __init__(self, context: Atlas):
        self.context = context

    def run(
        self,
        datasets: dict,
        harmonization_details_out: str | None = None,
        harmonization_options: dict | None = None,
        review_decisions: dict | None = None,
    ) -> dict:
        context = self.context
        document = AtlasDocument.from_mapping(datasets)
        legacy = context._documents.to_legacy(document)
        result, details = context._harmonizer.harmonize_datasets(
            datasets=legacy,
            details_out=harmonization_details_out,
            harmonization_options=harmonization_options,
            **(
                {"review_decisions": review_decisions}
                if review_decisions is not None
                else {}
            ),
        )
        updated = context._documents.assemble(
            result,
            atlas_metadata={
                "atlas_id": document.atlas.atlas_id,
                "title": document.atlas.title,
                "theme": document.atlas.theme,
            },
            run_id=document.run.run_id,
            created_at=document.run.created_at,
            theme=document.atlas.theme,
            config={
                "queries": list(document.run.config.queries),
                "metadata_repositories": list(
                    document.run.config.metadata_repositories
                ),
                **dict(document.run.config.options),
            },
            run_status=context._final_run_status(result),
            harmonization_details=details,
        )
        return updated.to_mapping()

