from __future__ import annotations

import pytest

from meta_standards_converter.miniml import (
    MINiMLCodec,
    MINiMLHarmonizationPatch,
    apply_miniml_harmonization_patch,
    miniml_source_fingerprint,
)

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


def test_checkpoint_round_trip_preserves_retained_harmonization_fragments() -> None:
    package = {**package_mapping(), "miniml_schema_version": "3.0"}
    patch = MINiMLHarmonizationPatch(
        base_sha256=miniml_source_fingerprint(package),
        adds=(),
    )
    # Empty patches are valid but have no package-local operation to attach.
    assert apply_miniml_harmonization_patch(package, patch) == package

    package["sample"] = [
        {"iid": "GSM1", "channel": [{"source": {"value": "lung"}}]}
    ]
    path = "/sample/0/channel/0/source"
    patch = MINiMLHarmonizationPatch(
        base_sha256=miniml_source_fingerprint(package),
        adds=(
            {
                "path": path,
                "harmonized_value": {"field": "tissue", "value": "lung"},
                "source_evidence": {
                    "target_id": "target-1",
                    "source_field": "source",
                    "source_label": "lung",
                    "source_field_path": path,
                    "source_value_path": f"{path}/value",
                    "derivation": "direct",
                    "match_kind": "exact_value",
                },
            },
        ),
    )
    applied = apply_miniml_harmonization_patch(package, patch)
    payload = checkpoint_payload([applied], checkpoint_version=3)

    restored = checkpoint_packages(payload)
    assert restored == [applied]
    assert restored[0]["extensions"]["msc_harmonization"]["patches"][0][
        "operations"
    ][0]["source_evidence"]["source_label"] == "lung"
