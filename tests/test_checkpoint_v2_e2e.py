"""Offline acceptance with real TA stages and controlled remote boundaries."""
from pathlib import Path
import json
import pytest
from ThematicAtlases.atlas import Atlas
from ThematicAtlases.integrations.europe_pmc import EuropePMCWrapper
from ThematicAtlases.integrations.geo import GEOWrapper
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.runtime.views import CheckpointViews
from test_metadata_conversion import Converter, outcome
from test_system_e2e import SUCCESS_STATUS


class EmptyGraph:
    def discover(self, publications, checkpoint_store=None, cached_only=False, **kwargs):
        if checkpoint_store is not None and not cached_only:
            for p in publications:
                if not checkpoint_store.get('pubmed_gds_links', p['pmid']):
                    checkpoint_store.put('pubmed_gds_links',p['pmid'],0,'no_data',payload={'target_uids':[]})
        return []


class EPMC(EuropePMCWrapper):
    def __init__(self, *, empty=False):
        super().__init__(request_delay=0, link_graph_provider=EmptyGraph())
        self.calls=[]
        self.empty=empty
    def _search(self,query,cursor):
        self.calls.append('search')
        return {'hitCount':0 if self.empty else 1,'resultList':{'result':[] if self.empty else [
            {'id':'1','source':'MED','pmid':'1','pmcid':'PMC1','title':'Fibrosis','abstractText':'GSE1'}]}}
    def _datalinks(self,source,epmc_id):
        self.calls.append('datalinks')
        return {}
    def _full_text_xml(self,epmc_id):
        self.calls.append('text')
        return '<article><body><p>Fibrosis GSE1</p></body></article>'


class Reviewer:
    def __init__(self): self.calls=0
    def review_relevancy(self,**kwargs):
        self.calls+=1
        return {'strategy':kwargs['strategy'],'judgement':'relevant','evidences':['Fibrosis'],
            'reasoning':'Study','confidence':'high','accessions_to_remove':[]}


class Harmonizer:
    def __init__(self): self.calls=0
    def harmonize_miniml_json(self,**kwargs):
        self.calls+=1
        return {'contract_version':'2.0','status':SUCCESS_STATUS,'miniml_json':kwargs['miniml_json']}


class Credentials:
    def check(self): pass


def components(*, partial=False, empty=False):
    epmc=EPMC(empty=empty)
    converter=Converter(outcome('GSE1',partial=partial))
    reviewer=Reviewer()
    harmonizer=Harmonizer()
    atlas=Atlas(metadata={}, epmc_wrapper_factory=lambda:epmc,
        metadata_handlers={'geo':lambda:GEOWrapper(converter=converter)},
        credential_checker=Credentials(),
        publication_text_reviewer=PublicationTextReviewer(reviewer_factory=lambda:reviewer),
        harmonizer=AtlasHarmonizer(ontology_harmonizer=harmonizer,credential_checker=Credentials()))
    return atlas,epmc,converter,reviewer,harmonizer


@pytest.mark.parametrize('review_first,partial,empty',[(False,False,False),(True,False,False),(False,True,False),(False,False,True)])
def test_resume_without_debug_snapshots_reuses_completed_work(tmp_path,review_first,partial,empty):
    atlas,epmc,converter,reviewer,harmonizer=components(partial=partial,empty=empty)
    original=atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
        review_before_metadata=review_first, dev_trace=True,dev_out_dir=str(tmp_path))
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    assert not (directory/'01_collected_accessions.json').exists()
    calls=(list(epmc.calls),len(converter.calls),reviewer.calls,harmonizer.calls)
    resumed=atlas.resume(dev_out_dir=str(tmp_path),run_id=directory.name)
    assert (epmc.calls,len(converter.calls),reviewer.calls,harmonizer.calls)==calls
    assert resumed['datasets']==original['datasets']
    assert resumed['publications']==original['publications']
    assert resumed['run']['status']==('partial' if partial else 'complete')
    assert len(CheckpointViews.from_directory(directory).metadata())==(0 if empty else 1)


