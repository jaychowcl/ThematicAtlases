"""Versioned, lossless MSC MAGE-TAB source evidence.

The optional MSC catalogue is part of the parse input, not enrichment that can
be reconstructed from an IDF/SDRF snapshot. Never silently discard that evidence.
"""
from collections.abc import Mapping
from copy import deepcopy

from meta_standards_converter.sources.magetab import MAGETabInput, TextResource


class SourceEvidenceCompatibilityError(ValueError):
    """Saved source evidence cannot be faithfully parsed by this runtime."""


def _catalogue_supported() -> bool:
    return 'file_catalogue' in MAGETabInput.__dataclass_fields__


def _catalogue(value) -> list[dict]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(row, Mapping) for row in value):
        raise SourceEvidenceCompatibilityError('MAGE-TAB file_catalogue must be a list of mappings')
    return deepcopy([dict(row) for row in value])


def resource_payload(resource: TextResource) -> dict:
    from ThematicAtlases.wrappers.metadata_evidence import compressed_text
    return {'name': resource.name, 'origin': resource.origin, 'content': compressed_text(resource.text)}


def restore_resource(value: Mapping) -> TextResource:
    from ThematicAtlases.wrappers.metadata_evidence import restored_text
    if not isinstance(value, Mapping):
        raise SourceEvidenceCompatibilityError('Invalid MAGE-TAB text resource')
    content = value.get('content')
    if not isinstance(content, Mapping):
        raise SourceEvidenceCompatibilityError('Invalid MAGE-TAB text resource content')
    try:
        text = restored_text(content)
    except (TypeError, ValueError) as error:
        raise SourceEvidenceCompatibilityError('Corrupt or unsupported MAGE-TAB text resource content') from error
    return TextResource(str(value.get('name') or ''), text, str(value.get('origin') or ''))


def source_payload(source: MAGETabInput) -> dict:
    supported = _catalogue_supported()
    result = {
        'contract_version': 2 if supported else 1,
        'provider': 'arrayexpress', 'source': source.source, 'source_kind': source.source_kind,
        'idf': resource_payload(source.idf), 'sdrfs': [resource_payload(item) for item in source.sdrfs],
    }
    if supported:
        result['file_catalogue'] = _catalogue(source.file_catalogue)
    return result


def restore_source(value: Mapping) -> MAGETabInput:
    if not isinstance(value, Mapping) or type(value.get('contract_version')) is not int or value['contract_version'] not in (1, 2):
        raise SourceEvidenceCompatibilityError('Unsupported MAGE-TAB source evidence version')
    supported = _catalogue_supported()
    version = value['contract_version']
    if version == 2 and not supported:
        raise SourceEvidenceCompatibilityError('This MAGE-TAB source snapshot requires catalogue-capable MSC')
    if version == 1 and supported and value.get('source_kind') not in {'path', 'url'}:
        raise SourceEvidenceCompatibilityError(
            f"MAGE-TAB source {value.get('source', '')} has no captured file catalogue; "
            'recollect the complete source bundle in a fresh run'
        )
    catalogue = []
    if version == 2:
        if not isinstance(value.get('file_catalogue'), list):
            raise SourceEvidenceCompatibilityError('MAGE-TAB source v2 requires file_catalogue as a list')
        catalogue = _catalogue(value['file_catalogue'])
    resources = value.get('sdrfs')
    if not isinstance(resources, list):
        raise SourceEvidenceCompatibilityError('MAGE-TAB source requires an SDRF resource list')
    arguments = (
        restore_resource(value.get('idf')),
        tuple(restore_resource(item) for item in resources),
        str(value.get('source') or ''), str(value.get('source_kind') or ''),
    )
    return MAGETabInput(*arguments, file_catalogue=tuple(catalogue)) if supported else MAGETabInput(*arguments)
