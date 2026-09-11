# =============================================================================
# Authors
#
# Created by jaychowcl @ Saez-Rodriguez Group & EMBL-EBI Functional Genomics Team on May 2026
# https://github.com/jaychowcl
# https://saezlab.org
# https://www.ebi.ac.uk/about/teams/functional-genomics/
# =============================================================================

import pytest


def obsolete_package():
    return {"miniml_schema_version": "2.0", "source": {"format": "test"}, "series": {"iid": "GSE1"}}


@pytest.mark.parametrize("collection", [False, True])
def test_atlas_boundary_rejects_v2(collection):
    from ThematicAtlases.miniml_boundary import canonicalize_atlas_metadata
    payload = obsolete_package()
    if collection:
        payload = {"packages": [payload]}
    with pytest.raises(ValueError, match="3.0"):
        canonicalize_atlas_metadata(payload)
