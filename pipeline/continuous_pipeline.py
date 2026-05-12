from dataclasses import dataclass
from typing import List
from core.model import Beam, Column
from analysis.continuous_beams import ContinuousBeamAnalyzer, ContinuousSpan

@dataclass
class ContinuousLine:
    id: str
    beam_ids: List[str]

class ContinuousPipeline:
    def __init__(self, columns: List[Column], beams: List[Beam]):
        self.columns=columns; self.beams=beams; self.lookup={b.id:b for b in beams}
    def run(self):
        lines=[ContinuousLine("CL1",["B4","B5"]), ContinuousLine("CL2",["B6","B7"])]
        analyzer=ContinuousBeamAnalyzer(); results=[]
        for line in lines:
            spans=[ContinuousSpan(self.lookup[bid].id,self.lookup[bid].span_m,self.lookup[bid].total_gk(),self.lookup[bid].total_qk()) for bid in line.beam_ids]
            ana=analyzer.analyze(spans)
            for r in ana["spans"]:
                b=self.lookup[r.span_id]
                b.continuous_result={"m_left_knm":r.m_left_knm,"m_right_knm":r.m_right_knm,"m_pos_knm":r.m_pos_knm,"v_left_kn":r.v_left_kn,"v_right_kn":r.v_right_kn}
            results.append((line,ana))
        return results