def test_interrupted_publication_reuses_completed_stages(tmp_path,monkeypatch):
    atlas,epmc,converter,reviewer,harmonizer=components()
    original_write = __import__('ThematicAtlases.runtime.trace',fromlist=['DevTraceWriter']).DevTraceWriter.write
    from ThematicAtlases.runtime.trace import DevTraceWriter
    def interrupt(self,name,value):
        if name=='06_final_atlas.json': raise KeyboardInterrupt()
        return original_write(self,name,value)
    monkeypatch.setattr(DevTraceWriter,'write',interrupt)
    with pytest.raises(KeyboardInterrupt):
        atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
            dev_trace=True,dev_out_dir=str(tmp_path))
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    calls=(list(epmc.calls),len(converter.calls),reviewer.calls,harmonizer.calls)
    monkeypatch.setattr(DevTraceWriter,'write',original_write)
    result=atlas.resume(dev_out_dir=str(tmp_path),run_id=directory.name)
    assert (epmc.calls,len(converter.calls),reviewer.calls,harmonizer.calls)==calls
    assert result['run']['status']=='complete'


@pytest.mark.parametrize('root_name',['trace','runs'])
def test_create_and_worker_resolve_the_same_run_and_combined_text_boundary(tmp_path,root_name):
    from ThematicAtlases.cli.atlas import main
    from ThematicAtlases.stage_worker import TraceStageWorker
    atlas,epmc,*_=components()
    root=tmp_path/root_name
    atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
        dev_trace=True,dev_out_dir=str(root),stop_after='datalinks')
    directory=next(root.iterdir())
    worker=TraceStageWorker(epmc_wrapper_factory=lambda:epmc)
    args=['worker-snapshot','--dev-out-dir',str(root),'--run-id',directory.name,'--stage','text']
    assert main(args,worker_factory=lambda:worker)==0
    saved=CheckpointViews.from_directory(directory).store.get('publication_text','MED:1')
    assert saved['payload']['extraction_complete']
    assert saved['payload']['records'][0]['datalink_id']=='GSE1'
    calls=list(epmc.calls)
    assert main(args,worker_factory=lambda:worker)==0
    assert epmc.calls==calls


@pytest.mark.parametrize('pause',['publication-text','fulltext-accessions'])
def test_text_pause_names_have_the_same_completed_boundary(tmp_path,pause):
    atlas,epmc,*_=components()
    atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
        dev_trace=True,dev_out_dir=str(tmp_path),stop_after=pause)
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    view=CheckpointViews.from_directory(directory)
    assert view.store.get_meta('pipeline_position')['stage']=='publication-text'
    assert view.store.get('publication_text','MED:1')['payload']['extraction_complete']
    assert not view.store.items('fulltext_accession_discovery')


def test_metadata_fork_and_independent_continuation_use_sqlite(tmp_path):
    atlas,epmc,converter,*_=components()
    atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
        dev_trace=True,dev_out_dir=str(tmp_path),stop_after='metadata')
    source=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    from test_checkpoint_contract_v2 import file_hashes
    before=file_hashes(source)
    fork=atlas.fork_run(dev_out_dir=str(tmp_path),run_id=source.name,new_run_id='fork',overrides={'theme':'new theme'})
    assert {name: file_hashes(source)[name] for name in before} == before
    assert not (fork/'01_collected_accessions.json').exists()
    assert CheckpointViews.from_directory(fork).metadata()[0]['datalink_id']=='GSE1'
    independent=atlas._collector.resume_metadata(str(fork))
    assert independent['accessions'][0]['metadata_status']=='available'
    assert len(converter.calls)==1
    resumed=atlas.resume(dev_out_dir=str(tmp_path),run_id='fork')
    assert resumed['datasets'][0]['dataset_id']=='GSE1'
    assert len(converter.calls)==1


def test_disabled_extraction_does_not_block_review_frontier(tmp_path):
    from ThematicAtlases.runtime.trace import DevTraceWriter
    from ThematicAtlases.stage_worker import TraceStageWorker
    trace=DevTraceWriter(str(tmp_path),'run',{'scrape_fulltext_accessions':False})
    store=trace.checkpoint_store
    publication={'source':'MED','epmc_id':'1','pmid':'1'}
    store.put('pubmed_gds_links','1',0,'no_data',payload={'target_uids':[]})
    assert TraceStageWorker._review_discovery_terminal(store,publication)


def test_empty_search_pause_resume_does_not_repeat_search(tmp_path):
    atlas,epmc,*_=components(empty=True)
    atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
        dev_trace=True,dev_out_dir=str(tmp_path),stop_after='query-results')
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    atlas.resume(dev_out_dir=str(tmp_path),run_id=directory.name)
    assert epmc.calls==['search']


