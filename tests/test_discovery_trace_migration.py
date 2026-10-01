import pytest
from test_checkpoint_contract_v2 import file_hashes
from ThematicAtlases.discovery_trace_migration import migrate_pre_graph_discovery_trace


def test_legacy_graph_migration_is_deferred_without_touching_source(tmp_path):
    source=tmp_path/'legacy'
    source.mkdir()
    (source/'00_run_manifest.json').write_text('{}')
    (source/'atlas_run.sqlite3').write_bytes(b'old database bytes')
    before=file_hashes(tmp_path)
    with pytest.raises(ValueError,match='migration.*deferred'):
        migrate_pre_graph_discovery_trace(dev_out_dir=str(tmp_path),run_id='legacy',new_run_id='new')
    assert file_hashes(tmp_path)==before
