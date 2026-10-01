"""Source evidence must reproduce fresh MSC parsing without retrieval."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from meta_standards_converter.magetab.parser import AEParser
from meta_standards_converter.sources.magetab import MAGETabInput, TextResource
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.integrations.magetab import source_payload, restore_source
from ThematicAtlases.wrappers.metadata_evidence import ARRAYEXPRESS_SOURCE_STAGE


def source_fixture():
    if 'file_catalogue' not in MAGETabInput.__dataclass_fields__:
        pytest.skip('fixture requires catalogue-capable MSC')
    data = json.loads((Path(__file__).parent / 'fixtures/contracts/msc-magetab-catalogue.json').read_text())
    return MAGETabInput(
        TextResource(**data['idf']), tuple(TextResource(**r) for r in data['sdrfs']),
        data['source'], data['source_kind'], tuple(data['file_catalogue']),
    )


def test_source_roundtrip_preserves_fresh_parser_result():
    source = source_fixture()
    payload = source_payload(source)
    restored = restore_source(json.loads(json.dumps(payload)))
    assert payload['contract_version'] == 2
    assert restored == source
    assert AEParser().parse(restored) == AEParser().parse(source)
    assert restored.file_catalogue[0] is not source.file_catalogue[0]




def test_catalogue_attributes_duplicates_and_empty_are_lossless():
    source = source_fixture()
    source.file_catalogue[0]['attributes'] = [{'name': 'checksum', 'value': 'abc'}]
    from dataclasses import replace
    for catalogue in ((), source.file_catalogue + (deepcopy(source.file_catalogue[0]),)):
        original = replace(source, file_catalogue=catalogue)
        restored = restore_source(source_payload(original))
        assert restored == original
        if catalogue:
            restored.file_catalogue[0]['attributes'][0]['value'] = 'changed'
            assert original.file_catalogue[0]['attributes'][0]['value'] == 'abc'




@pytest.mark.parametrize('kind', ['path', 'url'])
def test_legacy_nonaccession_source_remains_offline(kind):
    payload = source_payload(source_fixture())
    payload.update(contract_version=1, source_kind=kind)
    payload.pop('file_catalogue', None)
    assert restore_source(payload).file_catalogue == ()


@pytest.mark.parametrize('change', [
    {'contract_version': 99}, {'file_catalogue': None},
    {'file_catalogue': [42]}, {'file_catalogue': 'invalid'},
])
def test_invalid_source_contract_rejected(change):
    from ThematicAtlases.integrations.magetab import SourceEvidenceCompatibilityError
    payload = source_payload(source_fixture())
    payload.update(change)
    with pytest.raises(SourceEvidenceCompatibilityError):
        restore_source(payload)


def test_old_msc_keeps_four_argument_contract_and_rejects_v2(monkeypatch):
    from ThematicAtlases.integrations import magetab
    @dataclass(frozen=True)
    class OldInput:
        idf: TextResource
        sdrfs: tuple
        source: str
        source_kind: str
    monkeypatch.setattr(magetab, 'MAGETabInput', OldInput)
    original = OldInput(TextResource('x', 'text', 'origin'), (), 'E-MTAB-1', 'accession')
    legacy = source_payload(original)
    assert legacy['contract_version'] == 1
    assert 'file_catalogue' not in legacy
    assert restore_source(legacy) == original
    modern_payload = {**legacy, 'contract_version': 2, 'file_catalogue': []}
    with pytest.raises(magetab.SourceEvidenceCompatibilityError, match='MSC'):
        restore_source(modern_payload)




def test_metadata_worker_surfaces_incompatible_source_instead_of_deferring(tmp_path):
    from ThematicAtlases.integrations.magetab import SourceEvidenceCompatibilityError
    from ThematicAtlases.stage_worker import TraceStageWorker
    class Collector:
        def collect_accession_metadata(self, **kwargs):
            raise SourceEvidenceCompatibilityError('recollect in a fresh run')
    class Worker(TraceStageWorker):
        def _collector(self): return Collector()
        def _merged_accessions(self, publications, store):
            return [{'datalink_id':'E-MTAB-1','datalink_id_scheme':'arrayexpress'}]
        def _metadata_accession_actionable(self, *args): return True
        def _continue_work(self, store): return True
        def _manifest_repositories(self, directory): return ['arrayexpress']
    with pytest.raises(SourceEvidenceCompatibilityError, match='fresh run'):
        Worker()._run_metadata([], CheckpointStore(tmp_path/'worker.sqlite3'))


def test_review_continuation_surfaces_incompatible_source(tmp_path):
    from ThematicAtlases.integrations.magetab import SourceEvidenceCompatibilityError
    from ThematicAtlases.filterer.resume import TracePublicationReviewResumer
    record = {'datalink_id':'E-MTAB-1','metadata_status':'pending'}
    class Collector:
        def available_accession_metadata(self, **kwargs): return [record]
        def collect_accession_metadata(self, **kwargs):
            raise SourceEvidenceCompatibilityError('recollect in a fresh run')
    with pytest.raises(SourceEvidenceCompatibilityError, match='fresh run'):
        TracePublicationReviewResumer._collect_snapshot_metadata(
            collector=Collector(), accessions=[record], repositories=['arrayexpress'],
            store=CheckpointStore(tmp_path/'review.sqlite3'),
            datalink_checkpoint_count=1, datalink_row_count=1,
        )


@pytest.mark.parametrize('content', [[], {'encoding':'unknown'}, {'encoding':'gzip+base64','data':'bad'}])
def test_corrupt_text_resource_is_a_source_compatibility_error(content):
    from ThematicAtlases.integrations.magetab import restore_resource, SourceEvidenceCompatibilityError
    with pytest.raises(SourceEvidenceCompatibilityError, match='text resource'):
        restore_resource({'name':'study.idf.txt','origin':'fixture','content':content})
