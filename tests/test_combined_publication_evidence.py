from ThematicAtlases.runtime.checkpoint import CheckpointStore
from ThematicAtlases.integrations.europe_pmc import EuropePMCWrapper
from ThematicAtlases.filterer.review import PublicationTextReviewer


def test_text_and_accessions_are_one_reusable_outcome(tmp_path, monkeypatch):
    store = CheckpointStore(tmp_path / 'state.sqlite')
    wrapper = EuropePMCWrapper(request_delay=0)
    monkeypatch.setattr(wrapper, '_preprint_full_text', lambda publication: None)
    pub = {'source': 'MED', 'epmc_id': '1', 'pmid': '1', 'abstractText': 'Data deposited as GSE123.'}
    wrapper.collect_publication_texts([pub], checkpoint_store=store)
    payload = store.get('publication_text', 'MED:1')['payload']
    assert payload['extraction_complete']
    assert payload['records'][0]['datalink_id'] == 'GSE123'
    assert 'text' not in payload['records'][0]['publications'][0]
    assert not store.items('fulltext_accession_discovery')
    monkeypatch.setattr(wrapper, '_preprint_full_text', lambda publication: (_ for _ in ()).throw(AssertionError('no repeat download')))
    wrapper.collect_publication_texts([pub], checkpoint_store=store)


def test_review_checkpoint_references_text_and_reuses_decision(tmp_path):
    store = CheckpointStore(tmp_path / 'state.sqlite')
    class Reviewer:
        calls = 0
        def review_relevancy(self, **kwargs):
            self.calls += 1
            return {'judgement': 'relevant', 'reason': 'matches'}
    reviewer = Reviewer()
    owner = PublicationTextReviewer()
    arguments = dict(publication_texts={'1': {'text': 'Unique full text.', 'text_source': 'abstractText'}},
                     contexts={}, theme='fibrosis', reviewer=reviewer, checkpoint_store=store)
    first = owner.review_publication_texts(**arguments)
    assert owner.review_publication_texts(**arguments) == first
    assert reviewer.calls == 1
    saved = store.items('thematic_review')[0]['payload']
    assert 'publication_text' not in saved
    assert saved['text_ref']['sha256']
    assert len(store.items('publication_text')) == 1
    arguments['publication_texts']['1']['text'] = 'Changed full text.'
    owner.review_publication_texts(**arguments)
    assert reviewer.calls == 2
