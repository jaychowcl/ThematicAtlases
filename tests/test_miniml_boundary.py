from __future__ import annotations

import pytest

from meta_standards_converter.miniml import MINiMLCodec

from ThematicAtlases.miniml_boundary import (
    MINIML_CHECKPOINT_PAYLOAD_VERSION,
    canonicalize_atlas_metadata,
    canonicalize_miniml_package,
    checkpoint_payload,
    checkpoint_packages,
)


def package_mapping(iid: str = "GSE1") -> dict:
    return {
        "miniml_schema_version": "2.0",
        "source": {"format": "test"},
        "database": [],
        "organization": [],
        "contributor": [],
        "platform": [],
        "sample": [],
        "series": {"iid": iid},
    }


def test_canonicalization_accepts_mapping_and_typed_package() -> None:
    mapping = package_mapping()
    typed = MINiMLCodec().decode(mapping, strict=True).package
    canonical = {**mapping, "miniml_schema_version": "3.0"}

    assert canonicalize_miniml_package(mapping) == canonical
    assert canonicalize_miniml_package(typed) == canonical


@pytest.mark.parametrize(
    "value",
    [
        {"miniml_schema_version": "1.0", "series": {"iid": "GSE1"}},
        {"series": {"iid": "GSE1"}, "mage_tab": {"model": {}}},
    ],
)
def test_atlas_metadata_rejects_legacy_miniml(value) -> None:
    with pytest.raises(ValueError, match="MSC MINiML schema version '3.0'"):
        canonicalize_atlas_metadata(value)


def test_atlas_metadata_validates_package_collections_but_preserves_other_metadata() -> None:
    package = package_mapping()
    canonical = {**package, "miniml_schema_version": "3.0"}

    assert canonicalize_atlas_metadata({"packages": [package]}) == {
        "packages": [canonical]
    }
    assert canonicalize_atlas_metadata({"accession": "GSE1"}) == {
        "accession": "GSE1"
    }


def test_checkpoint_payload_requires_explicit_miniml_version_markers() -> None:
    package = package_mapping()
    payload = checkpoint_payload([package], checkpoint_version=3)

    assert payload["miniml_checkpoint_payload_version"] == MINIML_CHECKPOINT_PAYLOAD_VERSION
    assert payload["miniml_schema_version"] == "3.0"
    assert checkpoint_packages(payload) == [
        {**package, "miniml_schema_version": "3.0"}
    ]
    assert checkpoint_packages({"checkpoint_version": 3, "packages": [package]}) is None
