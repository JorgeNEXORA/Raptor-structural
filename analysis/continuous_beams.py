from dataclasses import dataclass
from typing import List

@dataclass
class ContinuousSpan:
    id: str
    length_m: float
    gk_kn_m: float
    qk_kn_m: float

@dataclass
class ContinuousSpanResult:
    span_id: str
    m_left_knm: float
    m_right_knm: float
    m_pos_knm: float
    v_left_kn: float
    v_right_kn: float

class ContinuousBeamAnalyzer:
    def __init__(self, gamma_g=1.35, gamma_q=1.50):
        self.gamma_g=gamma_g; self.gamma_q=gamma_q
    def qd(self, s): return self.gamma_g*s.gk_kn_m+self.gamma_q*s.qk_kn_m
    def analyze(self, spans: List[ContinuousSpan]):
        results=[]; support_m=[]
        n=len(spans)
        for i,s in enumerate(spans):
            qd=self.qd(s); l=s.length_m
            if n==1:
                ml=0.0; mr=0.0; mp=qd*l*l/8.0
            else:
                if i==0:
                    ml=0.0; mr=qd*l*l/10.0; mp=qd*l*l/10.0
                elif i==n-1:
                    ml=-qd*l*l/10.0; mr=0.0; mp=qd*l*l/14.0
                else:
                    ml=-qd*l*l/10.0; mr=qd*l*l/10.0; mp=qd*l*l/16.0
            vl=qd*l/2.0; vr=qd*l/2.0
            results.append(ContinuousSpanResult(s.id, ml, mr, max(mp,0.0), vl, vr))
        support_m=[results[0].m_left_knm]
        for r in results: support_m.append(r.m_right_knm)
        return {"support_moments_knm": support_m, "spans": results}
