import copy
import json
import logging

logger = logging.getLogger(__name__)


class AtlasHarmonizer:
    def __init__(
        self,
        ontology_harmonizer=None,
        ontology_harmonizer_factory=None,
    ):
        self._ontology_harmonizer_instance = ontology_harmonizer
        self._ontology_harmonizer_factory = ontology_harmonizer_factory

    def harmonize_datasets(
        self,
        datasets: dict,
        details_out: str | None = None,
        harmonization_options: dict | None = None,
    ) -> tuple[dict, list[dict]]:
        accessions = []
        details = []
        ontology_harmonizer = self._ontology_harmonizer_instance
        harmonization_options = dict(harmonization_options or {})

        for record in datasets.get("accessions", []):
            record = dict(record)
            metadata = record.get("accession_metadata")
            datalink_id = record.get("datalink_id", "")

            if not isinstance(metadata, (dict, list)):
                record["ontology_harmonization_status"] = "unavailable"
                record.pop("ontology_harmonization_error", None)
                details.append(
                    {"datalink_id": datalink_id, "status": "unavailable"}
                )
                accessions.append(record)
                continue

            if ontology_harmonizer is None:
                ontology_harmonizer = self._ontology_harmonizer()

            try:
                harmonization = ontology_harmonizer.harmonize_miniml_json(
                    publication_context=self.publication_context(record),
                    miniml_json=copy.deepcopy(metadata),
                    **harmonization_options,
                )
                record["accession_metadata"] = harmonization["miniml_json"]
                record["ontology_harmonization_status"] = "available"
                record.pop("ontology_harmonization_error", None)
                details.append(
                    {
                        "datalink_id": datalink_id,
                        "status": "available",
                        "harmonization_targets": harmonization.get(
                            "harmonization_targets", []
                        ),
                        "strategy": harmonization.get("strategy"),
                        "target_paths": harmonization.get("target_paths"),
                    }
                )
            except Exception as error:
                logger.exception(
                    "Atlas ontology harmonization failed datalink_id=%r",
                    datalink_id,
                )
                record["ontology_harmonization_status"] = "error"
                record["ontology_harmonization_error"] = str(error)
                details.append(
                    {
                        "datalink_id": datalink_id,
                        "status": "error",
                        "error": str(error),
                    }
                )

            accessions.append(record)

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