@pytest.mark.parametrize('review_first',[False,True])
def test_reconstructed_filtering_and_pruning_match_uninterrupted_execution(tmp_path,review_first):
    atlas,epmc,converter,reviewer,_=components()
    epmc._full_text_xml=lambda epmc_id:'<article><body><p>Fibrosis GSE1 and GSE2</p></body></article>'
    converter.outcomes=iter([outcome('GSE1'),outcome('GSE2')])
    original_review=reviewer.review_relevancy
    reviewer.review_relevancy=lambda **kw:{**original_review(**kw),
        'accessions_to_remove':[{'accession':'GSE2','reason':'out of scope'}]}
    original=atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
        review_filter='not_relevant',prune_accessions=True,review_before_metadata=review_first,
        dev_trace=True,dev_out_dir=str(tmp_path))
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    view=CheckpointViews.from_directory(directory)
    datasets,details=view.harmonization()
    assert [r['datalink_id'] for r in datasets['accessions']]==['GSE1']
    assert datasets['accessions'][0]['ontology_harmonization_run_status']=='completed'
    assert datasets['accessions'][0]['accession_metadata']==original['datasets'][0]['metadata']
    calls=(len(converter.calls),reviewer.calls)
    resumed=atlas.resume(dev_out_dir=str(tmp_path),run_id=directory.name)
    assert resumed['datasets']==original['datasets']
    assert (len(converter.calls),reviewer.calls)==calls
    assert len(converter.calls)==(1 if review_first else 2)


def test_trace_reading_benchmarks_use_sqlite_without_stage_json(tmp_path):
    atlas,*_=components()
    atlas.create_atlas(query=['fibrosis'],theme='fibrosis',generate_queries=False,
        dev_trace=True,dev_out_dir=str(tmp_path))
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    from benchmark_ThematicAtlases.benchmark_fibrosis_meta_pubs_recall.benchmark_fibrosis_meta_pubs_recall import _load_trace
    from benchmark_ThematicAtlases.benchmark_fibrosis_meta_pubs_query_recall.benchmark_fibrosis_meta_pubs_query_recall import _load_query_snapshot
    result,source=_load_trace(directory)
    assert result['accessions'][0]['datalink_id']=='GSE1'
    assert source['artifact'].endswith('atlas_run.sqlite3')
    assert _load_query_snapshot(directory)['publications'][0]['pmid']=='1'


@pytest.mark.parametrize('scenario', ['default', 'review_first', 'partial', 'empty', 'interrupted_publication'])
def test_checkpoint_v2_golden_offline_workflows(tmp_path, monkeypatch, scenario):
    golden = json.loads((Path(__file__).parent/'fixtures/contracts/checkpoint-v2-workflows.json').read_text())
    expected = golden['scenarios'][scenario]
    atlas, epmc, converter, reviewer, harmonizer = components(
        partial=scenario == 'partial', empty=scenario == 'empty')
    options = dict(query=['fibrosis'], theme='fibrosis', generate_queries=False,
                   review_before_metadata=scenario == 'review_first',
                   dev_trace=True, dev_out_dir=str(tmp_path))
    from ThematicAtlases.runtime.trace import DevTraceWriter
    original_write = DevTraceWriter.write
    if scenario == 'interrupted_publication':
        def interrupt(self, name, value):
            if name == '06_final_atlas.json':
                raise KeyboardInterrupt()
            return original_write(self, name, value)
        monkeypatch.setattr(DevTraceWriter, 'write', interrupt)
        with pytest.raises(KeyboardInterrupt):
            atlas.create_atlas(**options)
        monkeypatch.setattr(DevTraceWriter, 'write', original_write)
    else:
        atlas.create_atlas(**options)
    directory = next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    result = atlas.resume(dev_out_dir=str(tmp_path), run_id=directory.name)
    actual = {
        'document': {key: result[key] for key in ('datasets', 'publications')},
        'status': result['run']['status'],
        'calls': {'epmc': epmc.calls, 'conversion': len(converter.calls),
                  'review': reviewer.calls, 'harmonization': harmonizer.calls},
        'items': {stage: sorted(item['status'] for item in CheckpointViews.from_directory(directory).store.items(stage))
                  for stage in expected['items']},
    }
    assert actual == {**expected, 'document': golden['documents'][expected['document']]}
