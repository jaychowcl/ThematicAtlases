"""Supported operations on one run; storage layout stays behind this boundary."""
from __future__ import annotations
from collections.abc import Mapping
from meta_standards_converter.runtime_contracts import SafeErrorEnvelope


class AtlasRunManager:
    def __init__(self, trace):
        self._trace = trace

    @property
    def run_id(self) -> str:
        return self._trace.directory.name

    def request_retries(self, *, stages=(), items=None, degraded_stages=()) -> int:
        return self._trace.checkpoint_store.request_retries(
            stages=stages, items=items, degraded_stages=degraded_stages,
        )

    def stage_status_counts(self) -> dict[str, dict[str, int]]:
        return self._trace.checkpoint_store.stage_status_counts()

    def record_event(self, event_type: str, *, stage=None, work_item_id=None, detail: Mapping | None = None) -> int:
        return self._trace.run_store.record_event(
            self.run_id, event_type, stage=stage, work_item_id=work_item_id, detail=detail,
        )

    def mark_failed(self, error: Exception, *, provider: str = 'thematic_atlas') -> None:
        """Mark the run failed without discarding resumable item evidence."""
        trace = self._trace
        trace.write('08_retry_report.json', trace.checkpoint_store.retry_report())
        trace.register_artifact('retry_report', '08_retry_report.json')
        trace.run_store.set_stage_state(self.run_id, 'workflow', 'failed')
        trace.run_store.set_run_status(self.run_id, 'failed')
        safe_error = SafeErrorEnvelope.from_exception(
            error, provider=provider, stage='workflow', item_id=self.run_id,
        )
        self.record_event('run_failed', detail=safe_error.to_dict())
