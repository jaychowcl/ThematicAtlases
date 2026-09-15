import importlib
import pytest


@pytest.mark.parametrize('old,new,symbol', [
    ('domain','domain.atlas','AtlasDocument'),
    ('artifact_publisher','publication.publisher','JsonArtifactBundlePublisher'),
    ('document_adapter','publication.adapter','AtlasDocumentAdapter'),
    ('application.atlas_documents','publication.documents','AtlasDocumentService'),
    ('checkpoint','runtime.checkpoint','CheckpointStore'),
    ('run_store','runtime.run_store','AtlasRunStore'),
    ('trace','runtime.trace','DevTraceWriter'),
    ('run_lifecycle','runtime.lifecycle','AtlasRunLifecycle'),
    ('run_archive','runtime.archive','workflow_activity_lock'),
    ('stage_worker','workflows.worker','TraceStageWorker'),
    ('wrappers.epmc','integrations.europe_pmc','EuropePMCWrapper'),
    ('wrappers.ae','integrations.arrayexpress','ArrayExpressWrapper'),
    ('wrappers.geo','integrations.geo','GEOWrapper'),
])
def test_legacy_imports_resolve_to_owning_implementation(old,new,symbol):
    legacy = importlib.import_module('ThematicAtlases.'+old)
    owner = importlib.import_module('ThematicAtlases.'+new)
    assert getattr(legacy,symbol) is getattr(owner,symbol)


def test_cli_dispatch_accepts_explicit_factory_without_provider_calls():
    from ThematicAtlases.cli.atlas import main
    calls = []
    class FakeAtlas:
        def __init__(self, **kwargs): pass
        def collect_datasets(self, **kwargs): calls.append(kwargs)
    assert main(['collect-datasets','--query','lung'], atlas_factory=FakeAtlas) == 0
    assert calls[0]['query'] == ['lung']
