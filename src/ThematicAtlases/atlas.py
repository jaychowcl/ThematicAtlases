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

    def _collect_publication_texts(self, jsons: list[dict]) -> list[dict]:
        publications = []
        publication_index = {}

        for record in jsons:
            for publication in record.get("publications", []):
                publication_key = self._publication_key(publication=publication)

                if publication_key not in publication_index:
                    publication_index[publication_key] = len(publications)
                    publications.append(publication)

        if not publications:
            return jsons

        enriched_publications = EuropePMCWrapper().collect_publication_texts(
            publications=publications
        )
        enriched_publication_index = {
            self._publication_key(publication=publication): publication
            for publication in enriched_publications
        }

        return [
            {
                **record,
                "publications": [
                    enriched_publication_index.get(
                        self._publication_key(publication=publication),
                        publication,
                    )
                    for publication in record.get("publications", [])
                ],
            }
            for record in jsons
        ]

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
        result = self._collect_publication_texts(jsons=result)

        if out is not None:
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        return result

    def filter_jsons(self,) -> list[dict]:
        pass

    def harmonize_jsons(self, ) -> list[dict]:
        pass
