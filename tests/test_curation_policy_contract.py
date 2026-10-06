"""Conservative publication policy and configurable catalogue contracts."""
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
    if review_filter == 'not_relevant_and_unsure':
        with pytest.warns(DeprecationWarning):
            retained, output = owner.filtered_result(records, texts, review_filter)
    else:
        retained, output = owner.filtered_result(records, texts, review_filter)
    exclude = judgement == 'not_relevant' and confidence == 'high' and review_filter != 'none'
    assert bool(retained) is not exclude
    # Policy is also attached to excluded input reviews for audit/checkpoint writeback.
    policy = texts['p1']['agentic_curator']['publication_policy']
    assert policy['action'] == ('exclude' if exclude else 'retain')
    assert policy['exclusion_eligible'] == (judgement == 'not_relevant' and confidence == 'high')
    assert policy['review_required'] == (confidence is None or judgement == 'unsure' or judgement == 'not_relevant' and confidence != 'high')
    assert review['judgement'] == judgement


def test_failed_and_legacy_reviews_retained_and_flagged():
    owner = PublicationTextReviewer()
    for review in [{'review_status': 'failed', 'judgement': 'not_relevant', 'confidence': 'high'}, {'judgement': 'not_relevant'}]:
        texts = {'p': {'agentic_curator': review}}
        rows, output = owner.filtered_result([{'publications': [{'publication_text_ref': 'p'}]}], texts, 'not_relevant')
        assert rows and output['p']['agentic_curator']['publication_policy']['review_required']


def test_criterion_cap_reaches_factory_validation_and_identity():
    owner = PublicationTextReviewer()
    reviewer = owner._reviewer(max_review_criteria=15)
    assert reviewer.max_criteria == 15
    criteria = [{'id': f'c{i}', 'description': str(i)} for i in range(13)]
    assert owner._validated_criteria_catalogue(criteria, max_criteria=15) == criteria
    with pytest.raises(ValueError): owner._validated_criteria_catalogue(criteria, max_criteria=12)
    with pytest.raises(ValueError, match='conflict'):
        owner.review_publication_texts({}, {}, 'theme', reviewer=ThematicReviewer(max_criteria=12), max_review_criteria=15)
    for value in [0, -1, True, 1.5, '12']:
        with pytest.raises(ValueError): owner.review_publication_texts({}, {}, 'theme', max_review_criteria=value)
    for method in [Atlas.collect_datasets, Atlas.create_atlas]:
        assert inspect.signature(method).parameters['max_review_criteria'].default == 12


def test_weak_negative_projection_is_unknown_with_typed_policy():
    review = AtlasDocumentAdapter()._publication_review({'judgement': 'not_relevant', 'confidence': 'medium', 'reasoning': 'Limited evidence.'})
    assert review.criteria[0].passed is None
    assert review.confidence == 'medium'
    assert review.policy.action == 'retain' and review.policy.review_required
    assert SCHEMA_VERSION == '1.1'


def test_typed_review_default_is_conservative_and_serializes_policy():
    from ThematicAtlases.domain import PublicationReview, Judgement
    review = PublicationReview(Judgement.NOT_RELEVANT)
    assert review.policy.action == 'retain' and review.policy.review_required


def test_review_reconstruction_invalidates_changed_cap(tmp_path):
    from test_checkpoint_v2_e2e import components
    from ThematicAtlases.runtime.views import CheckpointViews
    atlas, *_ = components()
    atlas.create_atlas(query=['fibrosis'], theme='fibrosis', generate_queries=False, dev_trace=True, dev_out_dir=str(tmp_path))
    directory=next(p for p in tmp_path.iterdir() if (p/'00_run_manifest.json').is_file())
    views=CheckpointViews.from_directory(directory)
    assert views.review()['publication_texts']['1']['agentic_curator']['judgement']=='relevant'
    views.manifest['max_review_criteria']=17
    assert 'judgement' not in views.review()['publication_texts']['1']['agentic_curator']


def test_publication_confidence_and_policy_survive_internal_roundtrip():
    from dataclasses import asdict
    from ThematicAtlases.domain import Publication
    adapter = AtlasDocumentAdapter()
    review = adapter._publication_review({'judgement': 'not_relevant', 'confidence': 'medium', 'reasoning': 'Limited support.'})
    legacy = adapter._legacy_publication_text(Publication('PMID:1', review=review))['agentic_curator']
    assert legacy['confidence'] == 'medium'
    assert legacy['publication_policy'] == asdict(review.policy)
    assert adapter._publication_review(legacy) == review


def test_checkpoint_records_filter_action_and_reuses_assessment_when_filter_changes(tmp_path):
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
        assert saved['publication_policy']['action'] == action
        assert saved['judgement'] == 'not_relevant' and saved['confidence'] == 'high'
        assert result['p']['agentic_curator']['publication_policy'] == saved['publication_policy']
    assert reviewer.calls == 1
