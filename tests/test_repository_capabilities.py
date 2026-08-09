from __future__ import annotations

from dataclasses import replace

import pytest

from ThematicAtlases.repository_capabilities import (
    CAPABILITY_CONTRACT_VERSION,
    DEFAULT_REPOSITORY_CAPABILITIES,
    RepositoryCapabilityRegistry,
)


def test_default_capabilities_define_complete_geo_and_arrayexpress_paths() -> None:
    registry = RepositoryCapabilityRegistry()

    assert registry.repository_ids == ("geo", "arrayexpress")
    for repository_id in registry.repository_ids:
        capability = registry.require(repository_id)
        assert capability.contract_version == CAPABILITY_CONTRACT_VERSION
        assert capability.metadata_adapter
        assert capability.provider
        assert capability.review_identity_rule == "dataset_accession"
        assert capability.harmonization_supported is True
        assert capability.projection_project_id
        assert capability.study_id_rule == "dataset_accession"
        assert capability.terminal_limitations == ()
        assert set(capability.required_contract_tests) == {
            "collection",
            "review",
            "harmonization",
            "projection",
            "publication",
        }


@pytest.mark.parametrize(
    ("accession", "repository_id", "review_identity"),
    [
        ("GSE123", "geo", "GSE123"),
        ("gsm456", "geo", None),
        ("E-MTAB-6486", "arrayexpress", "E-MTAB-6486"),
        ("e-geod-42", "arrayexpress", "E-GEOD-42"),
        ("E-MEXP-9", "arrayexpress", "E-MEXP-9"),
    ],
)
def test_registry_resolves_accessions_and_review_identity(
    accession: str,
    repository_id: str,
    review_identity: str | None,
) -> None:
    registry = RepositoryCapabilityRegistry()

    assert registry.for_accession(accession).repository_id == repository_id
    assert registry.review_identity(accession) == review_identity


def test_registry_rejects_unknown_and_ambiguous_capabilities() -> None:
    registry = RepositoryCapabilityRegistry()

    with pytest.raises(ValueError, match="Unsupported repository"):
        registry.require("unknown")
    with pytest.raises(ValueError, match="Unsupported repository accession"):
        registry.for_accession("ERR123")

    duplicated = {
        **DEFAULT_REPOSITORY_CAPABILITIES,
        "duplicate": replace(
            DEFAULT_REPOSITORY_CAPABILITIES["geo"],
            repository_id="duplicate",
        ),
    }
    with pytest.raises(ValueError, match="Ambiguous repository accession"):
        RepositoryCapabilityRegistry(duplicated).for_accession("GSE1")


def test_registry_is_immutable_from_the_caller() -> None:
    registry = RepositoryCapabilityRegistry()

    with pytest.raises(TypeError):
        registry.capabilities["new"] = DEFAULT_REPOSITORY_CAPABILITIES["geo"]
