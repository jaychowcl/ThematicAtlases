import logging
import time
from contextlib import nullcontext

from meta_standards_converter.converters.geo2json import geo2json
import requests

from ThematicAtlases.checkpoint import is_retryable_error

logger = logging.getLogger(__name__)


class GEOWrapper:
    def __init__(
        self,
        api_key: str | None = None,
        tool: str = "ThematicAtlases",
        email: str | None = None,
        timeout: int = 30,
        request_delay: float = 0.34,
        max_retries: int = 3,
    ):
        self._api_key = api_key
        self._tool = tool
        self._email = email
        self._request_settings = {
            "timeout": timeout,
            "request_delay": request_delay,
            "max_retries": max_retries,
        }
        self._base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self._retry_statuses = {429, 500, 502, 503, 504}

    def collect_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        records = []
        dropped_records = 0

        logger.info(
            "GEO accession metadata progress stage=resolve-accessions input_records=%s",
            len(jsons),
        )

        for index, record in enumerate(jsons, start=1):
            if index == 1 or index == len(jsons) or index % 10 == 0:
                logger.info(
                    "GEO accession resolution progress record_index=%s record_total=%s",
                    index,
                    len(jsons),
                )
            source_accession = self._normalize_accession(
                record.get("datalink_id", "")
            )
            item_lock = (
                checkpoint_store.item_lock("geo_resolution", source_accession)
                if checkpoint_store is not None
                else nullcontext()
            )
            with item_lock:
                checkpoint = (
                    checkpoint_store.get("geo_resolution", source_accession)
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] in {"available", "no_data"}:
                    gse_accession = (checkpoint.get("payload") or {}).get("gse_accession")
                else:
                    try:
                        gse_accession = self.get_gse(source_accession)
                    except Exception as error:
                        if checkpoint_store is not None:
                            checkpoint_store.put(
                                "geo_resolution",
                                source_accession,
                                index,
                                "retryable_error"
                                if is_retryable_error(error)
                                else "terminal_error",
                                error=str(error),
                            )
                        raise
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            "geo_resolution",
                            source_accession,
                            index,
                            "available" if gse_accession else "no_data",
                            payload={"gse_accession": gse_accession},
                        )

            if gse_accession is None:
                dropped_records += 1
                continue

            records.append(self._gse_record(record=record, gse_accession=gse_accession))

        deduplicated_records = self._deduplicate_gse_jsons(jsons=records)
        logger.info(
            "GEO accession resolution stats input_records=%s resolved_records=%s dropped_records=%s deduplicated_gse_records=%s",
            len(jsons),
            len(records),
            dropped_records,
            len(deduplicated_records),
        )
        logger.info(
            "GEO accession metadata progress stage=collect-gse-metadata gse_records=%s",
            len(deduplicated_records),
        )
        result = self._collect_gse_metadata_records(
            records=deduplicated_records,
            checkpoint_store=checkpoint_store,
        )
        logger.info(
            "GEO accession metadata stats input_records=%s output_records=%s dropped_records=%s",
            len(jsons),
            len(result),
            dropped_records,
        )
        return result

    def available_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store,
    ) -> list[dict]:
        """Overlay completed metadata without issuing network requests."""
        resolved = []
        for record in jsons:
            source_accession = self._normalize_accession(record.get("datalink_id", ""))
            checkpoint = checkpoint_store.get("geo_resolution", source_accession)
            if checkpoint and checkpoint["status"] in {"available", "no_data"}:
                gse_accession = (checkpoint.get("payload") or {}).get("gse_accession")
            elif source_accession.startswith("GSE"):
                gse_accession = source_accession
            else:
                gse_accession = None
            if gse_accession:
                resolved.append(self._gse_record(record, gse_accession))
            else:
                resolved.append(
                    {
                        **record,
                        "metadata_repository": "geo",
                        "metadata_status": "pending",
                        "accession_metadata": None,
                    }
                )

        gse_records = self._deduplicate_gse_jsons(
            [record for record in resolved if str(record.get("datalink_id", "")).upper().startswith("GSE")]
        )
        pending_non_gse = [
            record
            for record in resolved
            if not str(record.get("datalink_id", "")).upper().startswith("GSE")
        ]
        enriched = []
        for record in gse_records:
            checkpoint = checkpoint_store.get("geo_metadata", record.get("datalink_id", ""))
            if checkpoint and checkpoint["status"] in {"available", "no_data", "terminal_error"}:
                enriched.extend(self._records_from_metadata_checkpoint(record, checkpoint))
            else:
                enriched.append(
                    {
                        **record,
                        "metadata_repository": "geo",
                        "metadata_status": "pending",
                        "accession_metadata": None,
                    }
                )
        return self._deduplicate_gse_jsons(enriched) + pending_non_gse

    def get_gse(self, accession: str) -> str | None:
        accession = self._normalize_accession(accession=accession)

        if not accession:
            logger.debug("GEO accession resolution decision accession=%r result=empty", accession)
            return None

        if accession.startswith("GSE"):
            logger.debug(
                "GEO accession resolution decision accession=%r result=direct_gse",
                accession,
            )
            return accession

        if accession.startswith("GPL"):
            logger.debug(
                "GEO accession resolution decision accession=%r result=drop_gpl",
                accession,
            )
            return None

        if not accession.startswith(("GDS", "GSM")):
            logger.debug(
                "GEO accession resolution decision accession=%r result=unsupported_prefix",
                accession,
            )
            return None

        uids = self._search(accession=accession)

        if not uids:
            logger.debug(
                "GEO accession resolution decision accession=%r result=no_uids",
                accession,
            )
            return None

        summaries = self._summary(uids=uids)
        summary = self._matching_summary(accession=accession, summaries=summaries)

        if summary is None:
            logger.debug(
                "GEO accession resolution decision accession=%r result=no_matching_summary uids=%s",
                accession,
                len(uids),
            )
            return None

        gse_accession = self._gse_from_summary(summary=summary)
        logger.debug(
            "GEO accession resolution decision accession=%r result=%r uids=%s",
            accession,
            gse_accession,
            len(uids),
        )
        return gse_accession

    def _search(self, accession: str) -> list[str]:
        params = self._params(
            {
                "db": "gds",
                "term": f"{accession}[ACCN]",
                "retmode": "json",
                "retmax": 20,
            }
        )
        logger.debug("GEO ESearch request accession=%r", accession)
        response = self._get(url=f"{self._base_url}/esearch.fcgi", params=params)
        uids = response.get("esearchresult", {}).get("idlist", [])
        logger.debug("GEO ESearch response accession=%r uid_count=%s", accession, len(uids))
        return uids

    def _summary(self, uids: list[str]) -> dict:
        params = self._params(
            {
                "db": "gds",
                "id": ",".join(uids),
                "retmode": "json",
            }
        )
        logger.debug("GEO ESummary request uid_count=%s", len(uids))
        return self._get(url=f"{self._base_url}/esummary.fcgi", params=params)

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(self._request_settings["max_retries"] + 1):
            started = time.monotonic()
            logger.debug(
                "GEO HTTP request endpoint=%s attempt=%s timeout=%s",
                url.rsplit("/", 1)[-1],
                attempt + 1,
                self._request_settings["timeout"],
            )
            response = requests.get(
                url,
                params=params,
                timeout=self._request_settings["timeout"],
            )

            if (
                response.status_code in self._retry_statuses
                and attempt < self._request_settings["max_retries"]
            ):
                retry_delay = self._retry_delay(response=response, attempt=attempt)
                logger.debug(
                    "GEO retry status=%s attempt=%s delay=%s",
                    response.status_code,
                    attempt + 1,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            response.raise_for_status()
            logger.debug(
                "GEO HTTP response endpoint=%s attempt=%s status=%s elapsed_seconds=%.3f",
                url.rsplit("/", 1)[-1],
                attempt + 1,
                response.status_code,
                time.monotonic() - started,
            )
            return response.json()

        return {}

    def _params(self, params: dict) -> dict:
        params = dict(params)

        if self._tool:
            params["tool"] = self._tool

        if self._email:
            params["email"] = self._email

        if self._api_key:
            params["api_key"] = self._api_key

        return params

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")

        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass

        return min(0.5 * (2 ** attempt), 8.0)

    def _matching_summary(self, accession: str, summaries: dict) -> dict | None:
        result = summaries.get("result", {})

        for uid in result.get("uids", []):
            summary = result.get(uid, {})

            if self._normalize_accession(summary.get("accession", "")) == accession:
                return summary

        return None

    def _gse_from_summary(self, summary: dict) -> str | None:
        for value in str(summary.get("gse", "")).split(";"):
            value = value.strip()

            if value:
                return self._normalize_accession(accession=f"GSE{value}")

        return None

    def _normalize_accession(self, accession: str) -> str:
        return str(accession or "").strip().upper()

    def _collect_gse_metadata_records(
        self,
        records: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        metadata_records = []
        packages_returned = 0
        related_records = 0
        error_records = 0
        unavailable_records = 0

        for index, record in enumerate(records, start=1):
            gse_accession = record.get("datalink_id", "")
            logger.info(
                "GEO metadata progress gse_index=%s gse_total=%s gse_accession=%s",
                index,
                len(records),
                gse_accession,
            )
            item_lock = (
                checkpoint_store.item_lock("geo_metadata", gse_accession)
                if checkpoint_store is not None
                else nullcontext()
            )
            with item_lock:
                checkpoint = (
                    checkpoint_store.get("geo_metadata", gse_accession)
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] in {
                    "available",
                    "no_data",
                    "terminal_error",
                }:
                    metadata_records.extend(
                        self._records_from_metadata_checkpoint(record, checkpoint)
                    )
                    continue

                try:
                    packages = self._gse_metadata_packages(gse_accession=gse_accession)
                except Exception as error:
                    error_records += 1
                    logger.warning(
                        "GEO metadata failed gse_accession=%s error_type=%s",
                        gse_accession,
                        type(error).__name__,
                    )
                    error_record = self._metadata_error_record(record=record)
                    metadata_records.append(error_record)
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            "geo_metadata",
                            gse_accession,
                            index,
                            "retryable_error"
                            if is_retryable_error(error)
                            else "terminal_error",
                            payload={"checkpoint_version": 2, "packages": []},
                            error=str(error),
                        )
                    continue

                if not packages:
                    unavailable_records += 1
                    metadata_records.append(self._metadata_unavailable_record(record=record))
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            "geo_metadata",
                            gse_accession,
                            index,
                            "no_data",
                            payload={"checkpoint_version": 2, "packages": []},
                        )
                    continue

                packages_returned += len(packages)
                package_records = self._metadata_records_from_packages(record, packages)
                related_records += sum(
                    item.get("datalink_id") != gse_accession for item in package_records
                )
                metadata_records.extend(package_records)
                if checkpoint_store is not None:
                    checkpoint_store.put(
                        "geo_metadata",
                        gse_accession,
                        index,
                        "available",
                        payload={"checkpoint_version": 2, "packages": packages},
                    )

        result = self._deduplicate_gse_jsons(jsons=metadata_records)
        logger.info(
            "GEO metadata stats source_gse_records=%s metadata_packages=%s related_records=%s error_records=%s unavailable_records=%s output_records=%s",
            len(records),
            packages_returned,
            related_records,
            error_records,
            unavailable_records,
            len(result),
        )
        return result

    def _metadata_records_from_packages(self, record: dict, packages: list[dict]) -> list[dict]:
        return [
            self._metadata_record(
                record=record,
                package=package,
                package_gse=self._package_gse_accession(package)
                or record.get("datalink_id", ""),
            )
            for package in packages
        ]

    def _records_from_metadata_checkpoint(self, record: dict, checkpoint: dict) -> list[dict]:
        payload = checkpoint.get("payload") or {}
        status = checkpoint.get("status")
        if "packages" in payload:
            packages = payload.get("packages") or []
            if status == "available" and packages:
                return self._metadata_records_from_packages(record, packages)
        elif status == "available":
            legacy_records = []
            for item in payload.get("records", []):
                package = item.get("accession_metadata")
                if not isinstance(package, (dict, list)):
                    continue
                legacy_records.append(
                    self._metadata_record(
                        record=record,
                        package=package,
                        package_gse=item.get("datalink_id")
                        or record.get("datalink_id", ""),
                    )
                )
            if legacy_records:
                return legacy_records
        if status == "no_data":
            return [self._metadata_unavailable_record(record)]
        return [self._metadata_error_record(record)]

    def _gse_metadata_packages(self, gse_accession: str) -> list[dict]:
        logger.debug("GEO geo2json request gse_accession=%s", gse_accession)
        return geo2json().convert(
            gse=gse_accession,
            related_series=True,
            remove_empty=True,
            enrich=True,
            out=None,
        )

    def _package_gse_accession(self, package: dict) -> str:
        series = package.get("series") or {}
        accessions = series.get("accession") or []

        if not isinstance(accessions, list):
            accessions = [accessions]

        for accession in accessions:
            if isinstance(accession, dict):
                accession = accession.get("value", "")

            value = self._normalize_accession(accession=accession)

            if value.startswith("GSE"):
                return value

        return ""

    def _metadata_record(self, record: dict, package: dict, package_gse: str) -> dict:
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

    def _metadata_error_record(self, record: dict) -> dict:
        return {
            **record,
            "metadata_repository": "geo",
            "metadata_source": "geo2json",
            "metadata_status": "error",
            "accession_metadata": None,
        }

    def _metadata_unavailable_record(self, record: dict) -> dict:
        return {
            **record,
            "metadata_repository": "geo",
            "metadata_source": "geo2json",
            "metadata_status": "unavailable",
            "accession_metadata": None,
        }

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
        duplicate_rows = 0
        publication_links = 0
        original_datalink_links = 0

        for record in jsons:
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
                original_datalink_key = self._original_datalink_key(
                    original_datalink=original_datalink
                )

                if original_datalink_key not in original_datalink_keys[gse_accession]:
                    original_datalink_keys[gse_accession].add(original_datalink_key)
                    target_record["original_datalinks"].append(original_datalink)
                    original_datalink_links += 1

            for publication in record.get("publications", []):
                publication_key = self._publication_key(publication=publication)

                if publication_key not in publication_keys[gse_accession]:
                    publication_keys[gse_accession].add(publication_key)
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
            "GEO GSE dedupe stats input_rows=%s output_rows=%s duplicate_rows_collapsed=%s publication_links=%s original_datalink_links=%s",
            len(jsons),
            len(records),
            duplicate_rows,
            publication_links,
            original_datalink_links,
        )
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
