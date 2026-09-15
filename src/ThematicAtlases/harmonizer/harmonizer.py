from ThematicAtlases.stages.harmonization import HarmonizationStage, HarmonizationRequest
import copy
from concurrent.futures import as_completed, ThreadPoolExecutor
import hashlib
import inspect
import json
import logging
from pathlib import Path

from agentic_curator.contracts import miniml_source_fingerprint
from agentic_curator.review_decisions import ReviewDecisionFile
from ThematicAtlases.checkpoint import failure_category, is_retryable_error
from meta_standards_converter.miniml import MINiMLCodec
from meta_standards_converter.runtime_contracts import (
    ExecutionStatus,
    OperationStatusV2,
)
from ThematicAtlases.runtime_contracts import failed_status, not_run_status
from ThematicAtlases.repository_capabilities import RepositoryCapabilityRegistry
from meta_standards_converter.runtime_contracts import ResourceProfile, get_resource_profile

logger = logging.getLogger(__name__)


class AtlasHarmonizer:
    REMOVED_HARMONIZATION_OPTIONS = frozenset(
        {"llm", "lookup_llm_judge", "search_llm_judge"}
    )
    MODEL_STAGE_DEFAULTS = {
        "target_checker": True,
        "direct_lookup_judge": True,
        "rag_lookup": True,
        "rag_lookup_judge": True,
        "ols_lookup": True,
        "ols_lookup_judge": True,
        "field_assignment_judge": True,
    }

    def __init__(
        self,
        ontology_harmonizer=None,
        ontology_harmonizer_factory=None,
        ontostore=None,
        credential_checker=None,
        max_workers: int = 1,
        capability_registry: RepositoryCapabilityRegistry | None = None,
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides: dict[str, int | float] | None = None,
    ):
        self._ontology_harmonizer_instance = ontology_harmonizer
        self._ontology_harmonizer_factory = ontology_harmonizer_factory
        self._ontostore = ontostore
        self._credential_checker = credential_checker
        self._credentials_checked = False
        self._capability_registry = (
            capability_registry or RepositoryCapabilityRegistry()
        )
        self._resource_profile = (
            resource_profile.with_overrides(resource_overrides)
            if isinstance(resource_profile, ResourceProfile) and resource_overrides
            else resource_profile
            if isinstance(resource_profile, ResourceProfile)
            else get_resource_profile(
                resource_profile,
                overrides=resource_overrides,
            )
        )
        if max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        self._max_workers = max_workers

    def harmonize_datasets(
        self,
        datasets: dict,
        details_out: str | None = None,
        harmonization_options: dict | None = None,
        checkpoint_store=None,
        review_decisions: dict | None = None,
    ) -> tuple[dict, list[dict]]:
        return HarmonizationStage(self).run(HarmonizationRequest(
            datasets=datasets,
            details_out=details_out,
            harmonization_options=harmonization_options,
            checkpoint_store=checkpoint_store,
            review_decisions=review_decisions,
        )).as_pair()

    def _eligibility_reason(self, record: dict) -> str | None:
        try:
            capability = self._capability_registry.for_accession(
                record.get("datalink_id")
            )
        except ValueError:
            return "unsupported_repository"
        declared_repository = str(
            record.get("metadata_repository") or ""
        ).strip().casefold()
        if declared_repository and declared_repository != capability.repository_id:
            return "repository_identity_mismatch"
        if not capability.harmonization_supported:
            return "harmonization_unsupported"
        return None

    @staticmethod
    def _validated_operation_status(harmonization: dict) -> OperationStatusV2:
        if not isinstance(harmonization, dict):
            raise ValueError("ontology harmonizer result must be an object")
        if harmonization.get("contract_version") != "2.0":
            raise ValueError(
                "ontology harmonizer result must use contract_version 2.0"
            )
        raw_status = harmonization.get("status")
        if not isinstance(raw_status, dict):
            raise ValueError("ontology harmonizer result must contain status v2")
        status = OperationStatusV2.from_dict(raw_status)
        if status.execution not in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.DEGRADED,
        }:
            raise ValueError(
                "ontology harmonizer did not return a usable terminal result"
            )
        return status

    def _work_key(
        self,
        metadata,
        publication_context: str | None,
        harmonization_options: dict,
        execution_identity: dict | None = None,
    ) -> str:
        if execution_identity is None:
            execution_identity = self._harmonization_execution_identity()
        key_data = {
            "metadata": metadata,
            "publication_context": publication_context,
            "harmonization_options": harmonization_options,
            "harmonization_execution_identity": execution_identity,
        }
        preferred_ontology_ids = self._preferred_ontology_ids()
        if preferred_ontology_ids:
            key_data["preferred_ontology_ids"] = preferred_ontology_ids
        return json.dumps(
            key_data,
            sort_keys=True,
            default=repr,
        )

    def _harmonization_execution_identity(
        self, ontology_harmonizer=None
    ) -> dict:
        provider = ontology_harmonizer or self._ontology_harmonizer()
        identity_method = getattr(
            provider, "harmonization_execution_identity", None
        )
        if not callable(identity_method):
            return self._fallback_execution_identity(provider)

        identity = identity_method()
        if not isinstance(identity, dict):
            raise ValueError(
                "harmonization_execution_identity must return an object"
            )
        required_sections = {
            "model",
            "generation",
            "prompt_sha256",
            "embedding",
            "ontology",
            "strategy",
            "preprocessing",
        }
        missing = sorted(
            {"contract_version", *required_sections}.difference(identity)
        )
        if missing:
            raise ValueError(
                "harmonization_execution_identity is missing: "
                + ", ".join(missing)
            )
        if not isinstance(identity["contract_version"], str) or not identity[
            "contract_version"
        ].strip():
            raise ValueError(
                "harmonization_execution_identity contract_version must be "
                "a non-empty string"
            )
        invalid_sections = sorted(
            section
            for section in required_sections
            if not isinstance(identity[section], dict) or not identity[section]
        )
        if invalid_sections:
            raise ValueError(
                "harmonization_execution_identity sections must be non-empty "
                "objects: "
                + ", ".join(invalid_sections)
            )
        try:
            return json.loads(
                json.dumps(
                    identity,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "harmonization_execution_identity must be JSON serializable"
            ) from error

    def _fallback_execution_identity(self, provider) -> dict:
        provider_type = type(provider)
        provider_name = (
            f"{provider_type.__module__}.{provider_type.__qualname__}"
        )
        implementation = getattr(
            provider_type, "harmonize_miniml_json", provider_type
        )
        try:
            implementation_source = inspect.getsource(implementation)
        except (OSError, TypeError):
            implementation_source = provider_name
        implementation_sha256 = hashlib.sha256(
            implementation_source.encode("utf-8")
        ).hexdigest()
        preferred_ontology_ids = self._preferred_ontology_ids()
        return {
            "contract_version": "fallback-1.0",
            "model": {
                "provider": provider_name,
                "model": str(getattr(provider, "model", "provider-owned")),
            },
            "generation": {"provider_contract": "injected-adapter"},
            "prompt_sha256": {
                "provider_implementation": implementation_sha256
            },
            "embedding": {"configuration": "provider-owned"},
            "ontology": {
                "preferred_ontology_ids": preferred_ontology_ids,
                "store_type": (
                    f"{type(self._ontostore).__module__}."
                    f"{type(self._ontostore).__qualname__}"
                    if self._ontostore is not None
                    else "provider-owned"
                ),
            },
            "strategy": {"atlas_adapter_revision": "2"},
            "preprocessing": {
                "miniml_boundary_revision": "3.1-retained-patches-v1"
            },
        }

    @staticmethod
    def _harmonize_metadata(
        ontology_harmonizer,
        *,
        metadata: dict | list,
        publication_context: str | None,
        options: dict,
    ) -> dict:
        """Use the typed MINiML boundary and patch API when the provider supports it."""
        patch_method = getattr(
            ontology_harmonizer, "harmonize_miniml_annotations", None
        )
        apply_method = getattr(
            ontology_harmonizer, "apply_miniml_harmonization_patch", None
        )
        typed_provider = callable(patch_method) and callable(apply_method)
        declared_miniml = AtlasHarmonizer._declares_miniml(metadata)
        if not typed_provider and not declared_miniml:
            return ontology_harmonizer.harmonize_miniml_json(
                publication_context=publication_context,
                miniml_json=copy.deepcopy(metadata),
                **options,
            )

        codec = MINiMLCodec()
        decoded = codec.decode_many(metadata, strict=True)
        canonical = codec.encode_many(decoded.packages)
        document = canonical[0] if isinstance(metadata, dict) else canonical
        if not typed_provider:
            result = ontology_harmonizer.harmonize_miniml_json(
                publication_context=publication_context,
                miniml_json=copy.deepcopy(document),
                **options,
            )
            if not isinstance(result, dict) or "miniml_json" not in result:
                raise ValueError("legacy MINiML harmonizer must return miniml_json")
            verified = codec.decode_many(result["miniml_json"], strict=True)
            encoded = codec.encode_many(verified.packages)
            result["miniml_json"] = (
                encoded[0] if isinstance(metadata, dict) else encoded
            )
            return result

        result = patch_method(
            publication_context=publication_context,
            miniml_json=document,
            **options,
        )
        applied = apply_method(document, result["harmonization_patch"])
        verified = codec.decode_many(applied, strict=True)
        encoded = codec.encode_many(verified.packages)
        result["miniml_json"] = encoded[0] if isinstance(metadata, dict) else encoded
        return result

    @staticmethod
    def _declares_miniml(metadata) -> bool:
        values = metadata if isinstance(metadata, list) else [metadata]
        return bool(values) and all(
            isinstance(value, dict)
            and ("miniml_schema_version" in value or "mage_tab" in value)
            for value in values
        )

    def _preferred_ontology_ids(self) -> list[str]:
        store = self._ontostore
        if store is None and self._ontology_harmonizer_instance is not None:
            store = getattr(self._ontology_harmonizer_instance, "ontostore", None)
        return list(getattr(store, "preferred_ontology_ids", ()) or ())

    def publication_context(self, record: dict) -> str | None:
        contexts = []

        for publication in record.get("publications", []):
            parts = []
            title = str(publication.get("title", "") or "").strip()
            abstract = str(publication.get("abstractText", "") or "").strip()

            if title:
                parts.append(f"Title: {title}")
            if abstract:
                parts.append(f"Abstract: {abstract}")
            if parts:
                contexts.append("\n".join(parts))

        return "\n\n".join(contexts) or None

    def harmonize_jsons(
        self,
        datasets: dict,
        details_out: str | None = None,
        harmonization_options: dict | None = None,
    ) -> dict:
        result, _ = self.harmonize_datasets(
            datasets=datasets,
            details_out=details_out,
            harmonization_options=harmonization_options,
        )
        return result

    def _ontology_harmonizer(self):
        if self._ontology_harmonizer_instance is not None:
            return self._ontology_harmonizer_instance

        if self._ontology_harmonizer_factory is not None:
            self._ontology_harmonizer_instance = self._ontology_harmonizer_factory()
            return self._ontology_harmonizer_instance

        from agentic_curator import OntologyHarmonizer
        from agentic_curator.curators.ontology_harmonizer import OntoStore

        if self._ontostore is None:
            self._ontostore = OntoStore(resource_profile=self._resource_profile)
            parameters = inspect.signature(OntologyHarmonizer).parameters.values()
            supports_ontostore = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                or parameter.name == "ontostore"
                for parameter in parameters
            )
            self._ontology_harmonizer_instance = (
                OntologyHarmonizer(ontostore=self._ontostore)
                if supports_ontostore
                else OntologyHarmonizer()
            )
        else:
            self._ontology_harmonizer_instance = OntologyHarmonizer(
                ontostore=self._ontostore
            )
        return self._ontology_harmonizer_instance

    def _preflight_credentials(self) -> None:
        if self._credential_checker is None or self._credentials_checked:
            return
        self._credential_checker.check()
        self._credentials_checked = True

    @classmethod
    def _validate_harmonization_options(cls, options: dict) -> None:
        removed = sorted(cls.REMOVED_HARMONIZATION_OPTIONS.intersection(options))
        if removed:
            joined = ", ".join(removed)
            raise ValueError(
                f"removed harmonization option(s): {joined}; use the "
                "stage-specific target, direct, RAG, OLS, and field controls"
            )

    @classmethod
    def _requires_model_credentials(cls, options: dict) -> bool:
        controls = {**cls.MODEL_STAGE_DEFAULTS, **options}
        return bool(
            controls["target_checker"]
            or controls["direct_lookup_judge"]
            or controls["rag_lookup"]
            or (controls["ols_lookup"] and controls["ols_lookup_judge"])
            or controls["field_assignment_judge"]
        )
