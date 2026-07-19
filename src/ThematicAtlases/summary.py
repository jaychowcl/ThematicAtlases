from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path


FIXED_CHARACTERISTICS = {
    "tissues_organs": {"tissue", "organ", "organ part", "anatomical site"},
    "diseases_conditions": {"disease", "disease state", "condition", "diagnosis", "phenotype"},
}


def summary_path(atlas_path: str) -> Path:
    path = Path(atlas_path)
    stem = path.stem if path.suffix else path.name
    return path.with_name(f"{stem}.summary.json")


def build_atlas_summary(atlas: dict, atlas_path: str | None = None) -> dict:
    accessions = atlas.get("accessions", [])
    publication_texts = atlas.get("publication_texts", {})
    repositories = Counter(str(item.get("metadata_repository") or "unknown") for item in accessions)
    harmonization = Counter(
        str(item.get("ontology_harmonization_run_status") or "unknown")
        for item in accessions
    )
    reviews = Counter()
    for item in publication_texts.values():
        review = item.get("agentic_curator", {}) if isinstance(item, dict) else {}
        judgement = review.get("judgement") if isinstance(review, dict) else None
        reviews[_normalized(judgement) or "unreviewed"] += 1

    publication_keys = set()
    for accession in accessions:
        for publication in accession.get("publications", []):
            publication_keys.add(
                publication.get("publication_text_ref")
                or publication.get("pmid")
                or publication.get("pmcid")
                or publication.get("doi")
                or f"{publication.get('source', '')}:{publication.get('epmc_id', '')}"
            )

    scientific = _scientific_profile(accessions)
    return {
        "schema_version": "1.0",
        "atlas_path": atlas_path,
        "counts": {
            "accessions": len(accessions),
            "publications": len(publication_keys),
            "publication_texts": len(publication_texts),
        },
        "repositories": dict(sorted(repositories.items())),
        "review_judgements": dict(sorted(reviews.items())),
        "harmonization_run_statuses": dict(sorted(harmonization.items())),
        "scientific_profile": scientific,
    }


def _scientific_profile(accessions: list[dict]) -> dict:
    counts = {name: Counter() for name in ("organisms", "sample_sources", "tissues_organs", "diseases_conditions", "platform_technologies")}
    unknown = Counter()
    observed: dict[str, Counter] = defaultdict(Counter)
    samples_total = 0

    for accession in accessions:
        metadata = accession.get("accession_metadata")
        if not isinstance(metadata, dict):
            continue
        platforms = _platforms(metadata)
        samples = metadata.get("sample", [])
        if isinstance(samples, dict):
            samples = [samples]
        if not isinstance(samples, list):
            continue
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            samples_total += 1
            values = {name: set() for name in counts}
            characteristics: dict[str, set[str]] = defaultdict(set)
            channels = sample.get("channel", [])
            if isinstance(channels, dict):
                channels = [channels]
            for channel in channels if isinstance(channels, list) else []:
                if not isinstance(channel, dict):
                    continue
                values["sample_sources"].update(_field_values(channel, "source"))
                values["organisms"].update(_organism_values(channel))
                for tag, tag_values in _characteristics(channel).items():
                    characteristics[tag].update(tag_values)
            for tag, tag_values in characteristics.items():
                for value in tag_values:
                    observed[tag][value] += 1
                for category, tags in FIXED_CHARACTERISTICS.items():
                    if tag in tags:
                        values[category].update(tag_values)
            values["platform_technologies"].update(_sample_platforms(sample, platforms))
            for category, sample_values in values.items():
                if not sample_values:
                    unknown[category] += 1
                for value in sample_values:
                    counts[category][value] += 1

    return {
        "samples_total": samples_total,
        **{name: dict(sorted(counter.items())) for name, counter in counts.items()},
        "unknown_samples": {name: unknown[name] for name in counts},
        "observed_characteristics": {
            tag: dict(sorted(values.items())) for tag, values in sorted(observed.items())
        },
    }


def _platforms(metadata: dict) -> dict[str, set[str]]:
    result = {}
    platforms = metadata.get("platform", [])
    if isinstance(platforms, dict):
        platforms = [platforms]
    for platform in platforms if isinstance(platforms, list) else []:
        if isinstance(platform, dict):
            result[str(platform.get("iid") or platform.get("id") or "")] = set(_field_values(platform, "technology"))
    return result


def _sample_platforms(sample: dict, platforms: dict[str, set[str]]) -> set[str]:
    refs = sample.get("platform_ref", [])
    if isinstance(refs, dict):
        refs = [refs]
    result = set()
    for ref in refs if isinstance(refs, list) else []:
        key = str(ref.get("ref") or "") if isinstance(ref, dict) else str(ref)
        result.update(platforms.get(key, set()))
    if not result and len(platforms) == 1:
        result.update(next(iter(platforms.values())))
    return result


def _organism_values(channel: dict) -> set[str]:
    organisms = channel.get("hz_organism", channel.get("organism", []))
    if not isinstance(organisms, list):
        organisms = [organisms]
    result = set()
    for organism in organisms:
        if isinstance(organism, dict):
            result.update(_field_values(organism, "name"))
            result.update(_field_values(organism, "value"))
        elif _normalized(organism):
            result.add(str(organism).strip())
    return result


def _characteristics(channel: dict) -> dict[str, set[str]]:
    grouped: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"raw": set(), "harmonized": set()})
    items = channel.get("characteristics", [])
    if isinstance(items, dict):
        items = [items]
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        tag = _normalized(item.get("tag"))
        if not tag:
            continue
        harmonized = tag.startswith("hz ")
        base = tag[3:] if harmonized else tag
        values = _field_values(item, "value")
        grouped[base]["harmonized" if harmonized else "raw"].update(values)
    return {tag: parts["harmonized"] or parts["raw"] for tag, parts in grouped.items()}


def _field_values(item: dict, key: str) -> set[str]:
    value = item.get(f"hz_{key}", item.get(key))
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    result = set()
    for entry in values:
        if isinstance(entry, dict):
            entry = entry.get("value") or entry.get("name")
        if _normalized(entry):
            result.add(str(entry).strip())
    return result


def _normalized(value) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())
