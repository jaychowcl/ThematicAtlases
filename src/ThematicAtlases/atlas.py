
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


class Atlas():
    def __init__(self, metadata: dict):
        pass

    def collect_jsons(self) -> list[dict]:
        return EuropePMCWrapper().collect_accessions()

    def filter_jsons(self,) -> list[dict]:
        pass

    def harmonize_jsons(self, ) -> list[dict]:
        pass
