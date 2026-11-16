"""Existing filtering, historical policy transport and criterion-limit contracts."""
from copy import deepcopy
import inspect
import pytest
from agentic_curator import ThematicReviewer
from ThematicAtlases.filterer.review import PublicationTextReviewer
from ThematicAtlases.publication.adapter import AtlasDocumentAdapter
from ThematicAtlases.domain.atlas import AtlasDocument, SCHEMA_VERSION
from ThematicAtlases.atlas import Atlas

@pytest.mark.parametrize('judgement', ['relevant', 'not_relevant', 'unsure'])
@pytest.mark.parametrize('confidence', ['low', 'medium', 'high', None])
@pytest.mark.parametrize('review_filter', ['none', 'not_relevant', 'not_relevant_and_unsure'])
def test_publication_policy_table(judgement, confidence, review_filter):
    owner = PublicationTextReviewer()
    review = {'judgement': judgement, 'confidence': confidence}
    texts = {'p1': {'agentic_curator': review}}
    records = [{'datalink_id': 'GSE1', 'publications': [{'publication_text_ref': 'p1'}]}]
    retained, output = owner.filtered_result(records, texts, review_filter)
    exclude = (review_filter != 'none' and judgement == 'not_relevant' or
               review_filter == 'not_relevant_and_unsure' and judgement == 'unsure')
    assert bool(retained) is not exclude
    assert 'publication_policy' not in review
    assert review == {'judgement': judgement, 'confidence': confidence}


def test_failed_review_is_retained_and_legacy_negative_is_filtered():
    owner = PublicationTextReviewer()
    for review, retained in [({'review_status': 'failed', 'judgement': 'not_relevant'}, True),
                             ({'judgement': 'not_relevant'}, False)]:
        texts = {'p': {'agentic_curator': review}}
        rows, _ = owner.filtered_result([{'publications': [{'publication_text_ref': 'p'}]}], texts, 'not_relevant')
        assert bool(rows) is retained
        assert 'publication_policy' not in review


def test_criterion_cap_reaches_factory_validation_and_identity():
    owner = PublicationTextReviewer()
    reviewer = owner._reviewer(max_review_criteria=15)
    assert reviewer.MAX_CRITERIA == 15
    criteria = [{'id': f'c{i}', 'description': str(i)} for i in range(13)]
    assert owner._validated_criteria_catalogue(criteria, max_criteria=15) == criteria
    with pytest.raises(ValueError): owner._validated_criteria_catalogue(criteria, max_criteria=12)
    with pytest.raises(ValueError, match='conflict'):
        owner.review_publication_texts({}, {}, 'theme', reviewer=ThematicReviewer(), max_review_criteria=15)
    for value in [0, -1, True, 1.5, '12']:
        with pytest.raises(ValueError): owner.review_publication_texts({}, {}, 'theme', max_review_criteria=value)
    for method in [Atlas.collect_datasets, Atlas.create_atlas]:
        assert inspect.signature(method).parameters['max_review_criteria'].default == 12


def test_negative_projection_preserves_existing_decision_and_confidence():
    review = AtlasDocumentAdapter()._publication_review({'judgement': 'not_relevant', 'confidence': 'medium', 'reasoning': 'Limited evidence.'})
    assert review.criteria[0].passed is False
    assert review.confidence == 'medium'
    assert review.policy is None
    assert SCHEMA_VERSION == '1.1'


def test_typed_review_does_not_synthesize_policy():
    from ThematicAtlases.domain import PublicationReview, Judgement
    review = PublicationReview(Judgement.NOT_RELEVANT)
    assert review.policy is None


def test_review_reconstruction_invalidates_changed_cap(tmp_path):
    from test_checkpoint_v2_e2e import components
    from ThematicAtlases.runtime.views import CheckpointViews
    atlas, *_ = components()
    atlas.create_atlas(query=['fibrosis'], theme='fibrosis', generate_queries=False, dev_trace=True, dev_out_dir=str(tmp_path))
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    views=CheckpointViews.from_directory(directory)
    assert views.review()['publication_texts']['1']['agentic_curator']['judgement']=='relevant'
    views.manifest['max_review_criteria']=17
    assert 'judgement' not in views.review()['publication_texts']['1'].get('agentic_curator', {})


