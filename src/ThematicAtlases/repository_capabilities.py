"""Versioned end-to-end repository capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping


CAPABILITY_CONTRACT_VERSION = "1.0"
REQUIRED_CONTRACT_TESTS = (
    "collection",
    "review",
    "harmonization",
    "projection",
    "publication",
)


@dataclass(frozen=True)
class RepositoryCapability:
    repository_id: str
    accession_patterns: tuple[str, ...]
    review_accession_patterns: tuple[str, ...]
    provider: str
    metadata_adapter: str
    review_identity_rule: str
    harmonization_supported: bool
    projection_project_id: str
    study_id_rule: str
    required_contract_tests: tuple[str, ...] = REQUIRED_CONTRACT_TESTS
    terminal_limitations: tuple[str, ...] = ()
    contract_version: str = CAPABILITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != CAPABILITY_CONTRACT_VERSION:
            raise ValueError(
                "Repository capability contract_version must be "
                f"{CAPABILITY_CONTRACT_VERSION}."
            )
        for name in (
            "repository_id",
            "provider",
            "metadata_adapter",
            "review_identity_rule",
            "projection_project_id",
            "study_id_rule",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"Repository capability {name} must not be blank")
        if not self.accession_patterns or not self.review_accession_patterns:
            raise ValueError("Repository capability accession patterns must not be empty")
        for pattern in (*self.accession_patterns, *self.review_accession_patterns):
            re.compile(pattern)
        if set(self.required_contract_tests) != set(REQUIRED_CONTRACT_TESTS):
            raise ValueError(
                "Repository capability must declare every end-to-end contract test"
            )

    def matches(self, accession: object) -> bool:
        normalized = _normalized_accession(accession)
        return any(re.fullmatch(pattern, normalized) for pattern in self.accession_patterns)

    def review_identity(self, accession: object) -> str | None:
        normalized = _normalized_accession(accession)
        if self.review_identity_rule != "dataset_accession":
            raise ValueError(
                f"Unsupported review identity rule: {self.review_identity_rule!r}"
            )
        return normalized if any(
            re.fullmatch(pattern, normalized)
            for pattern in self.review_accession_patterns
        ) else None


DEFAULT_REPOSITORY_CAPABILITIES: Mapping[str, RepositoryCapability] = (
    MappingProxyType(
        {
            "geo": RepositoryCapability(
                repository_id="geo",
                accession_patterns=(r"GSE\d+", r"GSM\d+", r"GPL\d+", r"GDS\d+"),
                review_accession_patterns=(r"GSE\d+",),
                provider="NCBI GEO",
                metadata_adapter="ThematicAtlases.wrappers.geo.GEOWrapper",
                review_identity_rule="dataset_accession",
                harmonization_supported=True,
                projection_project_id="geo",
                study_id_rule="dataset_accession",
            ),
            "arrayexpress": RepositoryCapability(
                repository_id="arrayexpress",
                accession_patterns=(
                    r"E-MTAB-\d+",
                    r"E-GEOD-\d+",
                    r"E-MEXP-\d+",
                ),
                review_accession_patterns=(
                    r"E-MTAB-\d+",
                    r"E-GEOD-\d+",
                    r"E-MEXP-\d+",
                ),
                provider="BioStudies ArrayExpress",
                metadata_adapter="ThematicAtlases.wrappers.ae.ArrayExpressWrapper",
                review_identity_rule="dataset_accession",
                harmonization_supported=True,
                projection_project_id="arrayexpress",
                study_id_rule="dataset_accession",
            ),
        }
    )
)


class RepositoryCapabilityRegistry:
    """Immutable resolver used by every repository-sensitive stage."""

    def __init__(
        self,
        capabilities: Mapping[str, RepositoryCapability] | None = None,
    ) -> None:
        values = dict(capabilities or DEFAULT_REPOSITORY_CAPABILITIES)
        for repository_id, capability in values.items():
            if repository_id != capability.repository_id:
                raise ValueError(
                    "Repository capability key must equal its repository_id"
                )
        self._capabilities = MappingProxyType(values)

    @property
    def capabilities(self) -> Mapping[str, RepositoryCapability]:
        return self._capabilities

    @property
    def repository_ids(self) -> tuple[str, ...]:
        return tuple(self._capabilities)

    def require(self, repository_id: object) -> RepositoryCapability:
        normalized = str(repository_id or "").strip().casefold()
        try:
            return self._capabilities[normalized]
        except KeyError as error:
            raise ValueError(f"Unsupported repository: {repository_id!r}") from error

    def for_accession(self, accession: object) -> RepositoryCapability:
        matches = [
            capability
            for capability in self._capabilities.values()
            if capability.matches(accession)
        ]
        if not matches:
            raise ValueError(f"Unsupported repository accession: {accession!r}")
        if len(matches) != 1:
            raise ValueError(f"Ambiguous repository accession: {accession!r}")
        return matches[0]

    def review_identity(self, accession: object) -> str | None:
        try:
            capability = self.for_accession(accession)
        except ValueError:
            return None
        return capability.review_identity(accession)


def _normalized_accession(accession: object) -> str:
    return str(accession or "").strip().upper()


__all__ = [
    "CAPABILITY_CONTRACT_VERSION",
    "DEFAULT_REPOSITORY_CAPABILITIES",
    "RepositoryCapability",
    "RepositoryCapabilityRegistry",
]
