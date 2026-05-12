def rectangular_inertia_m4(width_m: float, height_m: float) -> float:
    return width_m * (height_m ** 3) / 12.0

def slab_strip_inertia_m4(thickness_m: float, width_m: float = 1.0) -> float:
    return width_m * (thickness_m ** 3) / 12.0

def simply_supported_udl_deflection_mm(q_kn_m: float, span_m: float, e_mpa: float, inertia_m4: float, creep_factor: float = 2.0):
    # q in kN/m, E in MPa=N/mm² -> Pa
    q_n_m = q_kn_m * 1000.0
    e_pa = e_mpa * 1e6
    if inertia_m4 <= 0 or e_pa <= 0:
        return 0.0, 0.0
    delta_inst_m = 5.0 * q_n_m * (span_m ** 4) / (384.0 * e_pa * inertia_m4)
    delta_final_m = delta_inst_m * (1.0 + creep_factor)
    return delta_inst_m * 1000.0, delta_final_m * 1000.0

def span_limit_mm(span_m: float, ratio: float = 250.0):
    return span_m * 1000.0 / ratio