def test_publication_confidence_and_policy_survive_internal_roundtrip():
    from dataclasses import asdict
    from ThematicAtlases.domain import Publication
    adapter = AtlasDocumentAdapter()
    review = adapter._publication_review({'judgement': 'not_relevant', 'confidence': 'medium', 'reasoning': 'Limited support.'})
    legacy = adapter._legacy_publication_text(Publication('PMID:1', review=review))['agentic_curator']
    assert legacy['confidence'] == 'medium'
    assert 'publication_policy' not in legacy
    assert adapter._publication_review(legacy) == review


def test_checkpoint_reuses_assessment_without_policy_when_filter_changes(tmp_path):
    from ThematicAtlases.checkpoint import CheckpointStore
    owner = PublicationTextReviewer()
    store = CheckpointStore(tmp_path/'review.sqlite3')
    class Reviewer:
        calls = 0
        def review_relevancy(self, **kwargs):
            self.calls += 1
            return {'judgement': 'not_relevant', 'confidence': 'high', 'reasoning': 'Explicit mismatch.',
                    'criteria': [{'id': 'topic', 'description': 'Theme data.'}], 'accession_assessments': [],
                    'accessions_to_remove': []}
    reviewer = Reviewer()
    arguments = dict(publication_texts={'p': {'text': 'An unrelated paper.'}}, contexts={'p': {'accessions': []}},
                     theme='Human fibrosis', reviewer=reviewer, checkpoint_store=store)
    for review_filter, action in [('not_relevant', 'exclude'), ('none', 'retain')]:
        result = owner.review_publication_texts(**arguments, review_filter=review_filter)
        item, = store.items('thematic_review')
        saved = item['payload']['review']
        assert 'publication_policy' not in saved
        assert saved['judgement'] == 'not_relevant' and saved['confidence'] == 'high'
        assert result['p']['agentic_curator'] == saved
    assert reviewer.calls == 1


@pytest.mark.parametrize('declared', [False, True])
def test_changed_limit_invalidates_injected_reviewer_identity(declared):
    class Reviewer:
        MAX_CRITERIA = 12
        def review_relevancy(self, **kwargs): return {}
    reviewer = Reviewer()
    if declared:
        reviewer.review_execution_identity = lambda: {'provider': 'test', 'model': 'test', 'generation': {}, 'prompt_sha256': 'a'*64}
    before = PublicationTextReviewer._reviewer_identity(reviewer)
    reviewer.MAX_CRITERIA = 17
    after = PublicationTextReviewer._reviewer_identity(reviewer)
    assert before['max_review_criteria'] == 12
    assert after['max_review_criteria'] == 17
    assert after['filter_contract_version'] == 12


def test_historical_policy_is_readable_but_does_not_change_filtering():
    from dataclasses import asdict
    from ThematicAtlases.domain import Publication
    value = {'judgement': 'not_relevant', 'confidence': 'medium', 'publication_policy': {
        'version': 1, 'action': 'retain', 'exclusion_eligible': False,
        'review_required': True, 'reason': 'Historical confidence rule.'}}
    adapter = AtlasDocumentAdapter()
    review = adapter._publication_review(value)
    legacy = adapter._legacy_publication_text(Publication('PMID:1', review=review))['agentic_curator']
    assert legacy['publication_policy'] == value['publication_policy'] == asdict(review.policy)
    assert adapter._publication_review(legacy) == review
    texts = {'p': {'agentic_curator': legacy}}
    rows, _ = PublicationTextReviewer().filtered_result(
        [{'publications': [{'publication_text_ref': 'p'}]}], texts, 'not_relevant')
    assert rows == []
    assert legacy['publication_policy'] == value['publication_policy']


def test_factory_owned_ac_reviewer_uses_existing_limit_without_changing_class_default():
    owner = PublicationTextReviewer(reviewer_factory=lambda: ThematicReviewer(egress_classification='public'))
    configured = owner._reviewer(max_review_criteria=17)
    assert configured.MAX_CRITERIA == 17 and ThematicReviewer.MAX_CRITERIA == 12
    assert configured.egress_classification == 'public'
    assert owner._reviewer_identity(configured)['max_review_criteria'] == 17
