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
        source_accessions = [dict(record) for record in datasets.get("accessions", [])]
        accessions = list(source_accessions)
        details: list[dict | None] = [None] * len(accessions)
        harmonization_options = dict(harmonization_options or {})
        self._validate_harmonization_options(harmonization_options)
        work_by_key = {}
        ontology_harmonizer = None
        execution_identity = None
        typed_review_decisions = (
            ReviewDecisionFile.from_mapping(review_decisions)
            if review_decisions is not None
            else None
        )
        matched_review_source = False

        for index, record in enumerate(accessions):
            metadata = record.get("accession_metadata")
            datalink_id = record.get("datalink_id", "")

            eligibility_reason = self._eligibility_reason(record)
            if eligibility_reason is not None:
                status = not_run_status(
                    terminal_reason=eligibility_reason
                ).to_dict()
                record["ontology_harmonization_run_status"] = "not_run"
                record["ontology_harmonization_status"] = status
                record.pop("ontology_harmonization_error", None)
                details[index] = {
                    "datalink_id": datalink_id,
                    "run_status": "not_run",
                    "status": status,
                }
                continue

            if not isinstance(metadata, (dict, list)):
                status = not_run_status(
                    terminal_reason="metadata_unavailable"
                ).to_dict()
                record["ontology_harmonization_run_status"] = "not_run"
                record["ontology_harmonization_status"] = status
                record.pop("ontology_harmonization_error", None)
                details[index] = {
                    "datalink_id": datalink_id,
                    "run_status": "not_run",
                    "status": status,
                }
                continue

            context = self.publication_context(record)
            if ontology_harmonizer is None:
                if self._requires_model_credentials(harmonization_options):
                    self._preflight_credentials()
                ontology_harmonizer = self._ontology_harmonizer()
                execution_identity = self._harmonization_execution_identity(
                    ontology_harmonizer
                )
            item_options = dict(harmonization_options)
            if typed_review_decisions is not None:
                try:
                    source_fingerprint = miniml_source_fingerprint(metadata)
                except (TypeError, ValueError):
                    source_fingerprint = None
                if source_fingerprint == typed_review_decisions.source_fingerprint:
                    item_options["review_decisions"] = typed_review_decisions.to_mapping()
                    matched_review_source = True
            key = self._work_key(
                metadata=metadata,
                publication_context=context,
                harmonization_options=item_options,
                execution_identity=execution_identity,
            )
            work_by_key.setdefault(
                key,
                {
                    "work_key": hashlib.sha256(key.encode("utf-8")).hexdigest(),
                    "metadata": metadata,
                    "publication_context": context,
                    "execution_identity": execution_identity,
                    "harmonization_options": item_options,
                    "indices": [],
                },
            )["indices"].append(index)

        if typed_review_decisions is not None and not matched_review_source:
            raise ValueError("review decision source fingerprint is stale")

        if work_by_key:
            if ontology_harmonizer is None:
                raise RuntimeError("harmonization provider was not initialized")
            work_items = list(work_by_key.values())
            for position, item in enumerate(work_items, start=1):
                item["position"] = position
                item["total"] = len(work_items)

            def run(item):
                logger.info(
                    "Atlas ontology harmonization progress work_index=%s work_total=%s accession_count=%s",
                    item["position"],
                    item["total"],
                    len(item["indices"]),
                )
                try:
                    harmonization = self._harmonize_metadata(
                        ontology_harmonizer,
                        metadata=item["metadata"],
                        publication_context=item["publication_context"],
                        options=item["harmonization_options"],
                    )
                    self._validated_operation_status(harmonization)
                    return harmonization, None
                except Exception as error:
                    return None, error

            def apply_outcome(item, harmonization, error, *, cached=False):
                for index in item["indices"]:
                    record = accessions[index]
                    datalink_id = record.get("datalink_id", "")
                    if error is not None:
                        logger.error(
                            "Atlas ontology harmonization failed datalink_id=%r error_type=%s",
                            datalink_id,
                            type(error).__name__,
                        )
                        retryable = is_retryable_error(error)
                        status = failed_status(
                            error,
                            provider="agentic_curator",
                            stage="harmonization",
                            item_id=str(datalink_id) or None,
                            retryable=retryable,
                            terminal_reason="harmonization_failed",
                        ).to_dict()
                        safe_error = status["errors"][0]
                        record["ontology_harmonization_run_status"] = "error"
                        record["ontology_harmonization_status"] = status
                        record["ontology_harmonization_error"] = safe_error
                        details[index] = {
                            "datalink_id": datalink_id,
                            "run_status": "error",
                            "status": status,
                            "error": safe_error,
                        }
                        continue

                    status = self._validated_operation_status(harmonization).to_dict()
                    record["accession_metadata"] = harmonization["miniml_json"]
                    record["ontology_harmonization_run_status"] = "completed"
                    record["ontology_harmonization_status"] = status
                    record.pop("ontology_harmonization_quality_status", None)
                    record.pop("ontology_harmonization_error", None)
                    record["ontology_harmonization_review_required"] = bool(
                        harmonization.get("review_required")
                    )
                    record["ontology_harmonization_pending_review"] = list(
                        harmonization.get("pending_review") or []
                    )
                    details[index] = {
                        "datalink_id": datalink_id,
                        "run_status": "completed",
                        "harmonization_targets": harmonization.get(
                            "harmonization_targets", []
                        ),
                        "workflow": harmonization.get("workflow"),
                        "target_paths": harmonization.get("target_paths"),
                        "harmonization_execution_identity": item[
                            "execution_identity"
                        ],
                        "status": status,
                    }
                    if "preferred_ontology_ids" in harmonization:
                        details[index]["preferred_ontology_ids"] = harmonization[
                            "preferred_ontology_ids"
                        ]
                    if "controls" in harmonization:
                        details[index]["controls"] = harmonization["controls"]
                    for field in (
                        "harmonization_patch",
                        "pending_review",
                        "extension_registry",
                        "review_required",
                        "review_decisions",
                    ):
                        if field in harmonization:
                            details[index][field] = harmonization[field]

                if checkpoint_store is None or cached:
                    return
                if error is None:
                    checkpoint_store.put(
                        "harmonization",
                        item["work_key"],
                        item["position"],
                        "available",
                        payload=harmonization,
                    )
                else:
                    retryable = is_retryable_error(error)
                    persisted_error = failed_status(
                        error,
                        provider="agentic_curator",
                        stage="harmonization",
                        item_id=str(item["work_key"]),
                        retryable=retryable,
                        terminal_reason="harmonization_failed",
                    ).errors[0].to_dict()
                    checkpoint_store.put(
                        "harmonization",
                        item["work_key"],
                        item["position"],
                        "retryable_error"
                        if retryable
                        else "terminal_error",
                        error=json.dumps(persisted_error, sort_keys=True),
                        error_type=type(error).__name__,
                        failure_category=failure_category(error),
                    )

            pending = []
            for item in work_items:
                checkpoint = (
                    checkpoint_store.get("harmonization", item["work_key"])
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] == "available":
                    apply_outcome(item, checkpoint["payload"], None, cached=True)
                elif checkpoint and checkpoint["status"] == "terminal_error":
                    apply_outcome(
                        item,
                        None,
                        RuntimeError(checkpoint["error"] or "harmonization failed"),
                        cached=True,
                    )
                else:
                    pending.append(item)

            if self._max_workers == 1:
                for item in pending:
                    harmonization, error = run(item)
                    apply_outcome(item, harmonization, error)
            else:
                with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                    futures = {executor.submit(run, item): item for item in pending}
                    for future in as_completed(futures):
                        item = futures[future]
                        harmonization, error = future.result()
                        apply_outcome(item, harmonization, error)

        details = [detail for detail in details if detail is not None]

        result = {**datasets, "accessions": accessions}
        if details_out is not None:
            Path(details_out).parent.mkdir(parents=True, exist_ok=True)
            with open(details_out, "w", encoding="utf-8") as handle:
                json.dump(details, handle, indent=2)

        logger.info(
            "Atlas ontology harmonization stats accessions=%s completed=%s not_run=%s errors=%s details_path=%s",
            len(accessions),
            sum(item["run_status"] == "completed" for item in details),
            sum(item["run_status"] == "not_run" for item in details),
            sum(item["run_status"] == "error" for item in details),
            details_out,
        )
        return result, details

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
            "strategy": {"atlas_adapter_revision": "1"},
            "preprocessing": {"miniml_boundary_revision": "3.0"},
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
