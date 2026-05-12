def estimate_crack_width_mm(steel_stress_mpa: float, bar_diameter_mm: float = 12.0, spacing_factor: float = 1.0):
    # Heurística simplificada para MVP:
    # w_k cresce com tensão no aço e com diâmetro/espaçamento efetivo.
    base = 0.08 * (steel_stress_mpa / 200.0)
    size_factor = (bar_diameter_mm / 12.0) * spacing_factor
    return max(0.05, base * size_factor)

def steel_stress_from_moment(moment_knm: float, as_cm2: float, z_mm: float):
    if as_cm2 <= 0 or z_mm <= 0:
        return 0.0
    as_mm2 = as_cm2 * 100.0
    return (moment_knm * 1_000_000.0) / (as_mm2 * z_mm)
