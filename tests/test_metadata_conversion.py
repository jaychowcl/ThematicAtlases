"""Whole-study conversions are the only metadata recovery boundary."""
import pytest
from meta_standards_converter.converters.unified.contracts import ConversionBatchResult, ConversionItemResult
from meta_standards_converter.runtime_contracts import SafeErrorEnvelope, RetryCategory
from ThematicAtlases.runtime.checkpoint import CheckpointStore
from ThematicAtlases.integrations.conversion import MetadataConversionAdapter


def package(accession):
    return {"miniml_schema_version": "3.0", "source": {"format": "GEO MINiML"},
            "database": [], "organization": [], "contributor": [], "platform": [],
            "sample": [], "series": {"iid": accession, "accession": [{"value": accession}]}}


def outcome(*accessions, partial=False):
    return ConversionBatchResult([ConversionItemResult(
        "input_1", "GSE1", status="partial" if partial else "complete",
        execution="succeeded", completeness="partial" if partial else "complete",
        validation="valid", payload=[package(a) for a in accessions])])


class Converter:
    def __init__(self, *outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def convert(self, accession, **kwargs):
        self.calls.append((accession, kwargs))
        value = next(self.outcomes)
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.mark.parametrize("repository,accession", [("geo", "GSE1"), ("arrayexpress", "E-MTAB-1")])
def test_completed_conversion_reused_with_all_packages_and_current_provenance(tmp_path, repository, accession):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    converter = Converter(outcome(accession, "GSE2"))
    adapter = MetadataConversionAdapter(repository, converter=converter)
    record = {"datalink_id": accession, "publications": [{"pmid": "1"}]}
    first = adapter.collect([record], store)
    again = adapter.collect([{**record, "publications": [{"pmid": "2"}]}], store)
    assert len(first) == len(again) == 2
    assert all(r["publications"] == [{"pmid": "2"}] for r in again)
    assert len(converter.calls) == 1
    assert converter.calls[0][1]["enrichment"] == "standard"
    assert converter.calls[0][1]["options"]["expand_studies"] is True
    assert set(store.stage_status_counts()) == {"metadata_conversion"}


def test_partial_is_reused_and_failed_explicit_retry_retains_valid_payload(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    failure = ConversionBatchResult([ConversionItemResult("input_1", "GSE1", error=SafeErrorEnvelope(
        "Timeout", retry_category=RetryCategory.RETRYABLE))])
    converter = Converter(outcome("GSE1", partial=True), failure)
    adapter = MetadataConversionAdapter("geo", converter=converter)
    record = {"datalink_id": "GSE1", "publications": []}
    assert adapter.collect([record], store)[0]["metadata_status"] == "partial"
    adapter.collect([record], store)
    assert len(converter.calls) == 1
    store.request_retries(items={"metadata_conversion": ["geo:GSE1"]})
    result = adapter.collect([record], store)[0]
    assert result["metadata_status"] == "partial"
    assert result["accession_metadata"]["series"]["iid"] == "GSE1"
    assert store.get("metadata_conversion", "geo:GSE1")["status"] == "retryable_error"


def test_interrupted_conversion_repeats_only_unfinished_study(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    converter = Converter(outcome("GSE1"), KeyboardInterrupt(), outcome("GSE2"))
    adapter = MetadataConversionAdapter("geo", converter=converter)
    records = [{"datalink_id": a} for a in ("GSE1", "GSE2")]
    with pytest.raises(KeyboardInterrupt):
        adapter.collect(records, store)
    assert len(adapter.collect(records, store)) == 2
    assert [call[0] for call in converter.calls] == ["GSE1", "GSE2", "GSE2"]


def test_invalid_result_never_becomes_no_data(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.sqlite")
    failed = ConversionBatchResult([ConversionItemResult("input_1", "GSE1", validation="invalid")])
    result = MetadataConversionAdapter("geo", converter=Converter(failed)).collect([{"datalink_id": "GSE1"}], store)
    assert result[0]["metadata_status"] == "error"
    assert store.get("metadata_conversion", "geo:GSE1")["status"] == "terminal_error"


def test_failed_retry_of_partial_does_not_automatically_repeat(tmp_path):
    store=CheckpointStore(tmp_path/'state.sqlite')
    converter=Converter(outcome('GSE1',partial=True),TimeoutError('wait'))
    adapter=MetadataConversionAdapter('geo',converter=converter)
    record={'datalink_id':'GSE1'}
    adapter.collect([record],store)
    store.request_retries(items={'metadata_conversion':['geo:GSE1']})
    adapter.collect([record],store)
    assert adapter.collect([record],store)[0]['metadata_status']=='partial'
    assert len(converter.calls)==2


def test_incomplete_empty_conversion_is_not_no_data(tmp_path):
    store=CheckpointStore(tmp_path/'state.sqlite')
    result=MetadataConversionAdapter('geo',converter=Converter(outcome(partial=True))).collect([{'datalink_id':'GSE1'}],store)
    assert result[0]['metadata_status']=='error'


def test_collector_rejects_retired_tags_even_without_geo_handler():
    from ThematicAtlases.collector import AtlasCollector
    with pytest.raises(ValueError,match='metadata_conversion'):
        AtlasCollector(metadata_handlers={}).collect_accession_metadata([],retry_tags={})


def test_transport_outcome_persists_error_identity_and_cooldown(tmp_path):
    import time
    retry_at = time.time() + 60
    failure = ConversionBatchResult([ConversionItemResult('input_1', 'GSE1', retry_at=retry_at,
        error=SafeErrorEnvelope('ProviderCooldown', retry_category=RetryCategory.RETRYABLE))])
    converter = Converter(failure)
    store = CheckpointStore(tmp_path/'state.sqlite')
    adapter = MetadataConversionAdapter('geo', converter=converter)
    adapter.collect([{'datalink_id':'GSE1'}], store)
    saved = store.get('metadata_conversion', 'geo:GSE1')
    assert saved['error_type'] == 'ProviderCooldown'
    assert saved['failure_category'] == 'transient'
    assert saved['payload']['next_retry_at'] == retry_at
    adapter.collect([{'datalink_id':'GSE1'}], store)
    assert len(converter.calls) == 1


def test_related_packages_keep_their_repository_and_originating_publications():
    from ThematicAtlases.harmonizer import AtlasHarmonizer
    record = {'datalink_id':'E-MTAB-1', 'accession_repository':'arrayexpress', 'publications':[{'pmid':'1'}]}
    result = MetadataConversionAdapter('arrayexpress', converter=Converter(outcome('E-MTAB-1','GSE2'))).collect([record])
    assert [r['metadata_repository'] for r in result] == ['arrayexpress','geo']
    assert [r['accession_repository'] for r in result] == ['arrayexpress','geo']
    assert all(r['publications'] == record['publications'] for r in result)
    assert all(AtlasHarmonizer()._eligibility_reason(r) is None for r in result)
    assert result[1]['source_datalink_id'] == 'E-MTAB-1'
