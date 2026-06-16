from math import hypot
from core.model import FoundationTieBeam

class TieBeamPlanner:
    def build(self, project):
        footings = project.footings
        columns = {c.id: c for c in project.columns}

        if not footings:
            project.tie_beams = []
            return []

        # EC2 §9.10.2 — vigas de amarração entre TODAS as sapatas isoladas
        # Algoritmo: árvore de expansão mínima (greedy nearest-neighbor)
        # Garante que todas as sapatas ficam ligadas com o mínimo de vigas
        col_pos = {}
        for f in footings:
            c = columns.get(f.related_column_id)
            if c:
                col_pos[f.id] = (c.x, c.y)

        if len(col_pos) < 2:
            project.tie_beams = []
            return []

        ties = []
        counter = 1
        connected = {next(iter(col_pos))}
        remaining = {fid: pos for fid, pos in col_pos.items() if fid not in connected}
        ftg_by_id = {f.id: f for f in footings}

        while remaining:
            best = None
            best_dist = float('inf')
            for c_id in connected:
                cx, cy = col_pos[c_id]
                for r_id, (rx, ry) in remaining.items():
                    d = hypot(rx - cx, ry - cy)
                    if d < best_dist:
                        best_dist = d
                        best = (c_id, r_id, d)

            if best is None:
                break

            from_id, to_id, dist = best
            ties.append(
                FoundationTieBeam(
                    id=f"CB.{counter}.1",
                    start_footing_id=from_id,
                    end_footing_id=to_id,
                    width_cm=30.0,
                    height_cm=60.0,
                    span_m=dist,
                    recommendation="Viga de amarração/equilíbrio (EC2 §9.10.2)"
                )
            )
            connected.add(to_id)
            del remaining[to_id]
            counter += 1

        project.tie_beams = ties
        return ties


class TieBeamDesigner:
    def design(self, tie, start_footing):
        res = start_footing.result
        ex = abs(getattr(start_footing, "eccentricity_x_cm", 0.0)) / 100.0
        ey = abs(getattr(start_footing, "eccentricity_y_cm", 0.0)) / 100.0
        e = max(ex, ey, 0.10)

        # practical simplified balance force
        tie_force = res.nsd_kn * e / max(tie.span_m, 0.50)
        moment = tie_force * tie.span_m / 4.0

        fyd = 435.0
        d_cm = tie.height_cm - 5.0
        z_mm = 0.9 * d_cm * 10.0
        as_req_cm2 = (moment * 1_000_000.0) / (fyd * z_mm) / 100.0 if z_mm > 0 else 0.0

        tie.tie_force_kn = round(tie_force, 2)
        tie.required_as_cm2 = round(max(as_req_cm2, 2.26), 2)

        if tie.required_as_cm2 <= 2.26:
            tie.adopted_bars = "2Ø12"
        elif tie.required_as_cm2 <= 4.02:
            tie.adopted_bars = "2Ø16"
        elif tie.required_as_cm2 <= 6.03:
            tie.adopted_bars = "3Ø16"
        else:
            tie.adopted_bars = "4Ø16"
        return tie
