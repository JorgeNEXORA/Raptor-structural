from math import hypot

class SlabToBeamDistributor:
    def __init__(self, tol: float = 0.20):
        self.tol = tol

    def _beam_coords(self, beam, columns_by_id):
        c1 = columns_by_id[beam.start_node]
        c2 = columns_by_id[beam.end_node]
        return c1.x, c1.y, c2.x, c2.y

    def _beam_orientation(self, beam, columns_by_id):
        x1, y1, x2, y2 = self._beam_coords(beam, columns_by_id)
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        return "vertical" if dy >= dx else "horizontal"

    def _bounding_box(self, slab):
        if slab.polygon_points:
            xs = [p[0] for p in slab.polygon_points]
            ys = [p[1] for p in slab.polygon_points]
        else:
            xs = [0.0, slab.span_m]
            ys = [0.0, slab.span_m]
        return min(xs), min(ys), max(xs), max(ys)

    def _slab_edges(self, slab):
        pts = list(slab.polygon_points or [])
        if len(pts) < 2:
            return []
        return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]

    def _segments_overlap_1d(self, a1, a2, b1, b2):
        lo = max(min(a1, a2), min(b1, b2))
        hi = min(max(a1, a2), max(b1, b2))
        return max(0.0, hi - lo)

    def _beam_matches_edge(self, beam, edge, columns_by_id):
        (ex1, ey1), (ex2, ey2) = edge
        bx1, by1, bx2, by2 = self._beam_coords(beam, columns_by_id)

        beam_ori = self._beam_orientation(beam, columns_by_id)
        edge_dx = abs(ex2 - ex1)
        edge_dy = abs(ey2 - ey1)
        edge_ori = "vertical" if edge_dy >= edge_dx else "horizontal"

        if beam_ori != edge_ori:
            return 0.0

        if beam_ori == "horizontal":
            if abs(by1 - ey1) > self.tol:
                return 0.0
            return self._segments_overlap_1d(bx1, bx2, ex1, ex2)
        else:
            if abs(bx1 - ex1) > self.tol:
                return 0.0
            return self._segments_overlap_1d(by1, by2, ey1, ey2)

    def support_beams_by_edges(self, slab, beams, columns):
        cols = {c.id: c for c in columns}
        contributions = {}
        for edge in self._slab_edges(slab):
            for beam in beams:
                match_len = self._beam_matches_edge(beam, edge, cols)
                if match_len > self.tol:
                    contributions[beam.id] = contributions.get(beam.id, 0.0) + match_len
        total = sum(contributions.values())
        if total > 0:
            return {bid: val / total for bid, val in contributions.items()}
        return {}

    def support_beams_two_primary(self, slab, beams, columns):
        cols = {c.id: c for c in columns}
        min_x, min_y, max_x, max_y = self._bounding_box(slab)
        candidates = []

        for beam in beams:
            x1, y1, x2, y2 = self._beam_coords(beam, cols)
            ori = self._beam_orientation(beam, cols)
            if slab.direction == "x":
                if ori == "vertical" and (abs(x1 - min_x) <= self.tol or abs(x1 - max_x) <= self.tol):
                    if max(min(y1, y2), min_y) <= min(max(y1, y2), max_y) + self.tol:
                        candidates.append(beam.id)
            else:
                if ori == "horizontal" and (abs(y1 - min_y) <= self.tol or abs(y1 - max_y) <= self.tol):
                    if max(min(x1, x2), min_x) <= min(max(x1, x2), max_x) + self.tol:
                        candidates.append(beam.id)

        ordered = []
        seen = set()
        for bid in candidates:
            if bid not in seen:
                ordered.append(bid)
                seen.add(bid)
        ordered = ordered[:2]
        if len(ordered) == 2:
            return {ordered[0]: 0.5, ordered[1]: 0.5}
        elif len(ordered) == 1:
            return {ordered[0]: 1.0}
        return {}

    def is_irregular(self, slab):
        pts = slab.polygon_points or []
        if len(pts) < 4:
            return False
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bbox_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        poly_area = slab.area_m2 or 0.0
        if bbox_area <= 0:
            return False
        compactness = poly_area / bbox_area
        return len(pts) != 4 or compactness < 0.92

    def support_beams_for_slab(self, slab, beams, columns):
        # Híbrido:
        # - one_way regular -> 2 vigas principais
        # - irregular -> arestas
        # - two_way -> arestas
        if getattr(slab.slab_type, "value", slab.slab_type) == "two_way":
            contrib = self.support_beams_by_edges(slab, beams, columns)
            if not contrib:
                contrib = self.support_beams_two_primary(slab, beams, columns)
        elif self.is_irregular(slab):
            contrib = self.support_beams_by_edges(slab, beams, columns)
            if not contrib:
                contrib = self.support_beams_two_primary(slab, beams, columns)
        else:
            contrib = self.support_beams_two_primary(slab, beams, columns)
            if not contrib:
                contrib = self.support_beams_by_edges(slab, beams, columns)

        ordered = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)
        slab.support_beam_ids = [bid for bid, _ in ordered]
        slab.support_beam_contributions = dict(ordered)
        return slab.support_beam_contributions

    def line_loads_on_supports(self, slab, beams_by_id):
        area = slab.area_m2 if slab.area_m2 and slab.area_m2 > 0 else slab.span_m * slab.span_m
        total_gk = slab.gk_kn_m2 * area
        total_qk = slab.qk_kn_m2 * area
        result = {}
        for bid, frac in slab.support_beam_contributions.items():
            beam = beams_by_id[bid]
            beam_len = max(beam.span_m, 0.50)
            result[bid] = ((total_gk * frac) / beam_len, (total_qk * frac) / beam_len)
        return result
