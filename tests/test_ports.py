from ThematicAtlases.ports import (
    ArtifactPublisherPort,
    CollectorPort,
    FiltererPort,
    HarmonizerPort,
)


def test_runtime_ports_accept_minimal_injected_collaborators():
    class Collector:
        def collect_jsons(self, **kwargs):
            return []

    class Filterer:
        def filter_jsons(self, **kwargs):
            return {"accessions": [], "publication_texts": {}}

    class Harmonizer:
        def harmonize_datasets(self, **kwargs):
            return {"accessions": [], "publication_texts": {}}, []

    class Publisher:
        def publish(self, artifacts):
            return None

    assert isinstance(Collector(), CollectorPort)
    assert isinstance(Filterer(), FiltererPort)
    assert isinstance(Harmonizer(), HarmonizerPort)
    assert isinstance(Publisher(), ArtifactPublisherPort)
