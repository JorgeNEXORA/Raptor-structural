def make_project_snapshot(project, label: str):
    return {
        "label": label,
        "scores": dict(getattr(project, "project_scores", {}) or {}),
        "beams": {
            b.id: {
                "width_cm": b.width_cm,
                "height_cm": b.height_cm,
                "effective_depth_cm": b.effective_depth_cm,
                "shear_utilization": getattr(getattr(b, "result", None), "shear_utilization", None),
                "deflection_utilization": getattr(getattr(b, "result", None), "deflection_utilization", None),
                "crack_utilization": getattr(getattr(b, "result", None), "crack_utilization", None),
            } for b in project.beams
        },
        "columns": {
            c.id: {
                "width_cm": c.width_cm,
                "depth_cm": c.depth_cm,
                "utilization": getattr(getattr(c, "result", None), "utilization", None),
            } for c in project.columns
        },
        "footings": {
            f.id: {
                "width_a_cm": f.width_a_cm,
                "width_b_cm": f.width_b_cm,
                "height_cm": f.height_cm,
                "effective_depth_cm": f.effective_depth_cm,
                "soil_utilization": getattr(getattr(f, "result", None), "soil_utilization", None),
                "punching_utilization": getattr(getattr(f, "result", None), "punching_utilization", None),
                "sigma_min_mpa": getattr(getattr(f, "result", None), "sigma_min_mpa", None),
                "sigma_max_mpa": getattr(getattr(f, "result", None), "sigma_max_mpa", None),
                "uplift_detected": getattr(getattr(f, "result", None), "uplift_detected", None),
            } for f in project.footings
        }
    }

def store_snapshot(project, label: str):
    snap = make_project_snapshot(project, label)
    project.history_snapshots.append(snap)
    return snap

def build_comparison_text(before: dict, after: dict):
    lines = []
    lines.append(f"Comparação: {before.get('label', 'antes')} -> {after.get('label', 'depois')}")
    b_scores = before.get("scores", {})
    a_scores = after.get("scores", {})
    lines.append("SCORES")
    for key in ["seguranca_uls", "servico_els", "fundacoes"]:
        if key in b_scores or key in a_scores:
            lines.append(f"  {key}: {b_scores.get(key)} -> {a_scores.get(key)}")

    lines.append("VIGAS")
    for bid, b0 in before.get("beams", {}).items():
        b1 = after.get("beams", {}).get(bid)
        if not b1:
            continue
        changes = []
        if b0["width_cm"] != b1["width_cm"] or b0["height_cm"] != b1["height_cm"]:
            changes.append(f"secção {b0['width_cm']:.0f}x{b0['height_cm']:.0f} -> {b1['width_cm']:.0f}x{b1['height_cm']:.0f} cm")
        if b0.get("deflection_utilization") != b1.get("deflection_utilization"):
            changes.append(f"flecha {round(b0.get('deflection_utilization') or 0, 2)} -> {round(b1.get('deflection_utilization') or 0, 2)}")
        if b0.get("crack_utilization") != b1.get("crack_utilization"):
            changes.append(f"fiss {round(b0.get('crack_utilization') or 0, 2)} -> {round(b1.get('crack_utilization') or 0, 2)}")
        if changes:
            lines.append(f"  {bid}: " + " | ".join(changes))

    lines.append("PILARES")
    for cid, c0 in before.get("columns", {}).items():
        c1 = after.get("columns", {}).get(cid)
        if not c1:
            continue
        changes = []
        if c0["width_cm"] != c1["width_cm"] or c0["depth_cm"] != c1["depth_cm"]:
            changes.append(f"secção {c0['width_cm']:.0f}x{c0['depth_cm']:.0f} -> {c1['width_cm']:.0f}x{c1['depth_cm']:.0f} cm")
        if c0.get("utilization") != c1.get("utilization"):
            changes.append(f"util {round(c0.get('utilization') or 0, 2)} -> {round(c1.get('utilization') or 0, 2)}")
        if changes:
            lines.append(f"  {cid}: " + " | ".join(changes))

    lines.append("SAPATAS")
    for fid, f0 in before.get("footings", {}).items():
        f1 = after.get("footings", {}).get(fid)
        if not f1:
            continue
        changes = []
        if f0["width_a_cm"] != f1["width_a_cm"] or f0["width_b_cm"] != f1["width_b_cm"]:
            changes.append(f"planta {f0['width_a_cm']:.0f}x{f0['width_b_cm']:.0f} -> {f1['width_a_cm']:.0f}x{f1['width_b_cm']:.0f} cm")
        if f0["height_cm"] != f1["height_cm"]:
            changes.append(f"altura {f0['height_cm']:.0f} -> {f1['height_cm']:.0f} cm")
        if f0.get("soil_utilization") != f1.get("soil_utilization"):
            changes.append(f"solo {round(f0.get('soil_utilization') or 0, 2)} -> {round(f1.get('soil_utilization') or 0, 2)}")
        if f0.get("punching_utilization") != f1.get("punching_utilization"):
            changes.append(f"punçoamento {round(f0.get('punching_utilization') or 0, 2)} -> {round(f1.get('punching_utilization') or 0, 2)}")
        if f0.get("uplift_detected") != f1.get("uplift_detected"):
            changes.append(f"uplift {f0.get('uplift_detected')} -> {f1.get('uplift_detected')}")
        if changes:
            lines.append(f"  {fid}: " + " | ".join(changes))
    return lines
