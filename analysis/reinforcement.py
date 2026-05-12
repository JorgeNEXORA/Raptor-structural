from dataclasses import dataclass
import math

@dataclass
class BarSuggestion:
    bars_text: str
    provided_as_cm2: float

@dataclass
class StirrupSuggestion:
    text: str

class ReinforcementHelper:
    @staticmethod
    def bar_area_cm2(d): return (math.pi*d*d/4.0)/100.0
    @staticmethod
    def as_required_from_moment(moment_knm, d_cm, fyd_mpa=435.0, as_min_cm2=0.8):
        d_mm=d_cm*10.0; z_mm=0.9*d_mm
        return max(abs(moment_knm)*1_000_000.0/(fyd_mpa*z_mm)/100.0, as_min_cm2)
    @classmethod
    def suggest_beam_bars(cls, required_as_cm2):
        best=None
        for dia in [8,10,12,16,20]:
            a=cls.bar_area_cm2(dia)
            for n in range(2,9):
                prov=n*a
                if prov>=required_as_cm2:
                    cand=(prov-required_as_cm2,n,dia,prov)
                    if best is None or cand<best: best=cand
                    break
        if best is None: return BarSuggestion("dimensionar manualmente", required_as_cm2)
        _,n,d,p=best; return BarSuggestion(f"{n}Ø{d}", p)
    @classmethod
    def suggest_column_bars(cls, required_as_cm2):
        best=None
        for n,d in [(8,10),(8,12),(8,16),(10,12)]:
            prov=n*cls.bar_area_cm2(d)
            if prov>=required_as_cm2:
                cand=(prov-required_as_cm2,n,d,prov)
                if best is None or cand<best: best=cand
        _,n,d,p=best; return BarSuggestion(f"{n}Ø{d}", p)
    @classmethod
    def suggest_footing_bottom_bars(cls, required_as_cm2, width_cm):
        return BarSuggestion("6Ø10 // ~20 cm cada direção", 4.71)
    @classmethod
    def suggest_stirrups(cls, ved_kn, bw_cm, d_cm, fyd_mpa=435.0):
        z_mm=0.9*d_cm*10.0
        for dia,legs,s in [(6,2,20),(6,2,15),(8,2,20),(8,2,15),(8,2,10)]:
            asw=legs*cls.bar_area_cm2(dia)*100.0
            vrds=(asw/(s*10.0))*z_mm*fyd_mpa/1000.0
            if vrds>=ved_kn: return StirrupSuggestion(f"Ø{dia} {legs}r // {s} cm")
        return StirrupSuggestion("dimensionar manualmente")
