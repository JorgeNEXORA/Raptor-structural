from core.generators import ModelGenerator
from core.model import ColumnLoad, ContinuousFooting, Footing, FootingType, LineLoad, Project
from analysis.slabs import SlabAnalyzer
from analysis.beams import BeamAnalyzer
from analysis.columns import ColumnAnalyzer
from analysis.foundations import FoundationAnalyzer
from analysis.shear_walls import ShearWallAnalyzer
from analysis.flat_slabs import FlatSlabAnalyzer
from analysis.stairs import StairAnalyzer
from analysis.reinforcement import ReinforcementHelper
from analysis.tie_beams import TieBeamPlanner, TieBeamDesigner
from analysis.load_distribution import SlabToBeamDistributor
from analysis.slab_behavior import SlabBehaviorEstimator
from pipeline.continuous_pipeline import ContinuousPipeline
from config.design_code import load_design_code
import os


class AutoPipeline:
    def __init__(self):
        self.generator = ModelGenerator()

    def run(self, project: Project, slab_loads: dict | None = None):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code_cfg = load_design_code(root_dir)

        # Instantiate material-aware analyzers from project properties
        fck = getattr(project, "fck_mpa", 25.0)
        fyk = getattr(project, "fyk_mpa", 500.0)

        slab_analyzer   = SlabAnalyzer(fck_mpa=fck, fyk_mpa=fyk)
        beam_analyzer   = BeamAnalyzer(fck_mpa=fck, fyk_mpa=fyk)
        column_analyzer = ColumnAnalyzer(fck_mpa=fck, fyk_mpa=fyk)

        # ── Geometry generation ───────────────────────────────────────────────
        if not project.beams:
            project.beams = self.generator.generate_beams(project.columns)
            project.add_alert("info", "Vigas geradas automaticamente a partir da geometria dos pilares.")
        else:
            project.add_alert("info", f"Foram importadas {len(project.beams)} vigas por CSV/DXF.")

        if not project.slabs:
            project.slabs = self.generator.create_slabs_from_panels(
                self.generator.generate_panels(project.columns), project.beams,
                gk_kn_m2=project.gk_floor_kn_m2, qk_kn_m2=project.qk_floor_kn_m2)
            project.add_alert("info", "Lajes geradas automaticamente a partir da malha geométrica.")
        else:
            project.add_alert("info", f"Foram importadas {len(project.slabs)} lajes por CSV/DXF.")

        if slab_loads:
            self.generator.apply_slab_loads(project.slabs, slab_loads)
            project.add_alert("info", f"Foram aplicadas cargas específicas a {len(slab_loads)} lajes via CSV.")

        # ── Slab analysis ─────────────────────────────────────────────────────
        behavior = SlabBehaviorEstimator()
        for s in project.slabs:
            info = behavior.estimate(s)
            slab_analyzer.analyze(s)
            project.add_alert("info",
                f"Laje {s.id}: tipo={info['slab_type']} dir={info['direction']} razão={info['ratio']:.2f}.")
            if s.result.deflection_utilization > 0.80:
                project.add_alert("warning",
                    f"Laje {s.id}: flecha elevada ({s.result.deflection_utilization:.2f}).")
            if s.result.crack_utilization > 0.80:
                project.add_alert("warning",
                    f"Laje {s.id}: fissuração elevada ({s.result.crack_utilization:.2f}).")
            if info["ratio"] > 2.0:
                project.add_alert("warning",
                    f"Laje {s.id}: geometria muito alongada (razão={info['ratio']:.2f}).")

        # ── Load distribution: slab → beams ──────────────────────────────────
        distributor  = SlabToBeamDistributor()
        beam_lookup  = {b.id: b for b in project.beams}

        _col_map = {c.id: c for c in project.columns}

        def _beam_orientation(b):
            """Return 'H' (horizontal/X) or 'V' (vertical/Y)."""
            try:
                c1 = _col_map[b.start_node]
                c2 = _col_map[b.end_node]
                return 'H' if abs(c2.x - c1.x) >= abs(c2.y - c1.y) else 'V'
            except KeyError:
                return 'H'

        # Pre-group beams by orientation for fallback
        _h_beams = sorted(
            [b for b in project.beams if _beam_orientation(b) == 'H'],
            key=lambda b: b.id)
        _v_beams = sorted(
            [b for b in project.beams if _beam_orientation(b) == 'V'],
            key=lambda b: b.id)
        _rr = [0]   # round-robin counter across slabs

        for s in project.slabs:
            contribs = distributor.support_beams_for_slab(s, project.beams, project.columns)
            if not contribs and project.beams:
                # 1. Use explicitly declared support beams if available
                if s.support_beam_ids:
                    valid = [bid for bid in s.support_beam_ids if bid in beam_lookup]
                    if valid:
                        contribs = {bid: 1.0 / len(valid) for bid in valid}

                if not contribs:
                    # 2. Round-robin: assign each slab to 1 H-beam + 1 V-beam
                    #    cycling through both groups so all beams get loaded.
                    chosen = []
                    if _h_beams:
                        chosen.append(_h_beams[_rr[0] % len(_h_beams)])
                    if _v_beams:
                        chosen.append(_v_beams[_rr[0] % len(_v_beams)])
                    if not chosen:
                        chosen = [project.beams[_rr[0] % len(project.beams)]]
                    _rr[0] += 1
                    contribs = {b.id: 1.0 / len(chosen) for b in chosen}
                    project.add_alert(
                        "warning",
                        f"Laje {s.id}: sem polígono — carga atribuída a "
                        f"{', '.join(b.id for b in chosen)} [aprox. round-robin].")
            if not contribs:
                project.add_alert("warning", f"Laje {s.id}: não foi possível identificar vigas de apoio.")
                continue
            line_loads = distributor.line_loads_on_supports(s, beam_lookup)
            for bid, (gk_line, qk_line) in line_loads.items():
                beam_lookup[bid].add_line_load(LineLoad(s.id, gk_line, qk_line))
                if s.id not in beam_lookup[bid].supported_slab_ids:
                    beam_lookup[bid].supported_slab_ids.append(s.id)
            txt = ", ".join(f"{bid}={frac:.2f}" for bid, frac in contribs.items())
            project.add_alert("info", f"Laje {s.id}: descarga distribuída por {txt}.")

        # ── Beam analysis ─────────────────────────────────────────────────────
        for b in project.beams:
            beam_analyzer.analyze(b)
            if b.result.shear_utilization > 0.75:
                project.add_alert("warning",
                    f"Viga {b.id}: corte com utilização elevada ({b.result.shear_utilization:.2f}).")
            if b.result.deflection_utilization > 0.80:
                project.add_alert("warning",
                    f"Viga {b.id}: flecha elevada ({b.result.deflection_utilization:.2f}).")
            if b.result.crack_utilization > 0.80:
                project.add_alert("warning",
                    f"Viga {b.id}: fissuração elevada ({b.result.crack_utilization:.2f}).")
            if b.result.bending_utilization > 1.0:
                project.add_alert("warning",
                    f"Viga {b.id}: flexão excede MRd ({b.result.bending_utilization:.2f}).")

        # ── Continuous beam analysis ──────────────────────────────────────────
        cont = ContinuousPipeline(project.columns, project.beams).run()
        if cont:
            project.add_alert("info", f"Foram detetadas {len(cont)} linhas de vigas contínuas.")

        for b in project.beams:
            if b.continuous_result:
                a1 = ReinforcementHelper.as_required_from_moment(
                    b.continuous_result["m_left_knm"], b.effective_depth_cm)
                a2 = ReinforcementHelper.as_required_from_moment(
                    b.continuous_result["m_pos_knm"], b.effective_depth_cm)
                a3 = ReinforcementHelper.as_required_from_moment(
                    b.continuous_result["m_right_knm"], b.effective_depth_cm)
                st = ReinforcementHelper.suggest_stirrups(
                    max(b.continuous_result["v_left_kn"], b.continuous_result["v_right_kn"]),
                    b.width_cm, b.effective_depth_cm)
                b.reinforcement_result = {
                    "top_left_text":  ReinforcementHelper.suggest_beam_bars(a1).bars_text,
                    "bottom_text":    ReinforcementHelper.suggest_beam_bars(a2).bars_text,
                    "top_right_text": ReinforcementHelper.suggest_beam_bars(a3).bars_text,
                    "stirrups_text":  st.text,
                }
            else:
                st = ReinforcementHelper.suggest_stirrups(
                    b.result.vsd_kn, b.width_cm, b.effective_depth_cm)
                b.reinforcement_result = {
                    "top_left_text":  "-",
                    "bottom_text":    ReinforcementHelper.suggest_beam_bars(
                                          b.result.required_as_cm2).bars_text,
                    "top_right_text": "-",
                    "stirrups_text":  st.text,
                }

        # ── Load transfer: beams → columns ───────────────────────────────────
        col_lookup = {c.id: c for c in project.columns}
        for b in project.beams:
            col_lookup[b.start_node].add_load(
                ColumnLoad(b.id, b.total_gk() * b.span_m / 2.0, b.total_qk() * b.span_m / 2.0))
            col_lookup[b.end_node].add_load(
                ColumnLoad(b.id, b.total_gk() * b.span_m / 2.0, b.total_qk() * b.span_m / 2.0))

        # ── Column analysis ───────────────────────────────────────────────────
        for c in project.columns:
            column_analyzer.analyze(c)
            if not c.result.buckling_ok:
                project.add_alert("warning",
                    f"Pilar {c.id}: esbelteza λ={c.result.slenderness:.0f} > λ_lim={c.result.lambda_lim:.0f} "
                    f"— verificar efeitos de 2.ª ordem (EC2 §5.8).")
            if c.result.utilization < 0.10:
                project.add_alert("info", f"Pilar {c.id} pouco solicitado.")
            elif c.result.utilization > 0.75:
                project.add_alert("warning",
                    f"Pilar {c.id}: utilização elevada ({c.result.utilization:.2f}).")

        # ── Foundation design ─────────────────────────────────────────────────
        project.footings = [
            Footing(f"S_{c.id}", c.id, FootingType.CONCENTRIC, 100.0, 100.0, 40.0, 37.0)
            for c in project.columns
        ]
        if len(project.footings) >= 2:
            project.footings[1].footing_type = FootingType.ECCENTRIC
            project.footings[1].eccentricity_x_cm = 12.0
        if len(project.footings) >= 5:
            project.footings[4].footing_type = FootingType.ECCENTRIC
            project.footings[4].eccentricity_y_cm = 12.0

        fnd          = FoundationAnalyzer(project.soil_allowable_mpa, fck_mpa=fck, fyk_mpa=fyk)
        footing_lookup = {}
        for f in project.footings:
            footing_lookup[f.id] = f
            fnd.analyze(f, col_lookup[f.related_column_id])
            f.reinforcement_result = {
                "bottom_text": ReinforcementHelper.suggest_footing_bottom_bars(
                    f.result.adopted_as_cm2, f.width_a_cm).bars_text
            }
            if f.footing_type == FootingType.ECCENTRIC:
                project.add_alert("warning",
                    f"Sapata {f.id} excêntrica: confirmar viga de equilíbrio/amarração.")
            if f.result.uplift_detected:
                project.add_alert("warning",
                    f"Sapata {f.id}: levantamento detetado (σmin={f.result.sigma_min_mpa:.3f} MPa).")
            if f.result.needs_balance_beam:
                project.add_alert("warning", f"Sapata {f.id}: recomenda-se viga de equilíbrio.")
            if f.result.soil_utilization > code_cfg["geotechnics"]["max_footing_utilization_warning"]:
                project.add_alert("warning",
                    f"Sapata {f.id}: tensão de solo elevada ({f.result.soil_utilization:.2f}).")
            elif f.result.soil_utilization < code_cfg["geotechnics"]["min_footing_utilization_warning"]:
                project.add_alert("info",
                    f"Sapata {f.id}: muito folgada ({f.result.soil_utilization:.2f}).")
            if f.result.punching_utilization > 0.75:
                project.add_alert("warning",
                    f"Sapata {f.id}: punçoamento com utilização elevada ({f.result.punching_utilization:.2f}).")
            if f.result.bending_utilization > 1.0:
                project.add_alert("warning",
                    f"Sapata {f.id}: flexão excede MRd ({f.result.bending_utilization:.2f}).")

        # ── Tie beams ─────────────────────────────────────────────────────────
        ties     = TieBeamPlanner().build(project)
        designer = TieBeamDesigner()
        for tie in ties:
            designer.design(tie, footing_lookup[tie.start_footing_id])
        if ties:
            project.add_alert("info", f"Foram propostas {len(ties)} vigas de amarração/equilíbrio.")

        # ── Shear walls ───────────────────────────────────────────────────────
        if project.walls:
            wall_analyzer = ShearWallAnalyzer(fck_mpa=fck, fyk_mpa=fyk)
            for w in project.walls:
                wall_analyzer.analyze(w)
                r = w.result
                if not r.buckling_ok:
                    project.add_alert("warning",
                        f"Parede {w.id}: esbelteza λ={r.slenderness:.0f} > λ_lim={r.lambda_lim:.0f} "
                        f"— verificar estabilidade (EC2 §5.8.3).")
                if r.shear_utilization > 0.80:
                    project.add_alert("warning",
                        f"Parede {w.id}: corte horizontal elevado ({r.shear_utilization:.2f}).")
                if r.bending_utilization > 1.0:
                    project.add_alert("warning",
                        f"Parede {w.id}: flexão na base excede MRd ({r.bending_utilization:.2f}).")
                if r.axial_utilization > 0.80:
                    project.add_alert("warning",
                        f"Parede {w.id}: compressão vertical elevada ({r.axial_utilization:.2f}).")
            project.add_alert("info", f"Foram verificadas {len(project.walls)} paredes estruturais.")

        # ── Retaining walls ──────────────────────────────────────────────────
        if project.retaining_walls:
            from analysis.retaining_walls import RetainingWallAnalyzer, ContinuousFootingAnalyzer
            rw_analyzer = RetainingWallAnalyzer(fck_mpa=fck, fyk_mpa=fyk,
                                                soil_allowable_mpa=project.soil_allowable_mpa)
            cf_analyzer = ContinuousFootingAnalyzer(fck_mpa=fck, fyk_mpa=fyk,
                                                    soil_allowable_mpa=project.soil_allowable_mpa)
            for rw in project.retaining_walls:
                rw_analyzer.analyze(rw)
                r = rw.result
                if not r.sliding_ok:
                    project.add_alert("warning",
                        f"Muro {rw.id}: deslizamento insuficiente (SF={r.sliding_safety:.2f} < 1.5).")
                if not r.overturning_ok:
                    project.add_alert("warning",
                        f"Muro {rw.id}: derrubamento insuficiente (SF={r.overturning_safety:.2f} < 2.0).")
                if not r.bearing_ok:
                    project.add_alert("warning",
                        f"Muro {rw.id}: tensão solo excede admissível ({r.bearing_utilization:.2f}).")
            project.add_alert("info", f"Verificados {len(project.retaining_walls)} muros de suporte.")

            # Auto-generate continuous footings for retaining walls if not present
            existing_cf_ids = {cf.related_wall_id for cf in project.continuous_footings}
            for rw in project.retaining_walls:
                if rw.id not in existing_cf_ids:
                    cf = ContinuousFooting(
                        id=f"SC_{rw.id}",
                        related_wall_id=rw.id,
                        width_cm=rw.base_width_m * 100,
                        height_cm=rw.base_thickness_cm,
                        length_m=10.0,  # default — user should override
                        load_gk_kn_m=rw.result.axial_base_kn_m if rw.result else 0,
                        load_qk_kn_m=0.0,
                        effective_depth_cm=rw.base_thickness_cm - 5.0,
                    )
                    project.continuous_footings.append(cf)

            for cf in project.continuous_footings:
                cf_analyzer.analyze(cf)
                r = cf.result
                if r.soil_utilization > 0.90:
                    project.add_alert("warning",
                        f"Sapata corrida {cf.id}: tensão solo elevada ({r.soil_utilization:.2f}).")
                if r.bending_utilization > 1.0:
                    project.add_alert("warning",
                        f"Sapata corrida {cf.id}: flexão excede MRd ({r.bending_utilization:.2f}).")

        # ── Flat slabs ────────────────────────────────────────────────────────
        if project.flat_slabs:
            fs_analyzer = FlatSlabAnalyzer(fck_mpa=fck, fyk_mpa=fyk)
            for fs in project.flat_slabs:
                fs_analyzer.analyze(fs)
                r = fs.result
                if r.bending_utilization > 1.0:
                    project.add_alert("warning",
                        f"Laje {fs.id}: flexão na faixa de pilar excede MRd ({r.bending_utilization:.2f}).")
                if r.punching_utilization > 0.80:
                    project.add_alert("warning",
                        f"Laje {fs.id}: punçoamento elevado ({r.punching_utilization:.2f}) — verificar "
                        f"reforço ou capitéis.")
                if r.deflection_utilization > 0.80:
                    project.add_alert("warning",
                        f"Laje {fs.id}: flecha elevada ({r.deflection_utilization:.2f}).")
            project.add_alert("info", f"Foram verificadas {len(project.flat_slabs)} lajes fungiformes.")

        # ── Stairs ────────────────────────────────────────────────────────────
        if project.stairs:
            stair_analyzer = StairAnalyzer(fck_mpa=fck, fyk_mpa=fyk)
            for st in project.stairs:
                stair_analyzer.analyze(st)
                r = st.result
                if r.bending_utilization > 1.0:
                    project.add_alert("warning",
                        f"Escada {st.id}: flexão excede MRd ({r.bending_utilization:.2f}).")
                if r.deflection_utilization > 0.80:
                    project.add_alert("warning",
                        f"Escada {st.id}: flecha elevada ({r.deflection_utilization:.2f}) — limite L/350.")
            project.add_alert("info",
                f"Foram verificadas {len(project.stairs)} escadas "
                f"(α={project.stairs[0].result.inclination_deg:.0f}°).")
