"""ArrayExpress delegates scientific conversion through the unified contract."""
import pytest
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper
from meta_standards_converter.runtime_contracts import get_resource_profile
from meta_standards_converter.sources.contracts import RequestMetrics
from test_metadata_conversion import Converter, outcome


@pytest.mark.parametrize('wrapper_type,accession', [(GEOWrapper,'GSE1'),(ArrayExpressWrapper,'E-MTAB-1')])
def test_unified_adapter_defaults_limits_metrics_and_offline_reuse(tmp_path,wrapper_type,accession):
    class MeasuredConverter(Converter):
        def metrics(self): return RequestMetrics(2*len(self.calls),len(self.calls),.5*len(self.calls))
    converter=MeasuredConverter(outcome(accession))
    profile=get_resource_profile('standard',overrides={'max_xml_bytes':4096,'network_workers':2})
    wrapper=wrapper_type(converter=converter, resource_profile=profile)
    store=CheckpointStore(tmp_path/'store.sqlite')
    first=wrapper.collect_accession_metadata([{'datalink_id':accession,'publications':[{'pmid':'1'}]}],store)
    second=wrapper.collect_accession_metadata([{'datalink_id':accession,'publications':[{'pmid':'2'}]}],store)
    assert first[0]['accession_metadata']==second[0]['accession_metadata']
    assert second[0]['publications']==[{'pmid':'2'}]
    assert second[0]['metadata_source']=='msc.convert'
    assert converter.calls[0][1]['out_type']=='json'
    assert converter.calls[0][1]['enrichment']=='standard'
    options=converter.calls[0][1]['options']
    assert options['expand_studies']
    assert options['resource_overrides']['max_xml_bytes']==4096
    assert options['resource_overrides']['network_workers']==2
    assert (wrapper.provider_attempts,wrapper.retry_count,wrapper.rate_wait_seconds)==(2,1,.5)
    assert len(converter.calls)==1


def test_arrayexpress_isolates_failed_and_successful_empty_outcomes():
    converter=Converter(ValueError('invalid'),outcome())
    result=ArrayExpressWrapper(converter=converter).collect_accession_metadata([
        {'datalink_id':'E-MTAB-1'},{'datalink_id':'E-MTAB-2'}])
    assert [item['metadata_status'] for item in result]==['error','unavailable']


def test_retired_source_injection_explains_converter_replacement():
    with pytest.raises(ValueError,match='converter='):
        ArrayExpressWrapper(source_resolver=object())
