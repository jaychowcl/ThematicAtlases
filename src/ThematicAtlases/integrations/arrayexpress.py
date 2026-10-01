"""ArrayExpress metadata through the shared MSC conversion boundary."""
from meta_standards_converter.runtime_contracts import get_resource_profile
from ThematicAtlases.integrations.conversion import MetadataConversionAdapter


class ArrayExpressWrapper:
    metadata_handler_status = "supported"
    PREFIXES = ("E-MTAB-", "E-GEOD-", "E-MEXP-")

    def __init__(self, source_resolver=None, parser=None, resource_profile="standard", resource_overrides=None, *, converter=None):
        if source_resolver is not None or parser is not None:
            raise ValueError("inject converter= instead of source_resolver/parser; TA checkpoints whole MSC conversions")
        self.resource_profile = get_resource_profile(resource_profile, overrides=resource_overrides)
        self._conversion = MetadataConversionAdapter("arrayexpress", converter=converter, resource_profile=self.resource_profile)

    @property
    def provider_attempts(self):
        return self._conversion.metrics().provider_attempts

    @property
    def retry_count(self):
        return self._conversion.metrics().retry_count

    @property
    def rate_wait_seconds(self):
        return self._conversion.metrics().rate_wait_seconds

    def collect_accession_metadata(self, jsons, checkpoint_store=None):
        return self._conversion.collect(jsons, checkpoint_store)

    def available_accession_metadata(self, jsons, checkpoint_store):
        return self._conversion.collect(jsons, checkpoint_store, cached_only=True)
