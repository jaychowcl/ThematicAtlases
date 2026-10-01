"""GEO identity resolution followed by a whole MSC conversion."""
import logging
import time
import requests
from contextlib import nullcontext
from weakref import WeakKeyDictionary
from meta_standards_converter.helpers.request_helper import NCBIApplicationIdentity
from meta_standards_converter.runtime_contracts import ResourceProfile, get_resource_profile
from ThematicAtlases.infrastructure.http import RequestPolicy
from ThematicAtlases.runtime.checkpoint import is_retryable_error
from ThematicAtlases.runtime_contracts import safe_error_json
from ThematicAtlases.wrappers.geo_records import GEORecordPolicy
from ThematicAtlases.integrations.conversion import MetadataConversionAdapter

logger = logging.getLogger("ThematicAtlases.wrappers.geo")


class GEOWrapper:
    metadata_handler_status = "supported"
    def __init__(
        self,
        api_key: str | None = None,
        tool: str = "ThematicAtlases",
        email: str | None = None,
        timeout: int | float | tuple[int | float, int | float] | None = None,
        request_delay: float = 0.5,
        max_retries: int = 3,
        request_policy: RequestPolicy | None = None,
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides=None,
        record_policy: GEORecordPolicy | None = None,
        enrich_metadata: bool = True,
        converter=None,
    ):
        self.resource_profile = (
            resource_profile.with_overrides(resource_overrides)
            if isinstance(resource_profile, ResourceProfile) and resource_overrides
            else resource_profile
            if isinstance(resource_profile, ResourceProfile)
            else get_resource_profile(
                resource_profile,
                overrides=resource_overrides,
            )
        )
        effective_timeout = timeout or (
            self.resource_profile.connect_timeout_seconds,
            self.resource_profile.read_timeout_seconds,
        )
        identity_options = {"tool": tool, "email": email}
        if api_key is not None:
            identity_options["api_key"] = api_key
        self._ncbi_identity = NCBIApplicationIdentity(**identity_options)
        self._request_settings = {
            "timeout": effective_timeout,
            "request_delay": request_delay,
            "max_retries": max_retries,
        }
        self._base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self._retry_statuses = {403, 429, 500, 502, 503, 504}
        self.provider_attempts = 0
        self.retry_count = 0
        self.rate_wait_seconds = 0.0
        self._request_metric_snapshots = WeakKeyDictionary()
        self._request_policy = request_policy or RequestPolicy(
            timeout=effective_timeout,
            max_retries=max_retries,
            retry_statuses=self._retry_statuses,
            sleep=time.sleep,
            logger=logger,
            name="GEO",
            resource_profile=self.resource_profile,
        )
        self._record_policy = record_policy or GEORecordPolicy()
        self._enrich_metadata = bool(enrich_metadata)

        self._conversion = MetadataConversionAdapter("geo", converter=converter, resource_profile=self.resource_profile, enrichment="standard" if enrich_metadata else "off")

    def _resolve_records(self, jsons, checkpoint_store=None, *, cached_only=False):
        records = []
        for index, record in enumerate(jsons):
            accession = self._normalize_accession(record.get("datalink_id"))
            if accession.startswith("GSE"):
                records.append(self._gse_record(record, accession))
                continue
            if not accession.startswith(("GSM", "GDS")):
                continue
            with checkpoint_store.item_lock("geo_resolution", accession) if checkpoint_store is not None and not cached_only else nullcontext():
                saved = checkpoint_store.get("geo_resolution", accession) if checkpoint_store is not None else None
                if saved and (saved["status"] == "terminal_error" or (saved["status"] == "retryable_error" and (cached_only or (saved.get("payload") or {}).get("next_retry_at", 0) > time.time()))):
                    records.append({**record, "metadata_repository":"geo", "metadata_status":"error" if saved["status"] == "terminal_error" else "pending", "accession_metadata":None})
                    continue
                if saved and saved["status"] in {"available", "no_data"}:
                    gse = (saved.get("payload") or {}).get("gse_accession")
                elif cached_only:
                    records.append({**record, "metadata_repository": "geo", "metadata_status": "pending", "accession_metadata": None})
                    continue
                else:
                    try:
                        gse = self.get_gse(accession)
                    except Exception as error:
                        if checkpoint_store is not None:
                            retry_at = getattr(error, "retry_at", None)
                            checkpoint_store.put("geo_resolution", accession, index,
                                "retryable_error" if is_retryable_error(error) else "terminal_error",
                                payload={"next_retry_at": retry_at} if retry_at else None,
                                error=safe_error_json(error, provider="NCBI GEO", stage="geo_resolution", item_id=accession, retryable=is_retryable_error(error)))
                        raise
                    if checkpoint_store is not None:
                        checkpoint_store.put("geo_resolution", accession, index, "available" if gse else "no_data", payload={"gse_accession": gse})
                if gse:
                    records.append(self._gse_record(record, gse))
        return self._deduplicate_gse_jsons(records)

    def collect_accession_metadata(self, jsons, checkpoint_store=None, retry_tags=None):
        if retry_tags is not None:
            raise ValueError("identifier retry tags are retired; retry metadata_conversion for the study")
        logger.info("GEO metadata progress stage=resolve-accessions input_records=%s", len(jsons))
        records = self._resolve_records(jsons, checkpoint_store)
        logger.info("GEO metadata stats resolved_records=%s dropped_records=%s", len(records), len(jsons)-len(records))
        ready = [r for r in records if str(r.get("datalink_id", "")).startswith("GSE")]
        pending = [r for r in records if r not in ready]
        logger.info("GEO metadata progress stage=collect-gse-metadata gse_records=%s", len(ready))
        try:
            result = self._deduplicate_gse_jsons(self._conversion.collect(ready, checkpoint_store)) + pending
            logger.info("GEO metadata stats output_records=%s", len(result))
            return result
        finally:
            self._accumulate_request_metrics(self._conversion)

    def available_accession_metadata(self, jsons, checkpoint_store):
        records = self._resolve_records(jsons, checkpoint_store, cached_only=True)
        ready = [r for r in records if str(r.get("datalink_id", "")).startswith("GSE")]
        pending = [r for r in records if r not in ready]
        return self._deduplicate_gse_jsons(self._conversion.collect(ready, checkpoint_store, cached_only=True)) + pending

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
        started = time.monotonic()
        logger.debug(
            "GEO HTTP request endpoint=%s timeout=%s",
            url.rsplit("/", 1)[-1],
            self._request_settings["timeout"],
        )
        try:
            response = self._request_policy.get(url, params=params)
        finally:
            self._accumulate_request_metrics(self._request_policy)
        logger.debug(
            "GEO HTTP response endpoint=%s status=%s elapsed_seconds=%.3f",
            url.rsplit("/", 1)[-1],
            response.status_code,
            time.monotonic() - started,
        )
        return response.json()


    def _params(self, params: dict) -> dict:
        params = dict(params)

        params.update(self._ncbi_identity.params())

        return params


    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        return RequestPolicy.retry_delay(response, attempt)


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


    def _accumulate_request_metrics(self, *providers) -> None:
        """Accumulate explicit service snapshots without inspecting their internals."""
        from meta_standards_converter.sources.contracts import request_metrics
        for provider in {id(p): p for p in providers if p is not None}.values():
            current_metrics = request_metrics(provider)
            current = (current_metrics.provider_attempts, current_metrics.retry_count,
                       current_metrics.rate_wait_seconds)
            previous = self._request_metric_snapshots.get(provider, (0, 0, 0.0))
            self.provider_attempts += max(current[0] - previous[0], 0)
            self.retry_count += max(current[1] - previous[1], 0)
            self.rate_wait_seconds += max(current[2] - previous[2], 0.0)
            self._request_metric_snapshots[provider] = current


    def _package_gse_accession(self, package: dict) -> str:
        return self._record_policy.package_gse_accession(package)


    def _metadata_record(self, record: dict, package: dict, package_gse: str) -> dict:
        return self._record_policy.metadata_record(record, package, package_gse)


    def _metadata_error_record(self, record: dict) -> dict:
        return self._record_policy.metadata_error_record(record)


    def _metadata_unavailable_record(self, record: dict) -> dict:
        return self._record_policy.metadata_unavailable_record(record)


    def _gse_record(self, record: dict, gse_accession: str) -> dict:
        return self._record_policy.gse_record(record, gse_accession)


    def _deduplicate_gse_jsons(self, jsons: list[dict]) -> list[dict]:
        return self._record_policy.deduplicate_gse_jsons(jsons)


    def _original_datalink_key(self, original_datalink: dict) -> tuple:
        return self._record_policy.original_datalink_key(original_datalink)


    def _publication_key(self, publication: dict) -> tuple:
        return self._record_policy.publication_key(publication)
