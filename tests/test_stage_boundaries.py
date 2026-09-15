from ThematicAtlases.collector import AtlasCollector


def test_metadata_stage_preserves_input_order_across_repository_batches():
    from ThematicAtlases.stages.metadata import MetadataStage, MetadataRequest
    calls = []
    class Handler:
        def collect_accession_metadata(self, jsons, checkpoint_store=None):
            calls.append([row['datalink_id'] for row in jsons])
            return [{**row, 'metadata_status': 'available'} for row in jsons]
    collector = AtlasCollector(metadata_handlers={'geo': Handler, 'arrayexpress': Handler})
    rows = [
        {'datalink_id': 'GSE1', 'datalink_id_scheme': 'geo'},
        {'datalink_id': 'E-MTAB-1', 'datalink_id_scheme': 'arrayexpress'},
        {'datalink_id': 'GSE2', 'datalink_id_scheme': 'geo'},
    ]
    result = MetadataStage(collector).run(MetadataRequest(jsons=rows))
    assert [row['datalink_id'] for row in result.records] == ['GSE1','E-MTAB-1','GSE2']
    assert calls == [['GSE1','GSE2'],['E-MTAB-1']]
    assert all('_atlas_discovery_ordinal' not in row for row in result.records)
    assert all('metadata_status' not in row for row in rows)


def test_publication_text_stage_reuses_embedded_evidence_without_provider():
    from ThematicAtlases.filterer import AtlasFilterer
    from ThematicAtlases.stages.text import PublicationTextStage, PublicationTextRequest
    def forbidden():
        raise AssertionError('embedded evidence must not trigger retrieval')
    filterer = AtlasFilterer(epmc_wrapper_factory=forbidden)
    result = PublicationTextStage(filterer).run(PublicationTextRequest(jsons=[{
        'publications': [{'source':'MED','epmc_id':'1','text':'body','text_source':'abstract','full_text_status':'unavailable'}]
    }]))
    assert len(result.publication_texts) == 1
    assert next(iter(result.publication_texts.values()))['text'] == 'body'
