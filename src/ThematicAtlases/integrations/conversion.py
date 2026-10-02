"""One MSC conversion, and one durable outcome, per requested study."""
from contextlib import nullcontext
from dataclasses import asdict
from functools import lru_cache
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time
from uuid import uuid4
from ThematicAtlases.runtime.metadata_recovery import current_retry_scope, retry_at

from meta_standards_converter.converters import Converter
from meta_standards_converter.runtime_contracts import ResourceProfile, get_resource_profile
from meta_standards_converter.sources.contracts import request_metrics
from ThematicAtlases.miniml_boundary import checkpoint_packages, checkpoint_payload
from ThematicAtlases.runtime.checkpoint import is_retryable_error
from ThematicAtlases.runtime_contracts import safe_error_mapping
from ThematicAtlases.repository_capabilities import RepositoryCapabilityRegistry

STAGE = "metadata_conversion"


@lru_cache(maxsize=1)
def conversion_identity():
    import meta_standards_converter
    root = Path(meta_standards_converter.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return {"version": version("meta-standards-converter"), "source_sha256": digest.hexdigest()}


class MetadataConversionAdapter:
    def __init__(self, repository, *, converter=None, resource_profile="standard", enrichment="standard"):
        self.repository = repository
        self.converter = converter if converter is not None else Converter()
        self.profile = resource_profile if isinstance(resource_profile, ResourceProfile) else get_resource_profile(resource_profile)
        self.settings = {"out_type": "json", "enrichment": enrichment, "expand_studies": True,
                         "resource_profile": asdict(self.profile), "msc": conversion_identity()}
        self.input_hash = hashlib.sha256(json.dumps(self.settings, sort_keys=True).encode()).hexdigest()

    def metrics(self):
        return request_metrics(self.converter)

    def collect(self, records, store=None, *, cached_only=False):
        result = []
        for ordinal, record in enumerate(records):
            accession = str(record.get("datalink_id") or "").strip().upper()
            key = f"{self.repository}:{accession}"
            with store.item_lock(STAGE, key) if store is not None and not cached_only else nullcontext():
                saved = store.get(STAGE, key) if store is not None else None
                payload = (saved or {}).get("payload") or {}
                compatible = payload.get("input_hash") == self.input_hash
                usable = compatible and bool(checkpoint_packages(payload))
                scope = current_retry_scope(store)
                automatic = bool(scope and compatible and scope.allows(key, saved))
                reusable = compatible and (saved["status"] in {"available", "no_data", "terminal_error"}
                    or (usable and saved.get("error_type") != "ManualRetry"))
                cooling = compatible and retry_at(saved) > time.time()
                already_attempted = bool(scope and (key in scope.attempted or (saved and scope.stale(key, saved))))
                if cached_only or (reusable and not automatic) or cooling or already_attempted:
                    result.extend(self.records(record, saved if compatible else None))
                    continue
                previous = payload if compatible and checkpoint_packages(payload) else None
                if scope:
                    scope.attempted.add(key)
                trigger = 'provider_recovery' if automatic and saved.get('error_type') != 'ManualRetry' else 'manual' if saved and saved.get('error_type') == 'ManualRetry' else 'collection'
                try:
                    profile = asdict(self.profile)
                    profile_name = profile.pop("name")
                    batch = self.converter.convert(accession, out_type="json", enrichment=self.settings["enrichment"],
                        options={"expand_studies": True, "resource_profile": profile_name, "resource_overrides": profile})
                    if len(batch.items) != 1:
                        raise ValueError("one study conversion must return exactly one input outcome")
                    outcome = batch.items[0]
                    success = outcome.execution == "succeeded" and outcome.validation == "valid" and (bool(outcome.payload) or outcome.completeness == "complete")
                    if success:
                        payload = checkpoint_payload(outcome.payload or [], checkpoint_version=1,
                            input_hash=self.input_hash, settings=self.settings, outcome=outcome.to_dict(),
                            provenance={"accession": accession, "publications": [
                                {k: v for k, v in publication.items() if k not in {"text", "full_text_links"}}
                                for publication in record.get("publications", [])],
                                "original_datalinks": record.get("original_datalinks", [])})
                        status = "available" if payload["packages"] else "no_data"
                        error = None
                    else:
                        error = outcome.error.to_dict() if outcome.error else {"error_type": "InvalidConversionOutcome", "retry_category": "terminal"}
                        payload = dict(previous or checkpoint_payload([], checkpoint_version=1))
                        payload.pop('next_retry_at', None)
                        payload.update(input_hash=self.input_hash, settings=self.settings, last_failure=outcome.to_dict())
                        if outcome.retry_at is not None:
                            payload["next_retry_at"] = outcome.retry_at
                        status = "retryable_error" if error.get("retry_category") == "retryable" else "terminal_error"
                except Exception as exc:
                    error = safe_error_mapping(exc, provider="meta_standards_converter", stage=STAGE,
                                               item_id=key, retryable=is_retryable_error(exc))
                    payload = dict(previous or checkpoint_payload([], checkpoint_version=1))
                    payload.pop('next_retry_at', None)
                    payload.update(input_hash=self.input_hash, settings=self.settings, last_failure={"error": error})
                    if getattr(exc, "retry_at", None) is not None:
                        payload["next_retry_at"] = float(exc.retry_at)
                    status = "retryable_error" if is_retryable_error(exc) else "terminal_error"
                payload.update(attempt_id=uuid4().hex, retry_trigger=trigger)
                saved = {"status": status, "payload": payload, "error": error}
                if store is not None:
                    store.put(STAGE, key, ordinal, status, payload=payload,
                              error=json.dumps(error) if error else None,
                              error_type=error.get("error_type") if error else None,
                              failure_category=("transient" if status == "retryable_error" else "permanent") if error else None)
                result.extend(self.records(record, saved))
        return result

    def records(self, record, saved):
        """Attach current discovery provenance; it is never cached with metadata."""
        payload = (saved or {}).get("payload") or {}
        packages = checkpoint_packages(payload) or []
        base = {**record, "metadata_repository": self.repository, "metadata_source": "msc.convert"}
        if packages:
            partial = saved["status"] != "available" or payload.get("outcome", {}).get("completeness") != "complete"
            records = []
            for package in packages:
                series = package.get("series") or {}
                identities = series.get("accession") or []
                if isinstance(identities, dict):
                    identities = [identities]
                accession = next((str(item.get("value")) for item in identities if isinstance(item, dict) and item.get("value")), series.get("iid") or record.get("datalink_id"))
                try:
                    repository = RepositoryCapabilityRegistry().for_accession(accession).repository_id
                except ValueError:
                    repository = self.repository
                item = {**base, "datalink_id": accession, "accession_metadata": package,
                        "accession_repository": repository, "metadata_repository": repository,
                        "metadata_status": "partial" if partial else "available",
                        "metadata_conversion": {k: v for k, v in payload.items() if k != "packages"}}
                if accession != record.get("datalink_id"):
                    item["source_datalink_id"] = record.get("datalink_id")
                records.append(item)
            return records
        state = (saved or {}).get("status")
        return [{**base, "accession_metadata": None,
                 "metadata_status": "unavailable" if state == "no_data" else "pending" if saved is None else "error",
                 "metadata_conversion": {k: v for k, v in payload.items() if k != "packages"}}]
