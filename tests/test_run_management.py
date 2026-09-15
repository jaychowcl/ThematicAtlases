import json
from ThematicAtlases.trace import DevTraceWriter


def trace(tmp_path):
    return DevTraceWriter(root=str(tmp_path), run_id='run-1', manifest={'command':'create-atlas','atlas_id':'atlas-1'})


def test_run_manager_retries_only_requested_items_and_preserves_available_data(tmp_path):
    writer = trace(tmp_path)
    store = writer.checkpoint_store
    store.put('search_queries','a',0,'terminal_error',error='failed')
    store.put('search_queries','b',1,'available',payload={'rows':[]})
    available = store.get('search_queries','b')
    assert writer.manager.request_retries(items={'search_queries':['a']}) == 1
    assert store.get('search_queries','a')['status'] == 'retryable_error'
    assert store.get('search_queries','b') == available
    assert writer.manager.stage_status_counts()['search_queries']['available'] == 1


def test_run_manager_failure_writes_report_and_preserves_item_checkpoints(tmp_path):
    writer = trace(tmp_path)
    writer.checkpoint_store.put('search_queries','a',0,'available',payload={'rows':[]})
    before = writer.checkpoint_store.get('search_queries','a')
    writer.manager.mark_failed(ValueError('problem'), provider='test-runner')
    assert writer.run_store.get_run('run-1')['status'] == 'failed'
    assert writer.checkpoint_store.get('search_queries','a') == before
    assert json.loads((writer.directory/'08_retry_report.json').read_text()) == writer.checkpoint_store.retry_report()
    assert writer.run_store.artifact('run-1','retry_report') is not None


def test_read_only_snapshot_reads_coherent_rows_without_creating_store(tmp_path):
    from ThematicAtlases.runtime.snapshots import read_checkpoint_snapshot
    writer = trace(tmp_path)
    writer.checkpoint_store.set_meta('resolved_queries',['a'])
    writer.checkpoint_store.put('search_queries','a',0,'available',payload={'rows':[]})
    result = read_checkpoint_snapshot(writer.directory, stages=('search_queries',))
    assert json.loads(result.metadata['resolved_queries']) == ['a']
    assert result.items[0]['item_key'] == 'a'
    assert result.items[0]['status'] == 'available'
    import pytest
    with pytest.raises(FileNotFoundError):
        read_checkpoint_snapshot(tmp_path/'missing',stages=())
    assert not (tmp_path/'missing').exists()
