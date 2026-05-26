import json

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

GEO_ACCESSION_PREFIXES = ("GSE", "GSM", "GPL", "GDS")


class Atlas():
    def __init__(self, metadata: dict):
        pass

    def _load_queries(self, file: str) -> list[str]:
        with open(file, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def _filter_accessions(self, accessions: list[dict]) -> list[dict]:
        return [
            record
            for record in accessions
            if self._is_handled_accession(record=record)
        ]

    def _is_handled_accession(self, record: dict) -> bool:
        datalink_id_scheme = str(record.get("datalink_id_scheme", "")).upper()
        datalink_id = str(record.get("datalink_id", "")).upper()

        return datalink_id_scheme == "GEO" or datalink_id.startswith(
            GEO_ACCESSION_PREFIXES
        )

    def _collect_accession_metadata(self, jsons: list[dict]) -> list[dict]:
        records = []
        repository_records = {}

        for record in jsons:
            repository = self._metadata_repository(record=record)
            if repository is None:
                continue
            repository_records.setdefault(repository, []).append(record)

        for repository, repository_jsons in repository_records.items():
            records.extend(
                self._metadata_handler(repository=repository).collect_accession_metadata(
                    jsons=repository_jsons
                )
            )

        return records

    def _metadata_repository(self, record: dict) -> str | None:
        if self._is_handled_accession(record=record):
            return "geo"

        return None

    def _metadata_handler(self, repository: str):
        if repository == "geo":
            return GEOWrapper()

        raise ValueError(f"Unsupported metadata repository: {repository}")

    def _publication_key(self, publication: dict) -> tuple:
        return (
            publication.get("source", ""),
            publication.get("epmc_id", ""),
            publication.get("pmid", ""),
            publication.get("pmcid", ""),
            publication.get("doi", ""),
        )

    def _publication_text_ref(self, publication: dict) -> str:
        for key in ("pmid", "pmcid", "doi"):
            value = str(publication.get(key, "")).strip()

            if value:
                return value

        source = str(publication.get("source", "")).strip()
        epmc_id = str(publication.get("epmc_id", "")).strip()

        if source or epmc_id:
            return f"{source}:{epmc_id}"

        return ""

    def _collect_publication_texts(self, jsons: list[dict]) -> dict:
        publications = []
        publication_index = {}

        for record in jsons:
            for publication in record.get("publications", []):
                publication_key = self._publication_key(publication=publication)

                if publication_key not in publication_index:
                    publication_index[publication_key] = len(publications)
                    publications.append(publication)

        if not publications:
            return {}

        enriched_publications = EuropePMCWrapper().collect_publication_texts(
            publications=publications
        )

        return {
            publication_ref: {
                "text": publication.get("text", ""),
                "text_source": publication.get("text_source", "none"),
                "full_text_status": publication.get("full_text_status", "unavailable"),
            }
            for publication in enriched_publications
            if (publication_ref := self._publication_text_ref(publication=publication))
        }

    def _accessions_with_publication_text_refs(
        self,
        jsons: list[dict],
        publication_texts: dict,
    ) -> list[dict]:
        return [
            {
                **record,
                "publications": [
                    self._publication_with_text_ref(
                        publication=publication,
                        publication_texts=publication_texts,
                    )
                    for publication in record.get("publications", [])
                ],
            }
            for record in jsons
        ]

    def _publication_with_text_ref(
        self,
        publication: dict,
        publication_texts: dict,
    ) -> dict:
        publication_ref = self._publication_text_ref(publication=publication)
        publication = {
            key: value
            for key, value in publication.items()
            if key not in {"text", "text_source", "full_text_status"}
        }

        if publication_ref in publication_texts:
            publication["publication_text_ref"] = publication_ref

        return publication

    def collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
    ) -> list[dict]:
        queries = list(query or [])

        if file is not None:
            queries.extend(self._load_queries(file))

        result = self._filter_accessions(
            EuropePMCWrapper().collect_accessions(queries=queries)
        )
        result = self._collect_accession_metadata(jsons=result)

        if out is not None:
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        return result

    def filter_jsons(self, jsons: list[dict] | None = None) -> dict:
        jsons = list(jsons or [])
        publication_texts = self._collect_publication_texts(jsons=jsons)

        return {
            "accessions": self._accessions_with_publication_text_refs(
                jsons=jsons,
                publication_texts=publication_texts,
            ),
            "publication_texts": publication_texts,
        }

    def harmonize_jsons(self, ) -> list[dict]:
        pass
