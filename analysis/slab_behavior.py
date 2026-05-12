from math import hypot
from core.model import SlabType

class SlabBehaviorEstimator:
    """
    Heurística prática:
    - calcula bbox, área poligonal e compacidade
    - estima vãos principais x/y
    - se razão longo/curto <= 1.50 -> two_way
    - caso contrário -> one_way
    - direção principal = menor vão (x ou y)
    """

    def _bbox(self, slab):
        pts = slab.polygon_points or []
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return min(xs), min(ys), max(xs), max(ys)
        return 0.0, 0.0, slab.span_m, slab.span_m

    def estimate(self, slab):
        min_x, min_y, max_x, max_y = self._bbox(slab)
        dx = max(max_x - min_x, 0.01)
        dy = max(max_y - min_y, 0.01)

        short_span = min(dx, dy)
        long_span = max(dx, dy)
        ratio = long_span / short_span if short_span > 0 else 99.0

        direction = "x" if dx <= dy else "y"

        # polígonos muito recortados mantêm one_way por segurança do MVP
        area = slab.area_m2 if slab.area_m2 else dx * dy
        compactness = area / (dx * dy) if dx * dy > 0 else 1.0

        if ratio <= 1.50 and compactness >= 0.85:
            slab.slab_type = SlabType.TWO_WAY
        else:
            slab.slab_type = SlabType.ONE_WAY

        slab.direction = direction
        slab.span_m = short_span
        return {
            "dx": dx,
            "dy": dy,
            "ratio": ratio,
            "compactness": compactness,
            "slab_type": slab.slab_type.value,
            "direction": slab.direction,
            "span_m": slab.span_m,
        }
