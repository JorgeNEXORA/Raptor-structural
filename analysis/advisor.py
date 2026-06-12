class ProjectAdvisor:

    # ── element classification ────────────────────────────────────────────────
    def classify_beam(self, beam):
        vals = [
            getattr(beam.result, "bending_utilization", 0.0),
            getattr(beam.result, "shear_utilization", 0.0),
            getattr(beam.result, "deflection_utilization", 0.0),
            getattr(beam.result, "crack_utilization", 0.0),
        ]
        u = max(vals)
        if u >= 1.0:   return "CRITICA", u
        if u >= 0.80:  return "ATENCAO", u
        return "OK", u

    def classify_column(self, col):
        u = getattr(col.result, "utilization", 0.0)
        buckling_ok = getattr(col.result, "buckling_ok", True)
        if not buckling_ok or u >= 1.0:  return "CRITICO", max(u, 1.0)
        if u >= 0.75:                    return "ATENCAO", u
        return "OK", u

    def classify_footing(self, footing):
        vals = [
            getattr(footing.result, "soil_utilization", 0.0),
            getattr(footing.result, "punching_utilization", 0.0),
            getattr(footing.result, "bending_utilization", 0.0),
        ]
        u = max(vals)
        if getattr(footing.result, "uplift_detected", False):
            return "CRITICA", max(1.0, u)
        if u >= 1.0:   return "CRITICA", u
        if u >= 0.80:  return "ATENCAO", u
        return "OK", u

    # ── suggestions ──────────────────────────────────────────────────────────
    def beam_suggestions(self, beam):
        msgs = []
        r = beam.result
        if getattr(r, "bending_utilization", 0.0) > 1.0:
            msgs.append(f"Viga {beam.id}: MEd > MRd — aumentar secção ou armadura.")
        elif getattr(r, "bending_utilization", 0.0) > 0.80:
            msgs.append(f"Viga {beam.id}: flexão próxima do limite — rever armadura.")
        if getattr(r, "shear_utilization", 0.0) > 0.80:
            msgs.append(f"Viga {beam.id}: corte elevado — aumentar secção ou adicionar estribos.")
        if getattr(r, "deflection_utilization", 0.0) > 0.80:
            msgs.append(f"Viga {beam.id}: flecha elevada — aumentar altura da viga.")
        if getattr(r, "crack_utilization", 0.0) > 0.80:
            msgs.append(f"Viga {beam.id}: fissuração elevada — aumentar armadura longitudinal.")
        return msgs

    def column_suggestions(self, col):
        msgs = []
        r = col.result
        if not getattr(r, "buckling_ok", True):
            msgs.append(
                f"Pilar {col.id}: λ={r.slenderness:.0f} > λ_lim={r.lambda_lim:.0f} "
                f"— verificar efeitos de 2.ª ordem (EC2 §5.8) ou aumentar secção.")
        if getattr(r, "utilization", 0.0) > 0.75:
            msgs.append(f"Pilar {col.id}: considerar aumento de secção.")
        if getattr(r, "bending_utilization", 0.0) > 0.80:
            msgs.append(f"Pilar {col.id}: excentricidade mínima elevada — rever armadura.")
        if getattr(r, "utilization", 0.0) < 0.10:
            msgs.append(f"Pilar {col.id}: secção possivelmente otimizável.")
        return msgs

    def footing_suggestions(self, footing):
        msgs = []
        r = footing.result
        if getattr(r, "uplift_detected", False):
            msgs.append(f"Sapata {footing.id}: levantamento — ligar por viga de equilíbrio.")
        if getattr(r, "bending_utilization", 0.0) > 1.0:
            msgs.append(f"Sapata {footing.id}: flexão excede MRd — aumentar altura ou armadura.")
        if getattr(r, "soil_utilization", 0.0) > 1.0:
            msgs.append(f"Sapata {footing.id}: tensão de solo excede admissível — aumentar dimensões.")
        elif getattr(r, "soil_utilization", 0.0) > 0.80:
            msgs.append(f"Sapata {footing.id}: tensão de solo alta — rever dimensão.")
        if getattr(r, "punching_utilization", 0.0) > 0.80:
            msgs.append(f"Sapata {footing.id}: punçoamento elevado — aumentar altura útil.")
        if getattr(r, "soil_utilization", 0.0) < 0.15:
            msgs.append(f"Sapata {footing.id}: muito folgada — pode ser otimizada.")
        return msgs

    # ── global score ─────────────────────────────────────────────────────────
    def project_score(self, project):
        def _worst_beam(b):
            r = b.result
            # Shear > 1 → stirrups required (not collapse); cap at 1.0 for ULS score
            shear = min(getattr(r, "shear_utilization", 0.0), 1.0)
            return max(getattr(r, "bending_utilization", 0.0), shear)
        def _worst_col(c):
            r = c.result
            u = getattr(r, "utilization", 0.0)
            return u if getattr(r, "buckling_ok", True) else max(u, 1.0)
        def _worst_fnd(f):
            r = f.result
            return max(
                getattr(r, "soil_utilization", 0.0),
                getattr(r, "punching_utilization", 0.0),
                1.0 if getattr(r, "uplift_detected", False) else 0.0,
            )

        beam_vals = [_worst_beam(b) for b in project.beams] or [0.0]
        col_vals  = [_worst_col(c) for c in project.columns] or [0.0]
        fnd_vals  = [_worst_fnd(f) for f in project.footings] or [0.0]

        def score(vals):
            worst = max(vals)
            return max(0.0, min(1.0, 1.0 - max(0.0, worst - 0.20)))

        els_vals = (
            [max(getattr(b.result, "deflection_utilization", 0.0),
                 getattr(b.result, "crack_utilization", 0.0)) for b in project.beams]
            + [max(getattr(s.result, "deflection_utilization", 0.0),
                   getattr(s.result, "crack_utilization", 0.0)) for s in project.slabs]
        ) or [0.0]

        scores = {
            "seguranca_uls": round(score([max(max(beam_vals), max(col_vals), max(fnd_vals))]), 2),
            "servico_els":   round(score(els_vals), 2),
            "fundacoes":     round(score(fnd_vals), 2),
        }
        project.project_scores = scores
        return scores

    # ── advice generation ─────────────────────────────────────────────────────
    def generate_advice(self, project):
        project.advice_messages = []
        for b in project.beams:
            cls, u = self.classify_beam(b)
            project.add_advice(f"VIGA {b.id} → {cls} | utilização crítica = {u:.2f} "
                                f"| MRd={getattr(b.result,'mrd_knm',0):.1f} kNm "
                                f"| VRd,c={getattr(b.result,'vrd_c_kn',0):.1f} kN")
            for m in self.beam_suggestions(b):
                project.add_advice("  - " + m)
        for c in project.columns:
            cls, u = self.classify_column(c)
            r = c.result
            project.add_advice(
                f"PILAR {c.id} → {cls} | utilização = {u:.2f} "
                f"| NRd={r.nrd_kn:.1f} kN | λ={r.slenderness:.0f}/λ_lim={r.lambda_lim:.0f} "
                f"({'OK' if r.buckling_ok else 'VERIFICAR'})")
            for m in self.column_suggestions(c):
                project.add_advice("  - " + m)
        for f in project.footings:
            cls, u = self.classify_footing(f)
            r = f.result
            project.add_advice(
                f"SAPATA {f.id} → {cls} | solo={r.soil_utilization:.2f} "
                f"| punç={r.punching_utilization:.2f} | flex={r.bending_utilization:.2f}")
            for m in self.footing_suggestions(f):
                project.add_advice("  - " + m)
        return project.advice_messages
