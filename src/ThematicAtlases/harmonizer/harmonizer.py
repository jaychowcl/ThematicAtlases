import copy
from concurrent.futures import as_completed, ThreadPoolExecutor
import hashlib
import json
import logging

from ThematicAtlases.checkpoint import is_retryable_error

logger = logging.getLogger(__name__)


class AtlasHarmonizer:
    REMOVED_HARMONIZATION_OPTIONS = frozenset(
        {"llm", "lookup_llm_judge", "search_llm_judge"}
    )
    MODEL_STAGE_DEFAULTS = {
        "target_checker": True,
        "direct_lookup_judge": True,
        "rag_lookup": True,
        "rag_lookup_judge": True,
        "ols_lookup": True,
        "ols_lookup_judge": True,
        "field_assignment_judge": True,
    }

    def __init__(
        self,
        ontology_harmonizer=None,
        ontology_harmonizer_factory=None,
        ontostore=None,
        credential_checker=None,
        max_workers: int = 1,
    ):
        self._ontology_harmonizer_instance = ontology_harmonizer
        self._ontology_harmonizer_factory = ontology_harmonizer_factory
        self._ontostore = ontostore
        self._credential_checker = credential_checker
        self._credentials_checked = False
        if max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        self._max_workers = max_workers

    def harmonize_datasets(
        self,
        datasets: dict,
        details_out: str | None = None,
        harmonization_options: dict | None = None,
        checkpoint_store=None,
    ) -> tuple[dict, list[dict]]:
        source_accessions = [dict(record) for record in datasets.get("accessions", [])]
        accessions = list(source_accessions)
        details: list[dict | None] = [None] * len(accessions)
        harmonization_options = dict(harmonization_options or {})
        self._validate_harmonization_options(harmonization_options)
        work_by_key = {}

        for index, record in enumerate(accessions):
            metadata = record.get("accession_metadata")
            datalink_id = record.get("datalink_id", "")

            if not isinstance(metadata, (dict, list)):
                record["ontology_harmonization_run_status"] = "not_run"
                record.pop("ontology_harmonization_error", None)
                details[index] = {
                    "datalink_id": datalink_id,
                    "run_status": "not_run",
                }
                continue

            context = self.publication_context(record)
            key = self._work_key(
                metadata=metadata,
                publication_context=context,
                harmonization_options=harmonization_options,
            )
            work_by_key.setdefault(
                key,
                {
                    "work_key": hashlib.sha256(key.encode("utf-8")).hexdigest(),
                    "metadata": metadata,
                    "publication_context": context,
                    "indices": [],
                },
            )["indices"].append(index)

        if work_by_key:
            if self._requires_model_credentials(harmonization_options):
                self._preflight_credentials()
            ontology_harmonizer = self._ontology_harmonizer()
            work_items = list(work_by_key.values())
            for position, item in enumerate(work_items, start=1):
                item["position"] = position
                item["total"] = len(work_items)

            def run(item):
                logger.info(
                    "Atlas ontology harmonization progress work_index=%s work_total=%s accession_count=%s",
                    item["position"],
                    item["total"],
                    len(item["indices"]),
                )
                try:
                    return ontology_harmonizer.harmonize_miniml_json(
                        publication_context=item["publication_context"],
                        miniml_json=copy.deepcopy(item["metadata"]),
                        **harmonization_options,
                    ), None
                except Exception as error:
                    return None, error

            def apply_outcome(item, harmonization, error, *, cached=False):
                for index in item["indices"]:
                    record = accessions[index]
                    datalink_id = record.get("datalink_id", "")
                    if error is not None:
                        logger.error(
                            "Atlas ontology harmonization failed datalink_id=%r error=%r",
                            datalink_id,
                            error,
                        )
                        record["ontology_harmonization_run_status"] = "error"
                        record["ontology_harmonization_error"] = str(error)
                        details[index] = {
                            "datalink_id": datalink_id,
                            "run_status": "error",
                            "error": str(error),
                        }
                        continue

                    record["accession_metadata"] = harmonization["miniml_json"]
                    record["ontology_harmonization_run_status"] = "completed"
                    record.pop("ontology_harmonization_error", None)
                    details[index] = {
                        "datalink_id": datalink_id,
                        "run_status": "completed",
                        "harmonization_targets": harmonization.get(
                            "harmonization_targets", []
                        ),
                        "workflow": harmonization.get("workflow"),
                        "target_paths": harmonization.get("target_paths"),
                    }
                    if "preferred_ontology_ids" in harmonization:
                        details[index]["preferred_ontology_ids"] = harmonization[
                            "preferred_ontology_ids"
                        ]
                    if "controls" in harmonization:
                        details[index]["controls"] = harmonization["controls"]

                if checkpoint_store is None or cached:
                    return
                if error is None:
                    checkpoint_store.put(
                        "harmonization",
                        item["work_key"],
                        item["position"],
                        "available",
                        payload=harmonization,
                    )
                else:
                    checkpoint_store.put(
                        "harmonization",
                        item["work_key"],
                        item["position"],
                        "retryable_error"
                        if is_retryable_error(error)
                        else "terminal_error",
                        error=str(error),
                    )

            pending = []
            for item in work_items:
                checkpoint = (
                    checkpoint_store.get("harmonization", item["work_key"])
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] == "available":
                    apply_outcome(item, checkpoint["payload"], None, cached=True)
                elif checkpoint and checkpoint["status"] == "terminal_error":
                    apply_outcome(
                        item,
                        None,
                        RuntimeError(checkpoint["error"] or "harmonization failed"),
                        cached=True,
                    )
                else:
                    pending.append(item)

            if self._max_workers == 1:
                for item in pending:
                    harmonization, error = run(item)
                    apply_outcome(item, harmonization, error)
            else:
                with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                    futures = {executor.submit(run, item): item for item in pending}
                    for future in as_completed(futures):
                        item = futures[future]
                        harmonization, error = future.result()
                        apply_outcome(item, harmonization, error)

        details = [detail for detail in details if detail is not None]

        result = {**datasets, "accessions": accessions}
        if details_out is not None:
            with open(details_out, "w", encoding="utf-8") as handle:
                json.dump(details, handle, indent=2)

        logger.info(
            "Atlas ontology harmonization stats accessions=%s completed=%s not_run=%s errors=%s details_path=%s",
            len(accessions),
            sum(item["run_status"] == "completed" for item in details),
            sum(item["run_status"] == "not_run" for item in details),
            sum(item["run_status"] == "error" for item in details),
            details_out,
        )
        return result, details

    def _work_key(
        self,
        metadata,
        publication_context: str | None,
        harmonization_options: dict,
    ) -> str:
        key_data = {
            "metadata": metadata,
            "publication_context": publication_context,
            "harmonization_options": harmonization_options,
        }
        preferred_ontology_ids = self._preferred_ontology_ids()
        if preferred_ontology_ids:
            key_data["preferred_ontology_ids"] = preferred_ontology_ids
        return json.dumps(
            key_data,
            sort_keys=True,
            default=repr,
        )

    def _preferred_ontology_ids(self) -> list[str]:
        store = self._ontostore
        if store is None and self._ontology_harmonizer_instance is not None:
            store = getattr(self._ontology_harmonizer_instance, "ontostore", None)
        return list(getattr(store, "preferred_ontology_ids", ()) or ())

    def publication_context(self, record: dict) -> str | None:
        contexts = []

        for publication in record.get("publications", []):
            parts = []
            title = str(publication.get("title", "") or "").strip()
            abstract = str(publication.get("abstractText", "") or "").strip()

            if title:
                parts.append(f"Title: {title}")
            if abstract:
                parts.append(f"Abstract: {abstract}")
            if parts:
                contexts.append("\n".join(parts))

        return "\n\n".join(contexts) or None

    def harmonize_jsons(
        self,
        datasets: dict,
        details_out: str | None = None,
        harmonization_options: dict | None = None,
    ) -> dict:
        result, _ = self.harmonize_datasets(
            datasets=datasets,
            details_out=details_out,
            harmonization_options=harmonization_options,
        )
        return result

    def _ontology_harmonizer(self):
        if self._ontology_harmonizer_instance is not None:
            return self._ontology_harmonizer_instance

        if self._ontology_harmonizer_factory is not None:
            self._ontology_harmonizer_instance = self._ontology_harmonizer_factory()
            return self._ontology_harmonizer_instance

        from agentic_curator import OntologyHarmonizer

        if self._ontostore is None:
            self._ontology_harmonizer_instance = OntologyHarmonizer()
        else:
            self._ontology_harmonizer_instance = OntologyHarmonizer(
                ontostore=self._ontostore
            )
        return self._ontology_harmonizer_instance

    def _preflight_credentials(self) -> None:
        if self._credential_checker is None or self._credentials_checked:
            return
        self._credential_checker.check()
        self._credentials_checked = True

    @classmethod
    def _validate_harmonization_options(cls, options: dict) -> None:
        removed = sorted(cls.REMOVED_HARMONIZATION_OPTIONS.intersection(options))
        if removed:
            joined = ", ".join(removed)
            raise ValueError(
                f"removed harmonization option(s): {joined}; use the "
                "stage-specific target, direct, RAG, OLS, and field controls"
            )

    @classmethod
    def _requires_model_credentials(cls, options: dict) -> bool:
        controls = {**cls.MODEL_STAGE_DEFAULTS, **options}
        return bool(
            controls["target_checker"]
            or controls["direct_lookup_judge"]
            or controls["rag_lookup"]
            or (controls["ols_lookup"] and controls["ols_lookup_judge"])
            or controls["field_assignment_judge"]
        )
