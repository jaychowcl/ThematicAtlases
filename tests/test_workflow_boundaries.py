"""Exercise workflows with injected services and the public subclass boundary."""
import inspect
import json
from pathlib import Path
import pytest
from ThematicAtlases.atlas import Atlas


def test_public_atlas_signatures_stay_compatible():
    contracts = json.loads((Path(__file__).parent / 'fixtures/contracts/atlas-python-signatures.json').read_text())
    assert {name: str(inspect.signature(getattr(Atlas, name))) for name in contracts} == contracts


class Collector:
    def collect_jsons(self, **kwargs):
        return []


class Filterer:
    def filter_jsons(self, **kwargs):
        return {'accessions': [], 'publication_texts': {}}


class Harmonizer:
    def harmonize_datasets(self, datasets, **kwargs):
        return datasets, []


def atlas():
    return Atlas(metadata={'atlas_id': 'test'}, collector=Collector(), filterer=Filterer(), harmonizer=Harmonizer())


def test_collection_workflow_is_independently_callable():
    from ThematicAtlases.workflows.collect import CollectDatasetsWorkflow
    result = CollectDatasetsWorkflow(atlas()).run(query=['lung'], run_id='collection')
    assert result['schema_version'] == '1.0'
    assert result['atlas']['atlas_id'] == 'test'
    assert result['run']['config']['queries'] == ['lung']
    assert result['run']['run_id'] == 'collection'


def test_create_workflow_keeps_subclass_collection_extension():
    from ThematicAtlases.workflows.create import CreateAtlasWorkflow
    calls = []
    class Specialized(Atlas):
        def collect_datasets(self, **kwargs):
            calls.append(kwargs['query'])
            return {'accessions': [], 'publication_texts': {}}
    instance = Specialized(metadata={'atlas_id':'test'}, harmonizer=Harmonizer())
    result = CreateAtlasWorkflow(instance).run(query=['lung'], theme='lung', generate_queries=False)
    assert calls == [['lung']]
    assert result['schema_version'] == '1.0'


def test_create_workflow_validates_before_side_effects():
    from ThematicAtlases.workflows.create import CreateAtlasWorkflow
    with pytest.raises(ValueError, match='non-empty theme'):
        CreateAtlasWorkflow(atlas()).run(theme=' ', query=['lung'], generate_queries=False)
