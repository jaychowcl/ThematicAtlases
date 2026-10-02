"""Only unresolved, structured provider failures enable automatic partial retries."""
import json
import time

import pytest

from meta_standards_converter.converters.unified.contracts import Diagnostic
from meta_standards_converter.provider_issues import ProviderIssue
from meta_standards_converter.runtime_contracts import SafeErrorEnvelope, RetryCategory
from ThematicAtlases.integrations.conversion import MetadataConversionAdapter
from ThematicAtlases.runtime.checkpoint import CheckpointStore
from test_metadata_conversion import Converter, outcome


def partial(*, retry_at=None, recovered=False):
    result = outcome('GSE1', partial=True)
    result.items[0].diagnostics.append(Diagnostic(
        'provider_recovered' if recovered else 'source_partial', 'human wording may change',
        provider_issue=ProviderIssue('provider_response_invalid', 'study_resolution',
            SafeErrorEnvelope('JSONDecodeError', provider='ena', retry_category=RetryCategory.RETRYABLE), retry_at)))
    return result


def test_ordinary_resume_recovers_published_partial_without_explicit_selection(tmp_path):
    from test_checkpoint_v2_e2e import components
    from ThematicAtlases.runtime.views import CheckpointViews
    atlas, epmc, converter, reviewer, harmonizer = components()
    converter.outcomes = iter([partial(), outcome('GSE1')])
    first = atlas.create_atlas(query=['fibrosis'], theme='fibrosis', generate_queries=False,
        dev_trace=True, dev_out_dir=str(tmp_path))
    directory = next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').exists())
    store = CheckpointStore(directory/'atlas_run.sqlite3')
    assert store.retry_report()['automatic_retry_count'] == 1
    second = atlas.resume(dev_out_dir=str(tmp_path))
    assert len(converter.calls) == 2
    assert first['run']['status'] == 'partial'
    assert second['run']['status'] == 'complete'
    assert store.retry_report()['automatic_retry_count'] == 0
    assert store.history('metadata_conversion', 'geo:GSE1')


@pytest.mark.parametrize('cooling,recovered', [(True,False),(False,True)])
def test_cooldowns_and_recovered_issues_are_not_retried(tmp_path, cooling, recovered):
    from ThematicAtlases.runtime.metadata_recovery import metadata_retry_scope
    store = CheckpointStore(tmp_path/'state.sqlite')
    converter = Converter(partial(retry_at=time.time()+300 if cooling else None, recovered=recovered))
    adapter = MetadataConversionAdapter('geo', converter=converter)
    adapter.collect([{'datalink_id':'GSE1'}], store)
    with metadata_retry_scope(store):
        adapter.collect([{'datalink_id':'GSE1'}], store)
    assert len(converter.calls) == 1


def test_failed_retry_keeps_package_and_latest_structured_cause(tmp_path):
    from ThematicAtlases.runtime.metadata_recovery import metadata_retry_scope, retryable_provider_issues
    failed = partial()
    failed.items[0].execution = 'failed'
    failed.items[0].payload = None
    failed.items[0].error = failed.items[0].diagnostics[0].provider_issue.error
    store = CheckpointStore(tmp_path/'state.sqlite')
    converter = Converter(partial(), failed, outcome('GSE1'))
    adapter = MetadataConversionAdapter('geo', converter=converter)
    records = [{'datalink_id':'GSE1'}]
    adapter.collect(records, store)
    with metadata_retry_scope(store):
        assert adapter.collect(records, store)[0]['accession_metadata']
    assert retryable_provider_issues(store.get('metadata_conversion','geo:GSE1'))
    with metadata_retry_scope(store):
        assert adapter.collect(records, store)[0]['metadata_status'] == 'available'
    assert len(converter.calls) == 3


def test_once_per_resume_and_latest_terminal_failure_clears_eligibility(tmp_path):
    from ThematicAtlases.runtime.metadata_recovery import metadata_retry_scope, retryable_provider_issues
    store = CheckpointStore(tmp_path/'state.sqlite')
    failed = outcome()
    failed.items[0].execution = 'failed'
    failed.items[0].error = SafeErrorEnvelope('InvalidInput', retry_category=RetryCategory.TERMINAL)
    converter = Converter(partial(), partial(), failed)
    adapter = MetadataConversionAdapter('geo', converter=converter)
    records = [{'datalink_id':'GSE1'}]*2
    adapter.collect(records, store)
    with metadata_retry_scope(store):
        adapter.collect(records, store)
        adapter.collect(records, store)
    assert len(converter.calls) == 2
    with metadata_retry_scope(store):
        final = adapter.collect(records, store)
    assert len(converter.calls) == 3
    assert final[0]['accession_metadata']
    assert retryable_provider_issues(store.get('metadata_conversion', 'geo:GSE1')) == []
    with metadata_retry_scope(store):
        adapter.collect(records, store)
    assert len(converter.calls) == 3


def test_manual_and_automatic_selection_do_not_double_convert(tmp_path):
    from ThematicAtlases.runtime.metadata_recovery import metadata_retry_scope
    store = CheckpointStore(tmp_path/'state.sqlite')
    converter = Converter(partial(), outcome('GSE1'))
    adapter = MetadataConversionAdapter('geo', converter=converter)
    adapter.collect([{'datalink_id':'GSE1'}], store)
    store.request_retries(items={'metadata_conversion':['geo:GSE1']})
    with metadata_retry_scope(store):
        adapter.collect([{'datalink_id':'GSE1'}]*2, store)
    assert len(converter.calls) == 2


def test_newer_attempt_wins_over_stale_resume_selection(tmp_path):
    from ThematicAtlases.runtime.metadata_recovery import metadata_retry_scope
    store = CheckpointStore(tmp_path/'state.sqlite')
    converter = Converter(partial())
    adapter = MetadataConversionAdapter('geo', converter=converter)
    adapter.collect([{'datalink_id':'GSE1'}], store)
    with metadata_retry_scope(store):
        row = store.get('metadata_conversion','geo:GSE1')
        row['payload']['attempt_id'] = 'another-worker-finished'
        store.put('metadata_conversion','geo:GSE1',0,'available',payload=row['payload'])
        adapter.collect([{'datalink_id':'GSE1'}], store)
    assert len(converter.calls) == 1
