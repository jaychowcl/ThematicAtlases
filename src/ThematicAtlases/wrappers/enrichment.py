from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from meta_standards_converter.insdc_handlers.insdc_webfetcher import INSDCWebfetcher
from meta_standards_converter.pubmed_handlers.pubmed_webfetcher import PubmedWebFetcher

from ThematicAtlases.checkpoint import is_retryable_error


logger = logging.getLogger(__name__)

PUBMED_FIELDS = (
    "doi",
    "author_list",
    "title",
    "status",
    "status_term_source_ref",
    "status_term_accession_number",
)
SRA_PATTERN = re.compile(r"^[SED]R[RXSP]\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class RetryTags:
    tag_id: str
    pubmed: tuple[str, ...] = ()
    sra: tuple[str, ...] = ()
    ena: tuple[str, ...] = ()

    def normalized_dict(self) -> dict:
        return {
            "tag_id": self.tag_id,
            "pubmed": list(self.pubmed),
            "sra": list(self.sra),
            "ena": list(self.ena),
        }

    def digest(self) -> str:
        encoded = json.dumps(
            self.normalized_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _dedupe(values, *, normalize=lambda value: value) -> tuple[str, ...]:
    result = []
    for value in values:
        normalized = normalize(str(value).strip())
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


def load_retry_tags(path: str | Path) -> RetryTags:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("retry tags must be a JSON object")
    allowed = {"tag_id", "pubmed", "sra", "ena"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown retry tag keys: {', '.join(unknown)}")
    tag_id = str(value.get("tag_id") or "").strip()
    if not tag_id:
        raise ValueError("tag_id must be a non-empty string")
    for key in ("pubmed", "sra", "ena"):
        if not isinstance(value.get(key, []), list):
            raise ValueError(f"{key} must be a JSON array")
    pubmed = _dedupe(value.get("pubmed", []))
    if any(not item.isdigit() for item in pubmed):
        raise ValueError("PubMed identifiers must contain digits only")
    sra = _dedupe(value.get("sra", []), normalize=str.upper)
    ena = _dedupe(value.get("ena", []), normalize=str.upper)
    if any(SRA_PATTERN.fullmatch(item) is None for item in (*sra, *ena)):
        raise ValueError("SRA and ENA identifiers must be valid INSDC accessions")
    return RetryTags(tag_id=tag_id, pubmed=pubmed, sra=sra, ena=ena)


def _applied_tags(payload) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return list(payload.get("applied_retry_tags") or [])


def _with_tag(payload: dict, tag_id: str | None) -> dict:
    payload = dict(payload)
    tags = _applied_tags(payload)
    if tag_id and tag_id not in tags:
        tags.append(tag_id)
    if tags:
        payload["applied_retry_tags"] = tags
    return payload


class CheckpointedPubmedFetcher:
    stage = "pubmed_enrichment"

    def __init__(
        self,
        checkpoint_store,
        *,
        fetcher=None,
        forced_identifiers=(),
        tag_id: str | None = None,
    ):
        self.store = checkpoint_store
        self.fetcher = fetcher or PubmedWebFetcher()
        self.forced_identifiers = {str(item).strip() for item in forced_identifiers}
        self.tag_id = tag_id

    def pubmed_summary(self, pubmed_id: str) -> tuple:
        identifier = str(pubmed_id).strip()
        with self.store.item_lock(self.stage, identifier):
            item = self.store.get(self.stage, identifier)
            forced = identifier in self.forced_identifiers
            tag_applied = bool(
                self.tag_id and self.tag_id in _applied_tags((item or {}).get("payload"))
            )
            if item and (not forced or tag_applied):
                if item["status"] == "available":
                    summary = (item.get("payload") or {}).get("summary") or {}
                    return tuple(summary.get(field) for field in PUBMED_FIELDS)
                if item["status"] in {"no_data", "terminal_error"} or tag_applied:
                    return (None,) * len(PUBMED_FIELDS)

            try:
                result = tuple(self.fetcher.pubmed_summary(pubmed_id=identifier))
            except Exception as error:
                payload = _with_tag({}, self.tag_id if forced else None)
                self.store.put(
                    self.stage,
                    identifier,
                    0,
                    "retryable_error" if is_retryable_error(error) else "terminal_error",
                    payload=payload,
                    error=str(error),
                )
                raise

            summary = dict(zip(PUBMED_FIELDS, result))
            payload = _with_tag({"summary": summary}, self.tag_id if forced else None)
            status = "available" if any(result) else "no_data"
            self.store.put(self.stage, identifier, 0, status, payload=payload)
            return result


class CheckpointedINSDCFetcher(INSDCWebfetcher):
    def __init__(
        self,
        checkpoint_store,
        *,
        fetcher=None,
        forced_sra=(),
        forced_ena=(),
        ena_identifiers=None,
        tag_id: str | None = None,
    ):
        super().__init__()
        self.store = checkpoint_store
        self.fetcher = fetcher or INSDCWebfetcher()
        self.forced_sra = {str(item).strip().upper() for item in forced_sra}
        self.forced_ena = {str(item).strip().upper() for item in forced_ena}
        self.ena_identifiers = (
            None
            if ena_identifiers is None
            else {str(item).strip().upper() for item in ena_identifiers}
        )
        self.tag_id = tag_id

    def fetch_ena_fastq_files(self, accession: str) -> dict:
        identifier = str(accession).strip().upper()
        if self.ena_identifiers is not None and identifier not in self.ena_identifiers:
            return {}
        return super().fetch_ena_fastq_files(accession=identifier)

    def _ncbi_nrx(self, nrx: str):
        identifier = str(nrx).strip().upper()
        return self._checkpointed_xml(identifier)

    def _checkpointed_xml(self, identifier: str):
        stage = "sra_xml"
        with self.store.item_lock(stage, identifier):
            item = self.store.get(stage, identifier)
            forced = identifier in self.forced_sra
            tag_applied = bool(
                self.tag_id and self.tag_id in _applied_tags((item or {}).get("payload"))
            )
            if item and (not forced or tag_applied):
                if item["status"] in {"available", "no_data"}:
                    return ET.fromstring((item.get("payload") or {}).get("xml") or "<root/>")
                if item["status"] == "terminal_error" or tag_applied:
                    return ET.fromstring("<root/>")
            try:
                root = self.fetcher._ncbi_nrx(nrx=identifier)
            except Exception as error:
                self.store.put(
                    stage,
                    identifier,
                    0,
                    "retryable_error" if is_retryable_error(error) else "terminal_error",
                    payload=_with_tag({}, self.tag_id if forced else None),
                    error=str(error),
                )
                raise
            xml = ET.tostring(root, encoding="unicode")
            status = "available" if root.findall(".//EXPERIMENT_PACKAGE") else "no_data"
            self.store.put(
                stage,
                identifier,
                0,
                status,
                payload=_with_tag({"xml": xml}, self.tag_id if forced else None),
            )
            return root

    def fetch_ena_file_report(self, accession: str) -> list:
        identifier = str(accession).strip().upper()
        stage = "ena_fastq"
        with self.store.item_lock(stage, identifier):
            item = self.store.get(stage, identifier)
            forced = identifier in self.forced_ena
            tag_applied = bool(
                self.tag_id and self.tag_id in _applied_tags((item or {}).get("payload"))
            )
            if item and (not forced or tag_applied):
                if item["status"] == "available":
                    return list((item.get("payload") or {}).get("rows") or [])
                if item["status"] in {"no_data", "terminal_error"} or tag_applied:
                    return []
            try:
                rows = self.fetcher.fetch_ena_file_report(accession=identifier)
            except Exception as error:
                self.store.put(
                    stage,
                    identifier,
                    0,
                    "retryable_error" if is_retryable_error(error) else "terminal_error",
                    payload=_with_tag({}, self.tag_id if forced else None),
                    error=str(error),
                )
                raise
            rows = rows if isinstance(rows, list) else []
            self.store.put(
                stage,
                identifier,
                0,
                "available" if rows else "no_data",
                payload=_with_tag({"rows": rows}, self.tag_id if forced else None),
            )
            return rows


class EnrichmentAuditor:
    def audit(self, checkpoint_store) -> dict:
        candidates = []
        geo_rows = 0
        packages_seen = 0
        for item in checkpoint_store.items("geo_metadata"):
            if item["status"] != "available":
                continue
            payload = item.get("payload") or {}
            if payload.get("enrichment_mode") == "all":
                continue
            geo_rows += 1
            packages = self._packages(payload)
            for package_index, package in enumerate(packages):
                if not isinstance(package, dict):
                    continue
                packages_seen += 1
                package_accession = self._package_accession(package) or item["key"]
                self._audit_pubmed(
                    candidates, item["key"], package_index, package_accession, package
                )
                self._audit_samples(
                    candidates, item["key"], package_index, package_accession, package
                )
        order = {"pubmed": 0, "sra": 1, "ena": 2}
        candidates.sort(
            key=lambda value: (
                order[value["kind"]],
                value["gse"],
                value["package_index"],
                value["sample_path"] or "",
                value["identifier"],
            )
        )
        counts = {kind: sum(c["kind"] == kind for c in candidates) for kind in order}
        counts["total"] = len(candidates)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": {"legacy_geo_rows": geo_rows, "packages": packages_seen},
            "counts": counts,
            "candidates": candidates,
        }

    @staticmethod
    def _packages(payload: dict) -> list:
        if "packages" in payload:
            return list(payload.get("packages") or [])
        return [
            record.get("accession_metadata")
            for record in payload.get("records", [])
            if isinstance(record, dict)
            and isinstance(record.get("accession_metadata"), dict)
        ]

    @staticmethod
    def _as_list(value) -> list:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _package_accession(self, package: dict) -> str:
        series = package.get("series") if isinstance(package.get("series"), dict) else {}
        for accession in self._as_list(series.get("accession")):
            value = accession.get("value") if isinstance(accession, dict) else accession
            value = str(value or "").strip().upper()
            if value.startswith("GSE"):
                return value
        return ""

    def _base(self, kind, gse, package_index, package_accession, sample_path, identifier, reason):
        return {
            "kind": kind,
            "gse": gse,
            "package_index": package_index,
            "package_accession": package_accession,
            "sample_path": sample_path,
            "identifier": identifier,
            "reason": reason,
        }

    def _audit_pubmed(self, result, gse, package_index, package_accession, package):
        series = package.get("series") if isinstance(package.get("series"), dict) else {}
        for publication in self._as_list(series.get("pubmed_publication")):
            if not isinstance(publication, dict) or not publication.get("pubmed_id"):
                continue
            if all(publication.get(field) is None for field in PUBMED_FIELDS):
                result.append(
                    self._base(
                        "pubmed", gse, package_index, package_accession, None,
                        str(publication["pubmed_id"]), "all_enrichment_fields_null",
                    )
                )

    def _audit_samples(self, result, gse, package_index, package_accession, package):
        for sample_index, sample in enumerate(self._as_list(package.get("sample"))):
            if not isinstance(sample, dict):
                continue
            sample_path = f"/sample/{sample_index}"
            accessions = [str(v).strip().upper() for v in self._as_list(sample.get("sra_accession")) if v]
            runs = [v for v in self._as_list(sample.get("sra_run")) if isinstance(v, dict)]
            if accessions and not runs:
                for identifier in accessions:
                    result.append(
                        self._base(
                            "sra", gse, package_index, package_accession, sample_path,
                            identifier, "sra_accession_without_runs",
                        )
                    )
            if accessions and runs:
                affected = [str(run.get("run")) for run in runs if not run.get("fastq_files") and run.get("run")]
                if affected:
                    for identifier in accessions:
                        candidate = self._base(
                            "ena", gse, package_index, package_accession, sample_path,
                            identifier, "run_without_ena_fastq",
                        )
                        candidate["affected_run_ids"] = affected
                        result.append(candidate)
