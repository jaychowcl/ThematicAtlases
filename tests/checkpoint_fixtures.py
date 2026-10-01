"""Construct new-contract checkpoint fixtures without provider calls."""
from ThematicAtlases.integrations.conversion import MetadataConversionAdapter
from ThematicAtlases.miniml_boundary import checkpoint_payload


def conversion_payload(payload=None):
    adapter=MetadataConversionAdapter('geo',converter=object())
    value=checkpoint_payload([],checkpoint_version=1)
    value.update(payload or {})
    partial=(value.get('repair_summary') or {}).get('failed_count',0)>0
    value.update(input_hash=adapter.input_hash,settings=adapter.settings,
                 outcome={'execution':'succeeded','validation':'valid','completeness':'partial' if partial else 'complete'})
    return value
