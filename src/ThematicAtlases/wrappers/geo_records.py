"""Pure GEO metadata record projection and deduplication policy."""

from __future__ import annotations

import logging


logger = logging.getLogger("ThematicAtlases.wrappers.geo")


class GEORecordPolicy:
    """Project canonical GEO packages and merge linked records deterministically."""

    def metadata_records_from_packages(
        self,
        record: dict,
        packages: list[dict],
    ) -> list[dict]:
        return [
            self.metadata_record(
                record=record,
                package=package,
                package_gse=self.package_gse_accession(package)
                or record.get("datalink_id", ""),
            )
            for package in packages
        ]

    @staticmethod
    def package_gse_accession(package: dict) -> str:
        series = package.get("series") or {}
        accessions = series.get("accession") or []
        if not isinstance(accessions, list):
            accessions = [accessions]
        for accession in accessions:
            if isinstance(accession, dict):
                accession = accession.get("value", "")
            value = str(accession or "").strip().upper()
            if value.startswith("GSE"):
                return value
        return ""

    @staticmethod
    def metadata_record(record: dict, package: dict, package_gse: str) -> dict:
        metadata_record = {
            **record,
            "datalink_id": package_gse,
            "metadata_repository": "geo",
            "metadata_source": "geo2json",
            "metadata_status": "available",
            "accession_metadata": package,
        }
        if package_gse != record.get("datalink_id", ""):
            metadata_record["source_datalink_id"] = record.get("datalink_id", "")
        return metadata_record

    @staticmethod
    def metadata_error_record(record: dict) -> dict:
        return {
            **record,
            "metadata_repository": "geo",
            "metadata_source": "geo2json",
            "metadata_status": "error",
            "accession_metadata": None,
        }

    @staticmethod
    def metadata_unavailable_record(record: dict) -> dict:
        return {
            **record,
            "metadata_repository": "geo",
            "metadata_source": "geo2json",
            "metadata_status": "unavailable",
            "accession_metadata": None,
        }

    @staticmethod
    def gse_record(record: dict, gse_accession: str) -> dict:
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

    def deduplicate_gse_jsons(self, records_to_merge: list[dict]) -> list[dict]:
        records = []
        record_index = {}
        publication_keys = {}
        original_datalink_keys = {}
        duplicate_rows = 0
        publication_links = 0
        original_datalink_links = 0
        for record in records_to_merge:
            gse_accession = str(record.get("datalink_id", "")).strip().upper()
            if not gse_accession:
                continue
            if gse_accession not in record_index:
                record_index[gse_accession] = len(records)
                publication_keys[gse_accession] = set()
                original_datalink_keys[gse_accession] = set()
                records.append({**record, "publications": [], "original_datalinks": []})
            else:
                duplicate_rows += 1
            target_record = records[record_index[gse_accession]]
            for original_datalink in record.get("original_datalinks", []):
                key = self.original_datalink_key(original_datalink)
                if key not in original_datalink_keys[gse_accession]:
                    original_datalink_keys[gse_accession].add(key)
                    target_record["original_datalinks"].append(original_datalink)
                    original_datalink_links += 1
            for publication in record.get("publications", []):
                key = self.publication_key(publication)
                if key not in publication_keys[gse_accession]:
                    publication_keys[gse_accession].add(key)
                    target_record["publications"].append(publication)
                    publication_links += 1
            if (
                target_record.get("metadata_status") != "available"
                and record.get("metadata_status") == "available"
            ):
                target_record["metadata_repository"] = record.get(
                    "metadata_repository", ""
                )
                target_record["metadata_source"] = record.get("metadata_source", "")
                target_record["metadata_status"] = record.get("metadata_status", "")
                target_record["accession_metadata"] = record.get("accession_metadata")
                if "source_datalink_id" in record:
                    target_record["source_datalink_id"] = record["source_datalink_id"]
        logger.info(
            "GEO GSE dedupe stats input_rows=%s output_rows=%s "
            "duplicate_rows_collapsed=%s publication_links=%s "
            "original_datalink_links=%s",
            len(records_to_merge),
            len(records),
            duplicate_rows,
            publication_links,
            original_datalink_links,
        )
        return records

    @staticmethod
    def original_datalink_key(original_datalink: dict) -> tuple:
        return (
            original_datalink.get("datalink_id", ""),
            original_datalink.get("datalink_id_scheme", ""),
            original_datalink.get("datalink_url", ""),
            original_datalink.get("datalink_category", ""),
        )

    @staticmethod
    def publication_key(publication: dict) -> tuple:
        return (
            publication.get("source", ""),
            publication.get("epmc_id", ""),
            publication.get("pmid", ""),
            publication.get("pmcid", ""),
            publication.get("doi", ""),
        )
