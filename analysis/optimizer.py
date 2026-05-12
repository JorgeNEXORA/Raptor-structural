class AutoOptimizer:
    def optimize(self, project):
        changes = []

        for beam in project.beams:
            if getattr(beam.result, "deflection_utilization", 0.0) > 0.80 or getattr(beam.result, "crack_utilization", 0.0) > 0.80:
                old_h = beam.height_cm
                beam.height_cm = min(beam.height_cm + 10.0, 120.0)
                beam.effective_depth_cm = min(beam.effective_depth_cm + 9.0, beam.height_cm - 3.0)
                changes.append(f"Viga {beam.id}: altura {old_h:.0f} -> {beam.height_cm:.0f} cm")
            elif getattr(beam.result, "shear_utilization", 0.0) > 0.80:
                old_b = beam.width_cm
                beam.width_cm = min(beam.width_cm + 5.0, 50.0)
                changes.append(f"Viga {beam.id}: largura {old_b:.0f} -> {beam.width_cm:.0f} cm")

        for col in project.columns:
            if getattr(col.result, "utilization", 0.0) > 0.75:
                ow, od = col.width_cm, col.depth_cm
                col.width_cm = min(col.width_cm + 5.0, 50.0)
                col.depth_cm = min(col.depth_cm + 5.0, 50.0)
                changes.append(f"Pilar {col.id}: secção {ow:.0f}x{od:.0f} -> {col.width_cm:.0f}x{col.depth_cm:.0f} cm")

        for footing in project.footings:
            if getattr(footing.result, "needs_balance_beam", False) or getattr(footing.result, "soil_utilization", 0.0) > 0.80:
                oa, ob = footing.width_a_cm, footing.width_b_cm
                footing.width_a_cm = min(footing.width_a_cm + 20.0, 300.0)
                footing.width_b_cm = min(footing.width_b_cm + 20.0, 300.0)
                changes.append(f"Sapata {footing.id}: {oa:.0f}x{ob:.0f} -> {footing.width_a_cm:.0f}x{footing.width_b_cm:.0f} cm")
            if getattr(footing.result, "punching_utilization", 0.0) > 0.80:
                oh, od = footing.height_cm, footing.effective_depth_cm
                footing.height_cm = min(footing.height_cm + 10.0, 120.0)
                footing.effective_depth_cm = min(footing.effective_depth_cm + 10.0, footing.height_cm - 3.0)
                changes.append(f"Sapata {footing.id}: altura {oh:.0f}/{od:.0f} -> {footing.height_cm:.0f}/{footing.effective_depth_cm:.0f} cm")

        return changes
