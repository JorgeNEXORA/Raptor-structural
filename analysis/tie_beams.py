from math import hypot
from core.model import FoundationTieBeam

class TieBeamPlanner:
    def build(self, project):
        footings = project.footings
        columns = {c.id: c for c in project.columns}

        candidates = [f for f in footings if getattr(f.result, "needs_balance_beam", False)]
        if not candidates:
            # fallback: connect eccentric footings only if no critical need detected
            candidates = [f for f in footings if getattr(f, "footing_type", None) and f.footing_type.value == "eccentric"]

        ties = []
        used = set()
        counter = 1

        for f in candidates:
            if f.id in used:
                continue
            c1 = columns[f.related_column_id]

            best = None
            for other in footings:
                if other.id == f.id or other.id in used:
                    continue
                c2 = columns[other.related_column_id]
                dist = hypot(c2.x - c1.x, c2.y - c1.y)
                if dist < 0.01:
                    continue
                # prefer nearest concentric or safe footing
                score = dist
                if getattr(other.result, "needs_balance_beam", False):
                    score += 0.5
                if best is None or score < best[0]:
                    best = (score, dist, other)

            if best is None:
                continue

            _, dist, other = best
            ties.append(
                FoundationTieBeam(
                    id=f"TB{counter}",
                    start_footing_id=f.id,
                    end_footing_id=other.id,
                    width_cm=25.0,
                    height_cm=60.0,
                    span_m=dist,
                    recommendation="Viga de equilíbrio proposta automaticamente"
                )
            )
            used.add(f.id)
            used.add(other.id)
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
