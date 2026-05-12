import math
from core.model import StairSlab, StairSlabResult
from analysis.combinations import CombinationEngine
from analysis.deflections import slab_strip_inertia_m4, simply_supported_udl_deflection_mm, span_limit_mm


class StairAnalyzer:
    """
    EC2 stair slab verification (laje inclinada — escada):
      - Self-weight corrected for slope: g_sw = γc·t / cos(α)  on horizontal projection
      - MEd = qd_eq · Lh² / 8   (horizontal span)
      - VRd,c  §6.2.2
      - Deflection limit L/350 (§7.4, susceptible to damage)
    """

    GAMMA_C = 25.0   # kN/m³  reinforced concrete

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

    def _vrd_c_kn_m(self, d_cm: float, as_cm2_m: float) -> float:
        d_mm   = d_cm * 10.0
        As_mm2 = as_cm2_m * 100.0
        bw_mm  = 1000.0
        CRdc   = 0.18 / 1.5
        k      = min(1.0 + math.sqrt(200.0 / max(d_mm, 1.0)), 2.0)
        rho_l  = min(As_mm2 / (bw_mm * d_mm), 0.02)
        v_rdc  = CRdc * k * (100.0 * rho_l * self.fck) ** (1.0 / 3.0)
        v_min  = 0.035 * k ** 1.5 * self.fck ** 0.5
        return max(v_rdc, v_min) * bw_mm * d_mm / 1000.0

    # ── main ─────────────────────────────────────────────────────────────────
    def analyze(self, stair: StairSlab) -> StairSlabResult:
        Lh    = stair.span_h_m
        Hv    = stair.rise_m
        slope = math.sqrt(Lh ** 2 + Hv ** 2)
        cos_a = Lh / slope if slope > 0 else 1.0
        alpha_deg = round(math.degrees(math.atan2(Hv, Lh)), 1)

        # Self-weight on horizontal projection: γc × t / cos(α)
        t_m    = stair.thickness_cm / 100.0
        g_self = self.GAMMA_C * t_m / cos_a     # kN/m² (horiz. projection)

        gk_eq  = stair.gk_kn_m2 + g_self
        qk     = stair.qk_kn_m2
        qd     = self.comb.uls_fundamental(gk_eq, qk)
        q_qp   = self.comb.sls_quasi_permanent(gk_eq, qk)

        msd = qd * Lh ** 2 / 8.0
        vsd = qd * Lh / 2.0

        d      = stair.effective_depth_cm
        as_min = self._as_min_cm2_m(d)
        as_req = max(self._required_as_cm2_m(msd, d), as_min)

        mrd = self._mrd_knm_m(as_req, d)
        vrd = self._vrd_c_kn_m(d, as_req)

        # Deflection limit L/350 — elements susceptible to cracking damage
        inertia  = slab_strip_inertia_m4(stair.thickness_cm / 100.0, 1.0)
        d_inst, d_final = simply_supported_udl_deflection_mm(
            q_qp, Lh, self.e_cm, inertia, creep_factor=2.0)
        d_lim = span_limit_mm(Lh, 350.0)

        bending_util = msd / mrd if mrd > 0 else 999.0
        shear_util   = vsd / vrd if vrd > 0 else 999.0

        stair.result = StairSlabResult(
            span_h_m=Lh,
            sd_uls_kn_m2=round(qd, 3),
            msd_knm_m=round(msd, 2),
            vsd_kn_m=round(vsd, 2),
            mrd_knm_m=round(mrd, 2),
            vrd_c_kn_m=round(vrd, 2),
            required_as_cm2_m=round(as_req, 2),
            deflection_final_mm=round(d_final, 1),
            deflection_limit_mm=round(d_lim, 1),
            deflection_utilization=round(d_final / d_lim, 3) if d_lim > 0 else 999.0,
            bending_utilization=round(bending_util, 3),
            shear_utilization=round(shear_util, 3),
            inclination_deg=alpha_deg,
        )
        return stair.result
