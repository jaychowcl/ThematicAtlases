import hashlib
import json
from pathlib import Path
import pytest
from ThematicAtlases.runtime.trace import DevTraceWriter
from ThematicAtlases.pipeline import validate_stop_after


def file_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_legacy_trace_is_rejected_before_any_write(tmp_path):
    run = tmp_path / 'old'
    run.mkdir()
    (run / '00_run_manifest.json').write_text(json.dumps({'run_id': 'old'}))
    (run / 'atlas_run.sqlite3').write_bytes(b'untouched old state')
    before = file_hashes(tmp_path)
    with pytest.raises(ValueError, match='migration'):
        DevTraceWriter.existing(run)
    assert file_hashes(tmp_path) == before


def test_new_trace_has_contract_and_optional_debug_snapshots(tmp_path):
    trace = DevTraceWriter(str(tmp_path), 'new', {})
    assert json.loads((trace.directory / '00_run_manifest.json').read_text())['workflow_checkpoint_contract'] == '2.0'
    trace.write('01_collected_accessions.json', [{'datalink_id': 'GSE1'}])
    assert not (trace.directory / '01_collected_accessions.json').exists()
    debug = DevTraceWriter(str(tmp_path), 'debug', {'debug_snapshots': True})
    debug.write('01_collected_accessions.json', [])
    assert (debug.directory / '01_collected_accessions.json').exists()


def test_text_pause_alias_has_one_canonical_boundary():
    assert validate_stop_after('fulltext-accessions') == 'publication-text'


def test_position_is_a_single_run_ledger_record(tmp_path):
    trace = DevTraceWriter(str(tmp_path), 'new', {})
    store = trace.checkpoint_store
    store.set_meta('pipeline_position', {'phase': 'datalinks'})
    store.set_meta('pipeline_position', {'stage': 'query-results', 'state': 'running'})
    assert trace.run_store.metadata('new', 'pipeline_position') == {
        'phase': 'datalinks', 'stage': 'query-results', 'state': 'running'}
    with store._connection() as conn:
        assert conn.execute("select count(*) from checkpoint_meta where key='pipeline_position'").fetchone()[0] == 0


@pytest.mark.parametrize('operation',['resume','worker','metadata','review','fork','checkpoint','ledger'])
def test_all_writable_entrypoints_reject_legacy_trace_without_mutation(tmp_path,operation):
    from ThematicAtlases.atlas import Atlas
    from ThematicAtlases.stage_worker import TraceStageWorker
    from ThematicAtlases.collector import AtlasCollector
    from ThematicAtlases.filterer import PublicationTextReviewer
    from ThematicAtlases.runtime.checkpoint import CheckpointStore
    from ThematicAtlases.runtime.run_store import AtlasRunStore
    directory=tmp_path/'old'
    directory.mkdir()
    (directory/'00_run_manifest.json').write_text(json.dumps({'theme':'test','run_id':'old'}))
    (directory/'atlas_run.sqlite3').write_bytes(b'legacy database')
    (directory/'01_collected_accessions.json').write_text('[{"datalink_id":"GSE1"}]')
    before=file_hashes(tmp_path)
    actions={
        'resume':lambda:Atlas({}).resume(dev_out_dir=str(tmp_path),run_id='old'),
        'worker':lambda:TraceStageWorker().resume(directory,stage='text'),
        'metadata':lambda:AtlasCollector().resume_metadata(str(directory)),
        'review':lambda:PublicationTextReviewer().resume(directory),
        'fork':lambda:Atlas({}).fork_run(dev_out_dir=str(tmp_path),run_id='old',new_run_id='new'),
        'checkpoint':lambda:CheckpointStore(directory/'atlas_run.sqlite3'),
        'ledger':lambda:AtlasRunStore(directory/'atlas_run.sqlite3')}
    with pytest.raises(ValueError,match='migration'):
        actions[operation]()
    assert file_hashes(tmp_path)==before
