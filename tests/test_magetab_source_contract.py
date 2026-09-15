"""Source evidence must reproduce fresh MSC parsing without retrieval."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from meta_standards_converter.magetab.parser import AEParser
from meta_standards_converter.sources.magetab import MAGETabInput, TextResource
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.metadata_evidence import ARRAYEXPRESS_SOURCE_STAGE


def source_fixture():
    data = json.loads((Path(__file__).parent / 'fixtures/contracts/msc-magetab-catalogue.json').read_text())
    return MAGETabInput(
        TextResource(**data['idf']), tuple(TextResource(**r) for r in data['sdrfs']),
        data['source'], data['source_kind'], tuple(data['file_catalogue']),
    )


def test_source_roundtrip_preserves_fresh_parser_result():
    source = source_fixture()
    payload = ArrayExpressWrapper._source_payload(source)
    restored = ArrayExpressWrapper._restore_source(json.loads(json.dumps(payload)))
    assert payload['contract_version'] == 2
    assert restored == source
    assert AEParser().parse(restored) == AEParser().parse(source)
    assert restored.file_catalogue[0] is not source.file_catalogue[0]


def test_source_only_checkpoint_reparse_matches_fresh_collection(tmp_path):
    source = source_fixture()
    class Resolver:
        calls = 0
        def resolve(self, *args, **kwargs):
            self.calls += 1
            return source
    resolver = Resolver()
    wrapper = ArrayExpressWrapper(source_resolver=resolver)
    fresh_store = CheckpointStore(tmp_path / 'fresh.sqlite3')
    fresh = wrapper._convert_with_evidence(accession=source.source, index=1, checkpoint_store=fresh_store)
    restored_store = CheckpointStore(tmp_path / 'restored.sqlite3')
    restored_store.put(ARRAYEXPRESS_SOURCE_STAGE, source.source, 1, 'available',
                       payload=fresh_store.get(ARRAYEXPRESS_SOURCE_STAGE, source.source)['payload'])
    restored = wrapper._convert_with_evidence(accession=source.source, index=1, checkpoint_store=restored_store)
    assert resolver.calls == 1
    assert restored == fresh


def test_catalogue_attributes_duplicates_and_empty_are_lossless():
    source = source_fixture()
    source.file_catalogue[0]['attributes'] = [{'name': 'checksum', 'value': 'abc'}]
    from dataclasses import replace
    for catalogue in ((), source.file_catalogue + (deepcopy(source.file_catalogue[0]),)):
        original = replace(source, file_catalogue=catalogue)
        restored = ArrayExpressWrapper._restore_source(ArrayExpressWrapper._source_payload(original))
        assert restored == original
        if catalogue:
            restored.file_catalogue[0]['attributes'][0]['value'] = 'changed'
            assert original.file_catalogue[0]['attributes'][0]['value'] == 'abc'


def test_legacy_accession_requires_recollection_without_mutating_checkpoints(tmp_path):
    from ThematicAtlases.integrations.magetab import SourceEvidenceCompatibilityError
    source = source_fixture()
    payload = ArrayExpressWrapper._source_payload(source)
    payload['contract_version'] = 1
    payload.pop('file_catalogue', None)
    store = CheckpointStore(tmp_path / 'legacy.sqlite3')
    store.put(ARRAYEXPRESS_SOURCE_STAGE, source.source, 1, 'available', payload=payload)
    before = store.get(ARRAYEXPRESS_SOURCE_STAGE, source.source)
    record = {'datalink_id': source.source, 'datalink_id_scheme': 'ArrayExpress'}
    with pytest.raises(SourceEvidenceCompatibilityError, match='fresh run'):
        ArrayExpressWrapper(source_resolver=object()).collect_accession_metadata([record], store)
    assert store.get(ARRAYEXPRESS_SOURCE_STAGE, source.source) == before
    assert store.get('arrayexpress_metadata', source.source) is None
    assert store.get('arrayexpress_precanonical_metadata', source.source) is None


@pytest.mark.parametrize('kind', ['path', 'url'])
def test_legacy_nonaccession_source_remains_offline(kind):
    payload = ArrayExpressWrapper._source_payload(source_fixture())
    payload.update(contract_version=1, source_kind=kind)
    payload.pop('file_catalogue', None)
    assert ArrayExpressWrapper._restore_source(payload).file_catalogue == ()


@pytest.mark.parametrize('change', [
    {'contract_version': 99}, {'file_catalogue': None},
    {'file_catalogue': [42]}, {'file_catalogue': 'invalid'},
])
def test_invalid_source_contract_rejected(change):
    from ThematicAtlases.integrations.magetab import SourceEvidenceCompatibilityError
    payload = ArrayExpressWrapper._source_payload(source_fixture())
    payload.update(change)
    with pytest.raises(SourceEvidenceCompatibilityError):
        ArrayExpressWrapper._restore_source(payload)


def test_old_msc_keeps_four_argument_contract_and_rejects_v2(monkeypatch):
    from ThematicAtlases.integrations import magetab
    @dataclass(frozen=True)
    class OldInput:
        idf: TextResource
        sdrfs: tuple
        source: str
        source_kind: str
    modern_payload = ArrayExpressWrapper._source_payload(source_fixture())
    monkeypatch.setattr(magetab, 'MAGETabInput', OldInput)
    original = OldInput(TextResource('x', 'text', 'origin'), (), 'E-MTAB-1', 'accession')
    legacy = ArrayExpressWrapper._source_payload(original)
    assert legacy['contract_version'] == 1
    assert 'file_catalogue' not in legacy
    assert ArrayExpressWrapper._restore_source(legacy) == original
    with pytest.raises(magetab.SourceEvidenceCompatibilityError, match='MSC'):
        ArrayExpressWrapper._restore_source(modern_payload)


def test_available_metadata_reuse_does_not_reparse_legacy_source(tmp_path):
    source = source_fixture()
    class Resolver:
        def resolve(self, *args, **kwargs):
            return source
    store = CheckpointStore(tmp_path / 'cached.sqlite3')
    record = {'datalink_id': source.source, 'datalink_id_scheme': 'ArrayExpress'}
    wrapper = ArrayExpressWrapper(source_resolver=Resolver())
    fresh = wrapper.collect_accession_metadata([record], store)
    legacy = wrapper._source_payload(source)
    legacy.update(contract_version=1)
    legacy.pop('file_catalogue')
    store.put(ARRAYEXPRESS_SOURCE_STAGE, source.source, 1, 'available', payload=legacy)
    assert ArrayExpressWrapper(source_resolver=object(), parser=object()).collect_accession_metadata([record], store) == fresh
