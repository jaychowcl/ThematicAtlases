import logging

logger = logging.getLogger(__name__)


class ArrayExpressWrapper:
    def collect_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        records = [
            {
                **record,
                "metadata_repository": "arrayexpress",
                "metadata_source": "placeholder",
                "metadata_status": "placeholder",
                "accession_metadata": None,
            }
            for record in jsons
        ]
        logger.info(
            "ArrayExpress placeholder metadata stats input_records=%s output_records=%s",
            len(jsons),
            len(records),
        )
        return records
