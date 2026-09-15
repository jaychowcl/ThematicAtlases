from functools import partial
from meta_standards_converter.runtime_contracts import get_resource_profile


def test_runtime_factory_keeps_construction_lazy_and_injects_provider_identity():
    from ThematicAtlases.bootstrap import AtlasRuntimeFactory
    calls = []
    class Provider:
        def __init__(self, resource_profile, ncbi_tool, ncbi_api_key, ncbi_email):
            calls.append((resource_profile, ncbi_tool, ncbi_api_key, ncbi_email))
    profile = get_resource_profile('standard', overrides={'network_workers':2})
    factory = AtlasRuntimeFactory(resource_profile=profile, epmc_wrapper_factory=partial(
        Provider, resource_profile=profile, ncbi_tool='tool', ncbi_api_key='key', ncbi_email='mail'))
    main = factory.build_atlas(metadata={'atlas_id':'x'})
    worker = factory.build_worker()
    reviewer = factory.build_reviewer()
    assert calls == []
    assert main._resource_profile is profile
    main._collector._epmc_wrapper()
    worker._epmc_wrapper_factory()
    reviewer._resume_orchestrator()._epmc_wrapper_factory()
    assert calls == [(profile,'tool','key','mail')] * 3


def test_runtime_factory_isolates_continuation_instances_and_preserves_cancellation():
    from ThematicAtlases.bootstrap import AtlasRuntimeFactory
    received = []
    def cancelled(): return True
    def reviewer_factory(cancelled=None):
        received.append(cancelled)
        return object()
    factory = AtlasRuntimeFactory(reviewer_factory=reviewer_factory, metadata_repositories=['geo'])
    a, b = factory.build_reviewer(cancelled=cancelled), factory.build_reviewer()
    assert a is not b
    assert a._resume_orchestrator()._collector_factory() is not b._resume_orchestrator()._collector_factory()
    a._reviewer()
    assert received == [cancelled]
    assert factory.build_collector()._metadata_repositories == ('geo',)


def test_runtime_factory_preserves_injected_components():
    from ThematicAtlases.bootstrap import AtlasRuntimeFactory
    objects = {name: object() for name in ('collector','filterer','harmonizer','query_generator','credential_checker')}
    atlas = AtlasRuntimeFactory().build_atlas(metadata={}, **objects)
    for name in ('collector','filterer','harmonizer','credential_checker'):
        assert getattr(atlas, '_'+name) is objects[name]
    assert atlas._query_generator_instance is objects['query_generator']
