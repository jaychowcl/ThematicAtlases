"""Deterministic projections of completed work; no provider or model calls."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
from ThematicAtlases.runtime.contracts import validate_trace
from ThematicAtlases.runtime.snapshots import read_checkpoint_snapshot
from ThematicAtlases.runtime.evidence import referenced_text

STAGES = ('search_pages', 'search_queries', 'query_generation', 'datalinks',
          'publication_text', 'pubmed_gds_links', 'gds_summaries', 'geo_resolution',
          'metadata_conversion', 'thematic_review', 'harmonization')


def harmonization_input_hash(metadata, publication_context):
    value = json.dumps([metadata, publication_context], sort_keys=True, default=repr)
    return hashlib.sha256(value.encode()).hexdigest()


class SnapshotStore:
    """Read-only checkpoint interface backed by a consistent SQLite transaction."""
    def __init__(self, directory):
        self.path = Path(directory) / 'atlas_run.sqlite3'
        snapshot = read_checkpoint_snapshot(directory, stages=STAGES)
        self._meta = {k: json.loads(v) for k, v in snapshot.metadata.items()}
        self._items = tuple({**r, 'key': r['item_key'],
                             'payload': json.loads(r['payload']) if r['payload'] else None}
                            for r in snapshot.items)

    def items(self, stage):
        return deepcopy([r for r in self._items if r['stage'] == stage])

    def get(self, stage, key):
        return next((r for r in self.items(stage) if r['key'] == key), None)

    def get_meta(self, key, default=None):
        return deepcopy(self._meta.get(key, default))


class CheckpointViews:
    def __init__(self, store, manifest=None):
        self.store = store
        self.manifest = manifest or {}

    @classmethod
    def from_directory(cls, directory):
        manifest = validate_trace(directory)
        return cls(SnapshotStore(directory), manifest)

    def resolved_queries(self):
        key = self.store.get_meta("resolved_query_key")
        saved = self.store.get("query_generation", key) if key else None
        return list((saved or {}).get("payload", {}).get("queries", self.manifest.get("query") or []))

    def publications(self):
        from ThematicAtlases.integrations.europe_pmc import EuropePMCWrapper
        publications = [deepcopy(publication) for page in self.store.items('search_pages')
            if page['status'] == 'available'
            for publication in (page.get('payload') or {}).get('publications', [])]
        return EuropePMCWrapper()._deduplicate_publications(publications,
            include_query_list=len(self.resolved_queries()) > 1 or len(self.store.items('search_queries')) > 1)

    def discovery(self, *, wrapper=None, publications=None):
        from ThematicAtlases.integrations.europe_pmc import EuropePMCWrapper
        wrapper = wrapper or EuropePMCWrapper()
        rows = [row for item in self.store.items('datalinks') if item['status']=='available'
                for row in (item.get('payload') or {}).get('rows', [])]
        records = [record for item in self.store.items('publication_text')
                   for record in (item.get('payload') or {}).get('records', [])]
        graph_owner = wrapper if hasattr(wrapper, "accessions_from_link_graph") else EuropePMCWrapper()
        graph = graph_owner.accessions_from_link_graph(
            self.publications() if publications is None else publications,
            checkpoint_store=self.store, cached_only=True)
        merger = wrapper if hasattr(wrapper, "merge_accessions") else EuropePMCWrapper()
        return merger.merge_accessions(wrapper.accessions_from_datalinks(rows), records, graph)

    def metadata(self, *, collector=None, accessions=None):
        from ThematicAtlases.collector import AtlasCollector
        from ThematicAtlases.integrations.conversion import MetadataConversionAdapter
        from ThematicAtlases.integrations.geo import GEOWrapper
        records = self.discovery() if accessions is None else accessions
        if collector is not None:
            return collector.available_accession_metadata(
                jsons=records, metadata_repositories=self.manifest.get('metadata_repositories'),
                checkpoint_store=self.store)
        # Projection intentionally uses the saved conversion settings, so readers
        # can inspect a trace even after an installed MSC version has changed.
        collector = AtlasCollector()
        selected = collector.filter_accessions(records, self.manifest.get('metadata_repositories'))
        result = []
        for record in selected:
            repository = collector.metadata_repository(record, self.manifest.get('metadata_repositories'))
            if repository is None:
                result.append(record)
                continue
            resolved = GEOWrapper()._resolve_records([record], self.store, cached_only=True) if repository=='geo' else [record]
            for item in resolved:
                if repository == 'geo' and not str(item.get('datalink_id', '')).upper().startswith('GSE'):
                    result.append(item)
                    continue
                accession = str(item.get('datalink_id') or '').upper()
                saved = self.store.get('metadata_conversion', f'{repository}:{accession}')
                adapter = MetadataConversionAdapter(repository, converter=object())
                result.extend(adapter.records(item, saved))
        return collector._deduplicate_repository_aliases(result)

    def publication_texts(self, *, contexts=None):
        from ThematicAtlases.filterer import AtlasFilterer, PublicationTextReviewer
        filterer = AtlasFilterer()
        texts = {}
        for item in self.store.items('publication_text'):
            publication = (item.get('payload') or {}).get('publication') or {}
            ref = filterer.publication_text_ref(publication) or item['key'].removeprefix('ref:')
            texts[ref] = {k: publication[k] for k in ('text','text_source','full_text_status') if k in publication}
            texts[ref]['checkpoint_key'] = item['key']
        for item in self.store.items('thematic_review'):
            payload = item.get('payload') or {}
            ref = payload.get('publication_ref')
            reference = payload.get('text_ref')
            text = referenced_text(self.store, reference) if reference else None
            if not ref or text is None:
                continue
            if contexts is not None:
                reviewer = PublicationTextReviewer()
                identity = payload.get('reviewer_identity', {})
                if identity.get('max_review_criteria', 12) != self.manifest.get('max_review_criteria', 12):
                    continue
                theme = self.manifest.get('theme')
                strategy = self.manifest.get('review_strategy', 'direct')
                criteria = self.store.get_meta(reviewer._criteria_checkpoint_key(
                    theme=theme, strategy=strategy, reviewer_identity=identity), {})
                input_hash = reviewer._review_input_hash(
                    text, contexts.get(ref, {}), theme, strategy, identity,
                    criteria.get('criteria'))
                if payload.get('input_hash') != input_hash:
                    continue
            texts.setdefault(ref, text)['agentic_curator'] = payload.get('review', {})
        return texts

    def review(self, *, accessions=None):
        from ThematicAtlases.filterer import AtlasFilterer, PublicationTextReviewer
        from ThematicAtlases.unsupported_accessions import partition_unsupported_accessions
        records = self.metadata() if accessions is None else accessions
        records, unsupported = partition_unsupported_accessions(records)
        context_records = records
        if self.manifest.get('review_before_metadata'):
            from ThematicAtlases.collector import AtlasCollector
            context_records = AtlasCollector().filter_accessions(
                self.discovery(), self.manifest.get('metadata_repositories'))
            context_records, _ = partition_unsupported_accessions(context_records)
        context_records = AtlasFilterer().accessions_with_publication_text_refs(
            context_records, self.publication_texts(contexts={}))
        contexts = PublicationTextReviewer().publication_review_contexts(context_records)
        texts = self.publication_texts(contexts=contexts)
        records = AtlasFilterer().accessions_with_publication_text_refs(records, texts)
        if self.manifest.get('thematic_review', bool(self.manifest.get('theme'))):
            records, texts = PublicationTextReviewer().filtered_result(
                accessions=records, publication_texts=texts,
                review_filter=self.manifest.get('review_filter', 'none'),
                prune_accessions=self.manifest.get('prune_accessions', False))
        return {'accessions': records, 'publication_texts': texts, 'unsupported_accessions': unsupported}

    def harmonization(self, *, datasets=None):
        from ThematicAtlases.harmonizer import AtlasHarmonizer
        from ThematicAtlases.runtime_contracts import not_run_status

        datasets = deepcopy(self.review() if datasets is None else datasets)
        owner = AtlasHarmonizer()
        details = []
        outcomes = sorted(self.store.items('harmonization'), key=lambda item:
            ((item.get('payload') or {}).get('reconstruction') or {}).get('recorded_at_ns', 0),
            reverse=True)
        for record in datasets['accessions']:
            source = record.get('accession_metadata')
            accession = record.get('datalink_id', '')
            reason = owner._eligibility_reason(record)
            if reason is None and not isinstance(source, (dict, list)):
                reason = 'metadata_unavailable'
            if reason is not None:
                status = not_run_status(terminal_reason=reason).to_dict()
                record.update(ontology_harmonization_run_status='not_run',
                              ontology_harmonization_status=status)
                record.pop('ontology_harmonization_error', None)
                details.append({'datalink_id': accession, 'run_status': 'not_run',
                                'status': status})
                continue
            input_hash = harmonization_input_hash(source, owner.publication_context(record))
            for item in outcomes:
                payload = item.get('payload') or {}
                projection = payload.get('reconstruction') or {}
                if 'harmonization_options' in self.manifest:
                    options = {k: v for k, v in projection.get('options', {}).items() if k != 'review_decisions'}
                    if options != (self.manifest.get('harmonization_options') or {}):
                        continue
                if projection.get('input_hash') != input_hash:
                    continue
                saved_details = projection.get('details') or []
                detail = next((d for d in saved_details if d['datalink_id'] == accession),
                              saved_details[0] if saved_details else None)
                if detail is None:
                    continue
                detail = deepcopy({**detail, 'datalink_id': accession})
                record.update(ontology_harmonization_run_status=detail['run_status'],
                              ontology_harmonization_status=detail['status'])
                if detail['run_status'] == 'completed':
                    record.update(accession_metadata=payload['miniml_json'],
                        ontology_harmonization_review_required=bool(payload.get('review_required')),
                        ontology_harmonization_pending_review=list(payload.get('pending_review') or []))
                    record.pop('ontology_harmonization_quality_status', None)
                    record.pop('ontology_harmonization_error', None)
                elif detail['run_status'] == 'error':
                    record['ontology_harmonization_error'] = detail['error']
                details.append(detail)
                break
        return datasets, details
