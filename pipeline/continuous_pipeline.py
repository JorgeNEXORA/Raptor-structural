from dataclasses import dataclass
from typing import List
from core.model import Beam, Column

@dataclass
class ContinuousLine:
    id: str
    beam_ids: List[str]

class ContinuousPipeline:
    def __init__(self, columns: List[Column], beams: List[Beam]):
        try:
            self.lookup = {b.id: b for b in (beams or [])}
        except Exception:
            self.lookup = {}

    def run(self):
        return []
