import copy
from concurrent.futures import ThreadPoolExecutor
import json
import logging

logger = logging.getLogger(__name__)


class AtlasHarmonizer:
    def __init__(
        self,
        ontology_harmonizer=None,
        ontology_harmonizer_factory=None,
        credential_checker=None,
        max_workers: int = 1,
    ):
        self._ontology_harmonizer_instance = ontology_harmonizer
        self._ontology_harmonizer_factory = ontology_harmonizer_factory
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
    ) -> tuple[dict, list[dict]]:
        source_accessions = [dict(record) for record in datasets.get("accessions", [])]
        accessions = list(source_accessions)
        details: list[dict | None] = [None] * len(accessions)
        harmonization_options = dict(harmonization_options or {})
        work_by_key = {}

        for index, record in enumerate(accessions):
            metadata = record.get("accession_metadata")
            datalink_id = record.get("datalink_id", "")

            if not isinstance(metadata, (dict, list)):
                record["ontology_harmonization_status"] = "unavailable"
                record.pop("ontology_harmonization_error", None)
                details[index] = {
                    "datalink_id": datalink_id,
                    "status": "unavailable",
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
                    "metadata": metadata,
                    "publication_context": context,
                    "indices": [],
                },
            )["indices"].append(index)

        if work_by_key:
            if harmonization_options.get("llm", True):
                self._preflight_credentials()
            ontology_harmonizer = self._ontology_harmonizer()
            work_items = list(work_by_key.values())

            def run(item):
                try:
                    return ontology_harmonizer.harmonize_miniml_json(
                        publication_context=item["publication_context"],
                        miniml_json=copy.deepcopy(item["metadata"]),
                        **harmonization_options,
                    ), None
                except Exception as error:
                    return None, error

            if self._max_workers == 1:
                outcomes = [run(item) for item in work_items]
            else:
                with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                    outcomes = list(executor.map(run, work_items))

            for item, (harmonization, error) in zip(work_items, outcomes):
                for index in item["indices"]:
                    record = accessions[index]
                    datalink_id = record.get("datalink_id", "")
                    if error is not None:
                        logger.error(
                            "Atlas ontology harmonization failed datalink_id=%r error=%r",
                            datalink_id,
                            error,
                        )
                        record["ontology_harmonization_status"] = "error"
                        record["ontology_harmonization_error"] = str(error)
                        details[index] = {
                            "datalink_id": datalink_id,
                            "status": "error",
                            "error": str(error),
                        }
                        continue

                    record["accession_metadata"] = harmonization["miniml_json"]
                    record["ontology_harmonization_status"] = "available"
                    record.pop("ontology_harmonization_error", None)
                    details[index] = {
                        "datalink_id": datalink_id,
                        "status": "available",
                        "harmonization_targets": harmonization.get(
                            "harmonization_targets", []
                        ),
                        "strategy": harmonization.get("strategy"),
                        "target_paths": harmonization.get("target_paths"),
                    }

        details = [detail for detail in details if detail is not None]

        result = {**datasets, "accessions": accessions}
        if details_out is not None:
            with open(details_out, "w", encoding="utf-8") as handle:
                json.dump(details, handle, indent=2)

        logger.info(
            "Atlas ontology harmonization stats accessions=%s available=%s unavailable=%s errors=%s details_path=%s",
            len(accessions),
            sum(item["status"] == "available" for item in details),
            sum(item["status"] == "unavailable" for item in details),
            sum(item["status"] == "error" for item in details),
            details_out,
        )
        return result, details

    def _work_key(
        self,
        metadata,
        publication_context: str | None,
        harmonization_options: dict,
    ) -> str:
        return json.dumps(
            {
                "metadata": metadata,
                "publication_context": publication_context,
                "harmonization_options": harmonization_options,
            },
            sort_keys=True,
            default=repr,
        )

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

        self._ontology_harmonizer_instance = OntologyHarmonizer()
        return self._ontology_harmonizer_instance

    def _preflight_credentials(self) -> None:
        if self._credential_checker is None or self._credentials_checked:
            return
        self._credential_checker.check()
        self._credentials_checked = True
