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

    def _filter_jsons(self, jsons: list[dict]) -> list[dict]:
        return [
            record
            for record in jsons
            if self._is_handled_accession(record=record)
        ]

    def _is_handled_accession(self, record: dict) -> bool:
        datalink_id_scheme = str(record.get("datalink_id_scheme", "")).upper()
        datalink_id = str(record.get("datalink_id", "")).upper()

        return datalink_id_scheme == "GEO" or datalink_id.startswith(
            GEO_ACCESSION_PREFIXES
        )

    def _collect_gse_jsons(self, jsons: list[dict]) -> list[dict]:
        geo_wrapper = GEOWrapper()
        records = []

        for record in jsons:
            gse_accession = geo_wrapper.get_gse(record.get("datalink_id", ""))

            if gse_accession is None:
                continue

            records.append(self._gse_record(record=record, gse_accession=gse_accession))

        return self._deduplicate_gse_jsons(jsons=records)

    def _gse_record(self, record: dict, gse_accession: str) -> dict:
        return {
            **record,
            "datalink_id": gse_accession,
            "original_datalinks": [
                {
                    "datalink_id": record.get("datalink_id", ""),
                    "datalink_id_scheme": record.get("datalink_id_scheme", ""),
                    "datalink_url": record.get("datalink_url", ""),
                    "datalink_category": record.get("datalink_category", ""),
                }
            ],
        }

    def _deduplicate_gse_jsons(self, jsons: list[dict]) -> list[dict]:
        records = []
        record_index = {}
        publication_keys = {}
        original_datalink_keys = {}

        for record in jsons:
            gse_accession = str(record.get("datalink_id", "")).strip().upper()

            if not gse_accession:
                continue

            if gse_accession not in record_index:
                record_index[gse_accession] = len(records)
                publication_keys[gse_accession] = set()
                original_datalink_keys[gse_accession] = set()
                records.append({**record, "publications": [], "original_datalinks": []})

            target_record = records[record_index[gse_accession]]

            for original_datalink in record.get("original_datalinks", []):
                original_datalink_key = self._original_datalink_key(
                    original_datalink=original_datalink
                )

                if original_datalink_key not in original_datalink_keys[gse_accession]:
                    original_datalink_keys[gse_accession].add(original_datalink_key)
                    target_record["original_datalinks"].append(original_datalink)

            for publication in record.get("publications", []):
                publication_key = self._publication_key(publication=publication)

                if publication_key not in publication_keys[gse_accession]:
                    publication_keys[gse_accession].add(publication_key)
                    target_record["publications"].append(publication)

        return records

    def _original_datalink_key(self, original_datalink: dict) -> tuple:
        return (
            original_datalink.get("datalink_id", ""),
            original_datalink.get("datalink_id_scheme", ""),
            original_datalink.get("datalink_url", ""),
            original_datalink.get("datalink_category", ""),
        )

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

        result = self._filter_jsons(
            EuropePMCWrapper().collect_accessions(queries=queries)
        )
        result = self._collect_gse_jsons(jsons=result)
        result = self._collect_publication_texts(jsons=result)

        if out is not None:
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        return result

    def filter_jsons(self,) -> list[dict]:
        pass

    def harmonize_jsons(self, ) -> list[dict]:
        pass
