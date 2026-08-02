from __future__ import annotations

import logging
from contextlib import nullcontext

from meta_standards_converter.converters.ae2json import ae2json

from ThematicAtlases.checkpoint import is_retryable_error


logger = logging.getLogger(__name__)


class ArrayExpressWrapper:
    """Collect ArrayExpress/BioStudies MAGE-TAB through MSC in memory."""

    metadata_handler_status = "supported"
    STAGE = "arrayexpress_metadata"
    PREFIXES = ("E-MTAB-", "E-GEOD-", "E-MEXP-")

    def __init__(self, converter_factory=None):
        self._converter_factory = converter_factory or ae2json

    def collect_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        records = []
        for index, record in enumerate(jsons, start=1):
            accession = self._normalize_accession(record.get("datalink_id"))
            if not accession:
                records.append(self._error_record(record))
                continue
            item_lock = (
                checkpoint_store.item_lock(self.STAGE, accession)
                if checkpoint_store is not None
                else nullcontext()
            )
            with item_lock:
                checkpoint = (
                    checkpoint_store.get(self.STAGE, accession)
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] in {
                    "available", "no_data", "terminal_error"
                }:
                    records.append(self._record_from_checkpoint(record, checkpoint))
                    continue
                try:
                    packages = self._converter_factory().convert(
                        source=accession,
                        out=None,
                        sdrf_sources=None,
                    )
                except Exception as error:
                    logger.warning(
                        "ArrayExpress metadata failed accession=%s error_type=%s",
                        accession,
                        type(error).__name__,
                    )
                    status = (
                        "retryable_error" if is_retryable_error(error)
                        else "terminal_error"
                    )
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            self.STAGE,
                            accession,
                            index,
                            status,
                            payload={"checkpoint_version": 1, "packages": []},
                            error=str(error),
                        )
                    records.append(self._error_record(record))
                    continue
                package = next(
                    (item for item in packages if isinstance(item, dict)), None
                )
                status = "available" if package is not None else "no_data"
                payload = {
                    "checkpoint_version": 1,
                    "packages": [package] if package is not None else [],
                }
                if checkpoint_store is not None:
                    checkpoint_store.put(
                        self.STAGE, accession, index, status, payload=payload
                    )
                records.append(
                    self._available_record(record, package)
                    if package is not None
                    else self._unavailable_record(record)
                )
        return records

    def available_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store,
    ) -> list[dict]:
        records = []
        for record in jsons:
            accession = self._normalize_accession(record.get("datalink_id"))
            checkpoint = checkpoint_store.get(self.STAGE, accession) if accession else None
            if checkpoint and checkpoint["status"] in {
                "available", "no_data", "terminal_error"
            }:
                records.append(self._record_from_checkpoint(record, checkpoint))
            else:
                records.append(self._pending_record(record))
        return records

    def _record_from_checkpoint(self, record: dict, checkpoint: dict) -> dict:
        status = checkpoint.get("status")
        package = next(
            (
                item for item in (checkpoint.get("payload") or {}).get("packages", [])
                if isinstance(item, dict)
            ),
            None,
        )
        if status == "available" and package is not None:
            return self._available_record(record, package)
        if status == "no_data":
            return self._unavailable_record(record)
        return self._error_record(record)

    @classmethod
    def _normalize_accession(cls, value) -> str:
        accession = str(value or "").strip().upper()
        return accession if accession.startswith(cls.PREFIXES) else ""

    @staticmethod
    def _base_record(record: dict) -> dict:
        return {
            **record,
            "metadata_repository": "arrayexpress",
            "metadata_source": "ae2json",
        }

    def _available_record(self, record: dict, package: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "available",
            "accession_metadata": package,
        }

    def _unavailable_record(self, record: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "unavailable",
            "accession_metadata": None,
        }

    def _error_record(self, record: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "error",
            "accession_metadata": None,
        }

    def _pending_record(self, record: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "pending",
            "accession_metadata": None,
        }
