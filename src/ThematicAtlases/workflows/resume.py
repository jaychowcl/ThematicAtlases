"""Resume by replaying shared stages over completed SQLite work items."""
from agentic_curator.review_decisions import ReviewDecisionFile
from ThematicAtlases.pipeline import AtlasStagePause, validate_stop_after
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.runtime.contracts import validate_trace
from ThematicAtlases.runtime.views import CheckpointViews


class ResumeAtlasWorkflow:
    def __init__(self, context):
        self.context = context

    def run(self, dev_out_dir='.dev', run_id=None, out=None, stop_before_review=False,
            retry_stages=None, retry_items=None, retry_degraded_stages=None,
            review_decisions=None, stop_after=None):
        context = self.context
        stop_after = validate_stop_after(stop_after)
        directory = context._resume_run_directory(dev_out_dir=dev_out_dir, run_id=run_id)
        manifest = validate_trace(directory)
        if review_decisions is not None:
            decision = ReviewDecisionFile.from_mapping(review_decisions)
            if decision.run_id != directory.name:
                raise ValueError(f'review decision file belongs to run {decision.run_id!r}, not {directory.name!r}')
            review_decisions = decision.to_mapping()
        trace = DevTraceWriter.existing(directory)
        store = trace.checkpoint_store
        store.request_retries(stages=retry_stages or (), items=retry_items,
                              degraded_stages=retry_degraded_stages or ())
        if not any((retry_stages, retry_items, retry_degraded_stages, review_decisions)):
            paused = context._already_completed_pause(trace, stop_after)
            if paused is not None:
                return paused
        trace.run_store.set_run_status(directory.name, 'running')
        trace.run_store.record_event(directory.name, 'resume_started', detail={
            'retry_stages': list(retry_stages or ()), 'retry_items': retry_items or {},
            'retry_degraded_stages': list(retry_degraded_stages or ()), 'stop_after': stop_after})
        context._reconcile_checkpoint_contracts(store)
        output = out if out is not None else manifest.get('atlas_out')
        options = {name: manifest[name] for name in (
            'query', 'theme', 'review_filter', 'review_strategy', 'max_review_criteria', 'prune_accessions',
            'metadata_repositories', 'max_publications', 'max_publications_per_query',
            'collect_metadata', 'generate_queries', 'max_generated_queries',
            'review_before_metadata', 'scrape_fulltext_accessions') if name in manifest}
        options.update(file=manifest.get('query_file'), out=None,
                       _trace_writer=trace,
                       _thematic_review=manifest.get('thematic_review', manifest.get('theme') is not None),
                       stop_before_review=stop_before_review or stop_after=='metadata')
        if stop_after is not None:
            options['stop_after'] = stop_after
        # Discovery reconstruction and cached metadata/text/review operations are
        # shared with create, so ordering, filtering and pruning cannot diverge.
        try:
            datasets = context._collect_for_internal(options)
        except AtlasStagePause as pause:
            return context._pause_at_stage(trace=trace, stage=pause.stage, result=pause.result)
        if stop_after in {'metadata', 'review'}:
            return context._pause_at_stage(trace=trace, stage=stop_after, result=datasets)
        if stop_before_review or manifest.get('command') == 'collect-datasets':
            return context._write_resumed_outputs(result=datasets, out=output, trace=trace,
                                                 artifact_role='collection_snapshot')
        if context._cache_ontologies:
            context._preflight_credentials()
        context._prepare_ontology_cache()
        store.set_meta('pipeline_position', {'stage':'harmonization', 'state':'running'})
        result, details = context._harmonizer.harmonize_datasets(
            datasets=datasets, details_out=manifest.get('harmonization_details_out'),
            harmonization_options=manifest.get('harmonization_options'),
            **({'review_decisions':review_decisions} if review_decisions is not None else {}),
            **context._checkpoint_keyword(context._harmonizer.harmonize_datasets, store))
        trace.write('04_harmonization_details.json', details)
        store.set_meta('pipeline_position', {'stage':'harmonization', 'state':'complete'})
        if stop_after == 'harmonization':
            return context._pause_at_stage(trace=trace, stage=stop_after, result=result)
        return context._write_resumed_outputs(result=result, out=output, trace=trace)
