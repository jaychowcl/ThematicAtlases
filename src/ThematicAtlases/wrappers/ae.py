class ArrayExpressWrapper:
    metadata_handler_status = "unsupported"

    def collect_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        raise NotImplementedError(
            "ArrayExpress metadata collection is not implemented; "
            "inject a metadata handler or select the geo repository"
        )
