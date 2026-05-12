import math
from core.model import FlatSlab, FlatSlabResult
from analysis.combinations import CombinationEngine
from analysis.deflections import slab_strip_inertia_m4, simply_supported_udl_deflection_mm, span_limit_mm


class FlatSlabAnalyzer:
    """
    EC2 flat slab (laje fungiforme) verification:
      - Flexure:   equivalent frame split  60 % column strip / 40 % middle strip
      - Punching:  EC2 §6.4.3 at basic control perimeter u1 = 4c + 4π·2d
      - Deflection: L/250  §7.4

    Panel types (β factor for uneven shear distribution):
      interior → β = 1.00
      edge     → β = 1.15
      corner   → β = 1.50
    """

    def __init__(self, fck_mpa: float = 25.0, fyk_mpa: float = 500.0):
        self.fck = fck_mpa
        self.fcd = fck_mpa / 1.5
        self.fyk = fyk_mpa
        self.fyd = fyk_mpa / 1.15
        self.fctm = (0.30 * fck_mpa ** (2.0 / 3.0)
                     if fck_mpa <= 50
                     else 2.12 * math.log(1.0 + (fck_mpa + 8.0) / 10.0))
        self.e_cm = 22000.0 * ((fck_mpa + 8.0) / 10.0) ** 0.3
        self.comb = CombinationEngine()

    # ── §9.3.1.1 — minimum reinforcement ─────────────────────────────────────
    def _as_min_cm2_m(self, d_cm: float) -> float:
        d_mm = d_cm * 10.0
        return max(
            0.26 * self.fctm / self.fyk * 1000.0 * d_mm,
            0.0013 * 1000.0 * d_mm
        ) / 100.0

    def _required_as_cm2_m(self, msd_knm_m: float, d_cm: float) -> float:
        z_mm = 0.9 * d_cm * 10.0
        return (msd_knm_m * 1e6) / (self.fyd * z_mm) / 100.0 if msd_knm_m > 0 else 0.0

    def _mrd_knm_m(self, as_cm2_m: float, d_cm: float) -> float:
        bw_mm  = 1000.0
        d_mm   = d_cm * 10.0
        As_mm2 = as_cm2_m * 100.0
        x_mm   = As_mm2 * self.fyd / (0.8 * bw_mm * self.fcd)
        z_mm   = min(d_mm - 0.4 * x_mm, 0.95 * d_mm)
        return As_mm2 * self.fyd * z_mm / 1e6

    # ── §6.4.3 — punching shear ──────────────────────────────────────────────
    def _punching_check(self, slab: FlatSlab, qd_kn_m2: float,
                        beta: float) -> tuple[float, float]:
        d_mm  = slab.effective_depth_cm * 10.0
        c_mm  = slab.col_width_cm * 10.0

        # Basic control perimeter at 2d from column face (square column)
        u1_mm = 4.0 * c_mm + 4.0 * math.pi * 2.0 * d_mm

        # VEd = β × qd × tributary area
        a_trib_m2 = slab.lx_m * slab.ly_m
        ved_kn = beta * qd_kn_m2 * a_trib_m2

        # vRd,c with conservative ρl = 0.5 % (typical flat slab mid-reinf.)
        CRdc  = 0.18 / 1.5
        k     = min(1.0 + math.sqrt(200.0 / max(d_mm, 1.0)), 2.0)
        rho_l = 0.005
        v_rdc = max(
            CRdc * k * (100.0 * rho_l * self.fck) ** (1.0 / 3.0),
            0.035 * k ** 1.5 * self.fck ** 0.5,
        )
        vrd_kn = v_rdc * u1_mm * d_mm / 1000.0

        return round(ved_kn, 2), round(vrd_kn, 2)

    # ── main ─────────────────────────────────────────────────────────────────
    def analyze(self, slab: FlatSlab) -> FlatSlabResult:
        gk = slab.gk_kn_m2
        qk = slab.qk_kn_m2
        qd   = self.comb.uls_fundamental(gk, qk)
        q_qp = self.comb.sls_quasi_permanent(gk, qk)

        beta = {"interior": 1.0, "edge": 1.15, "corner": 1.5}.get(slab.panel_type, 1.0)

        # Moment per unit width in short-span direction (§5.3 equivalent frame)
        m_total = qd * slab.lx_m ** 2 / 8.0    # kNm/m (simple span analogy)
        m_col   = 0.60 * m_total * beta
        m_mid   = 0.40 * m_total

        d      = slab.effective_depth_cm
        as_min = self._as_min_cm2_m(d)
        as_col = max(self._required_as_cm2_m(m_col, d), as_min)
        as_mid = max(self._required_as_cm2_m(m_mid, d), as_min)

        mrd_col = self._mrd_knm_m(as_col, d)
        mrd_mid = self._mrd_knm_m(as_mid, d)

        bending_util = m_col / mrd_col if mrd_col > 0 else 999.0

        # Punching
        ved_pun, vrd_pun = self._punching_check(slab, qd, beta)
        pun_util = ved_pun / vrd_pun if vrd_pun > 0 else 999.0

        # Deflection — 1 m strip over short span
        inertia = slab_strip_inertia_m4(slab.thickness_cm / 100.0, 1.0)
        d_inst, d_final = simply_supported_udl_deflection_mm(
            q_qp, slab.lx_m, self.e_cm, inertia, creep_factor=2.0)
        d_lim = span_limit_mm(slab.lx_m, 250.0)

        slab.result = FlatSlabResult(
            sd_uls_kn_m2=round(qd, 3),
            med_column_strip_knm_m=round(m_col, 2),
            med_middle_strip_knm_m=round(m_mid, 2),
            mrd_column_strip_knm_m=round(mrd_col, 2),
            mrd_middle_strip_knm_m=round(mrd_mid, 2),
            bending_utilization=round(bending_util, 3),
            punching_ved_kn=ved_pun,
            punching_vrd_kn=vrd_pun,
            punching_utilization=round(pun_util, 3),
            deflection_inst_mm=round(d_inst, 1),
            deflection_final_mm=round(d_final, 1),
            deflection_limit_mm=round(d_lim, 1),
            deflection_utilization=round(d_final / d_lim, 3) if d_lim > 0 else 999.0,
            required_as_col_cm2_m=round(as_col, 2),
            required_as_mid_cm2_m=round(as_mid, 2),
        )
        return slab.result
