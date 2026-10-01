"""PublicationTextStage: a typed operation shared by caller-specific scheduling."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from .results import PublicationTextsResult
if TYPE_CHECKING:
    from ThematicAtlases.filterer.filterer import AtlasFilterer
from ThematicAtlases.filterer.review import PUBLICATIONS
import logging
logger = logging.getLogger("ThematicAtlases.filterer.filterer")


@dataclass(frozen=True, kw_only=True)
class PublicationTextRequest:
    jsons: list[dict]
    publication_texts: dict | None = None
    checkpoint_store: Any = None


class PublicationTextStage:
    def __init__(self, owner: AtlasFilterer):
        self.owner = owner

    def run(self, request: PublicationTextRequest) -> PublicationTextsResult:
        return PublicationTextsResult(self._execute(
            jsons=request.jsons,
            publication_texts=request.publication_texts,
            checkpoint_store=request.checkpoint_store,
        ))

    def _execute(
        self,
        jsons: list[dict],
        publication_texts: dict | None = None,
        checkpoint_store=None,
    ) -> dict:
        import inspect
        stage_owner = self.owner
        publication_texts = dict(publication_texts or {})
        publications = []
        publication_index = {}

        for record in jsons:
            for publication in record.get(PUBLICATIONS, []):
                if checkpoint_store is not None:
                    saved = checkpoint_store.get("publication_text", f"{publication.get('source', '')}:{publication.get('epmc_id', '')}")
                    if saved and saved["status"] in {"available", "no_data", "terminal_error"}:
                        saved_publication = (saved.get("payload") or {}).get("publication", {})
                        publication = {**publication, **{key: saved_publication[key] for key in ("text", "text_source", "full_text_status") if key in saved_publication}}
                publication_ref = stage_owner.publication_text_ref(publication=publication)

                if publication_ref in publication_texts:
                    continue
                if (
                    publication.get("text_source")
                    or publication.get("full_text_status")
                ):
                    publication_texts[publication_ref] = {
                        **({"checkpoint_key": f"{publication.get('source', '')}:{publication.get('epmc_id', '')}"} if checkpoint_store is not None and publication.get("epmc_id") else {}),
                    "text": publication.get("text", ""),
                        "text_source": publication.get("text_source", "none"),
                        "full_text_status": publication.get(
                            "full_text_status",
                            "unavailable",
                        ),
                    }
                    continue

                publication_key = stage_owner.publication_key(publication=publication)

                if publication_key not in publication_index:
                    publication_index[publication_key] = len(publications)
                    publications.append(publication)

        if not publications:
            logger.info(
                "Atlas publication text stats input_accessions=%s unique_publications=0 publication_texts=%s",
                len(jsons),
                len(publication_texts),
            )
            return publication_texts

        logger.info(
            "Atlas publication text progress unique_publications=%s",
            len(publications),
        )
        text_options = {"publications": publications}
        if checkpoint_store is not None:
            text_options["checkpoint_store"] = checkpoint_store
        wrapper = stage_owner._epmc_wrapper()
        if "extract_accessions" in inspect.signature(wrapper.collect_publication_texts).parameters:
            text_options["extract_accessions"] = False
        enriched_publications = wrapper.collect_publication_texts(**text_options)

        publication_texts.update(
            {
                publication_ref: {
                    **({"checkpoint_key": f"{publication.get('source', '')}:{publication.get('epmc_id', '')}"} if checkpoint_store is not None and publication.get("epmc_id") else {}),
                    "text": publication.get("text", ""),
                    "text_source": publication.get("text_source", "none"),
                    "full_text_status": publication.get(
                        "full_text_status",
                        "unavailable",
                    ),
                }
                for publication in enriched_publications
                if (
                    publication_ref := stage_owner.publication_text_ref(
                        publication=publication
                    )
                )
            }
        )
        logger.info(
            "Atlas publication text stats input_accessions=%s unique_publications=%s publication_texts=%s",
            len(jsons),
            len(publications),
            len(publication_texts),
        )
        return publication_texts

