from dataclasses import dataclass
from typing import List
from core.model import Beam, BeamType, Column, SlabPanel, SlabType

@dataclass
class PanelGeometry:
    id: str
    width_m: float   # dimension in X
    height_m: float  # dimension in Y
    x0: float = 0.0  # left edge X
    y0: float = 0.0  # bottom edge Y

class ModelGenerator:
    def generate_beams(self, columns: List[Column]) -> List[Beam]:
        c = {x.id:x for x in columns}
        pairs = [("P1","P4"),("P2","P5"),("P3","P6"),("P1","P2"),("P2","P3"),("P4","P5"),("P5","P6")]
        beams=[]
        for i,(a,b) in enumerate(pairs,1):
            if a not in c or b not in c:
                continue
            ca, cb = c[a], c[b]
            span=((ca.x-cb.x)**2+(ca.y-cb.y)**2)**0.5
            beams.append(Beam(id=f"B{i}", start_node=a, end_node=b, width_cm=25.0, height_cm=75.0,
                              effective_depth_cm=72.0, span_m=span, beam_type=BeamType.FRAME))
        return beams

    def generate_panels(self, columns: List[Column]) -> List[PanelGeometry]:
        xs = sorted({round(c.x, 2) for c in columns})
        ys = sorted({round(c.y, 2) for c in columns})
        panels = []
        counter = 1
        for i in range(len(xs)-1):
            for j in range(len(ys)-1):
                panels.append(PanelGeometry(
                    f"PANEL{counter}",
                    xs[i+1]-xs[i], ys[j+1]-ys[j],
                    xs[i], ys[j]))
                counter += 1
        return panels

    def create_slabs_from_panels(self, panels: List[PanelGeometry], beams: List[Beam],
                                  gk_kn_m2: float = 6.15, qk_kn_m2: float = 2.0) -> List[SlabPanel]:
        slabs=[]
        for i, p in enumerate(panels, 1):
            lx = p.width_m
            ly = p.height_m
            # Build actual corner polygon so load_distribution can find support beams
            x1, y1 = p.x0, p.y0
            x2, y2 = p.x0 + lx, p.y0 + ly
            poly = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            direction = "x" if lx <= ly else "y"
            slabs.append(SlabPanel(
                id=f"SLAB{i}",
                span_m=min(lx, ly),
                thickness_cm=27.0,
                effective_depth_cm=24.0,
                slab_type=SlabType.ONE_WAY,
                gk_kn_m2=gk_kn_m2,
                qk_kn_m2=qk_kn_m2,
                direction=direction,
                polygon_points=poly,
                area_m2=lx * ly,
            ))
        return slabs

    def apply_slab_loads(self, slabs: List[SlabPanel], slab_loads: dict):
        for slab in slabs:
            if slab.id in slab_loads:
                slab.gk_kn_m2 = slab_loads[slab.id]["gk_kn_m2"]
                slab.qk_kn_m2 = slab_loads[slab.id]["qk_kn_m2"]
