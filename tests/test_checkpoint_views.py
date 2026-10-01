import json
import pytest
from ThematicAtlases.runtime.trace import DevTraceWriter
from ThematicAtlases.runtime.views import CheckpointViews
from ThematicAtlases.integrations.conversion import MetadataConversionAdapter
from test_metadata_conversion import Converter, outcome


def test_sqlite_reconstruction_retains_expanded_packages_and_publication_provenance(tmp_path, monkeypatch):
    trace = DevTraceWriter(str(tmp_path), 'run', {})
    store = trace.checkpoint_store
    publication = {'source':'MED', 'epmc_id':'1', 'pmid':'1'}
    record = {'datalink_id':'GSE1', 'accession_repository':'geo', 'publications':[publication]}
    store.put('search_pages', 'page', 1, 'available', payload={'publications':[publication]})
    store.put('publication_text', 'MED:1', 1, 'available', payload={
        'publication':{**publication, 'text':'GSE1', 'text_source':'abstract', 'full_text_status':'unavailable'},
        'records':[record], 'extraction_complete':True, 'extraction_enabled':True})
    MetadataConversionAdapter('geo', converter=Converter(outcome('GSE1','GSE2',partial=True))).collect([record],store)
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', lambda *a, **k: pytest.fail('reconstruction made a network call'))
    before = (trace.directory/'atlas_run.sqlite3').read_bytes()
    first = CheckpointViews.from_directory(trace.directory).metadata()
    second = CheckpointViews.from_directory(trace.directory).metadata()
    assert first == second
    assert [r['datalink_id'] for r in first] == ['GSE1','GSE2']
    assert all(all(r['publications'][0][key]==value for key,value in publication.items()) and r['metadata_status']=='partial' for r in first)
    assert (trace.directory/'atlas_run.sqlite3').read_bytes()==before
    assert not (trace.directory/'01_collected_accessions.json').exists()


def test_review_view_resolves_text_and_rejects_stale_text_reference(tmp_path):
    trace=DevTraceWriter(str(tmp_path),'run',{})
    store=trace.checkpoint_store
    from ThematicAtlases.runtime.evidence import reference_text
    ref=reference_text(store,'1',{'text':'first'})
    store.put('thematic_review','direct:1',0,'available',payload={
        'publication_ref':'1','text_ref':ref,'review':{'theme':'test','review_status':'completed'}})
    assert CheckpointViews(store).publication_texts()['1']['agentic_curator']['theme']=='test'
    reference_text(store,'1',{'text':'changed'})
    assert 'agentic_curator' not in CheckpointViews(store).publication_texts()['1']


@pytest.mark.parametrize('fails', [False, True])
def test_harmonization_reconstruction_preserves_all_outcomes(tmp_path, fails):
    from test_checkpoint_v2_e2e import Harmonizer, Credentials
    from test_metadata_conversion import package
    from ThematicAtlases.harmonizer import AtlasHarmonizer
    provider = Harmonizer()
    if fails:
        def fail(**kwargs):
            raise ValueError('controlled failure')
        provider.harmonize_miniml_json = fail
    owner = AtlasHarmonizer(ontology_harmonizer=provider, credential_checker=Credentials())
    trace = DevTraceWriter(str(tmp_path), 'run', {})
    datasets = {'accessions': [
        {'datalink_id': 'GSE1', 'accession_metadata': package('GSE1')},
        {'datalink_id': 'GSE2', 'accession_metadata': None},
    ], 'publication_texts': {}}
    expected, expected_details = owner.harmonize_datasets(datasets, checkpoint_store=trace.checkpoint_store)
    actual, details = CheckpointViews.from_directory(trace.directory).harmonization(datasets=datasets)
    assert actual == expected
    assert details == expected_details
    if fails:
        repeated, _ = owner.harmonize_datasets(datasets, checkpoint_store=trace.checkpoint_store)
        assert repeated == expected


def test_review_reconstruction_drops_decision_when_metadata_input_changes(tmp_path):
    from test_checkpoint_v2_e2e import components
    atlas, *_ = components()
    atlas.create_atlas(query=['fibrosis'], theme='fibrosis', generate_queries=False,
                       dev_trace=True, dev_out_dir=str(tmp_path))
    directory = next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    views = CheckpointViews.from_directory(directory)
    records = views.metadata()
    assert 'agentic_curator' in views.review(accessions=records)['publication_texts']['1']
    records[0]['accession_metadata']['series']['title'] = 'Changed metadata'
    assert 'agentic_curator' not in views.review(accessions=records)['publication_texts']['1']


@pytest.mark.parametrize('workflows', [('first', 'second'), ('second', 'first')])
def test_harmonization_view_selects_latest_matching_input(tmp_path, workflows):
    from test_checkpoint_v2_e2e import Harmonizer, Credentials
    from test_metadata_conversion import package
    from test_system_e2e import SUCCESS_STATUS
    from ThematicAtlases.harmonizer import AtlasHarmonizer
    from copy import deepcopy
    class RevisionHarmonizer(Harmonizer):
        def harmonize_miniml_json(self, **kwargs):
            metadata = deepcopy(kwargs['miniml_json'])
            metadata['series']['title'] = kwargs['workflow']
            return {'contract_version':'2.0', 'status':SUCCESS_STATUS, 'miniml_json':metadata}
    owner = AtlasHarmonizer(ontology_harmonizer=RevisionHarmonizer(), credential_checker=Credentials())
    trace = DevTraceWriter(str(tmp_path), 'run', {})
    datasets = {'accessions':[{'datalink_id':'GSE1', 'accession_metadata':package('GSE1')}], 'publication_texts':{}}
    owner.harmonize_datasets(datasets, harmonization_options={'workflow':workflows[0]}, checkpoint_store=trace.checkpoint_store)
    expected, expected_details = owner.harmonize_datasets(datasets, harmonization_options={'workflow':workflows[1]}, checkpoint_store=trace.checkpoint_store)
    actual, details = CheckpointViews.from_directory(trace.directory).harmonization(datasets=datasets)
    assert actual == expected
    assert details == expected_details
