import math
from core.model import Beam, BeamResult
from analysis.combinations import CombinationEngine
from analysis.deflections import rectangular_inertia_m4, simply_supported_udl_deflection_mm, span_limit_mm
from analysis.serviceability import estimate_crack_width_mm, steel_stress_from_moment


class BeamAnalyzer:
    """
    EC2 beam verification:
      - MRd = As·fyd·z  (§6.1)
      - VRd,c  without shear reinforcement  (§6.2.2)
      - Deflection L/250  (§7.4)
      - Crack width wk ≤ 0.3 mm  (§7.3)
      - As,min / As,max  (§9.2.1.1)
    """

    def __init__(self, fck_mpa: float = 25.0, fyk_mpa: float = 500.0):
        self.fck = fck_mpa
        self.fcd = fck_mpa / 1.5
        self.fyk = fyk_mpa
        self.fyd = fyk_mpa / 1.15
        self.fctm = (0.30 * fck_mpa ** (2.0 / 3.0)
                     if fck_mpa <= 50
                     else 2.12 * math.log(1.0 + (fck_mpa + 8.0) / 10.0))
        self.e_cm = 22000.0 * ((fck_mpa + 8.0) / 10.0) ** 0.3   # §3.1.3
        self.comb = CombinationEngine()

    # ── §9.2.1.1 — minimum tensile reinforcement ─────────────────────────────
    def _as_min_cm2(self, beam: Beam) -> float:
        bw_mm = beam.width_cm * 10.0
        d_mm  = beam.effective_depth_cm * 10.0
        return max(
            0.26 * self.fctm / self.fyk * bw_mm * d_mm,
            0.0013 * bw_mm * d_mm
        ) / 100.0

    # ── §9.2.1.1 — maximum reinforcement ────────────────────────────────────
    def _as_max_cm2(self, beam: Beam) -> float:
        return 0.04 * beam.width_cm * beam.height_cm   # 4 % Ac

    # ── §6.1 — flexural resistance ───────────────────────────────────────────
    def _required_as_cm2(self, msd_knm: float, d_cm: float) -> float:
        z_mm = 0.9 * d_cm * 10.0
        return (msd_knm * 1e6) / (self.fyd * z_mm) / 100.0 if msd_knm > 0 else 0.0

    def _mrd_knm(self, beam: Beam, as_cm2: float) -> float:
        bw_mm  = beam.width_cm * 10.0
        d_mm   = beam.effective_depth_cm * 10.0
        As_mm2 = as_cm2 * 100.0
        x_mm   = As_mm2 * self.fyd / (0.8 * bw_mm * self.fcd)
        z_mm   = min(d_mm - 0.4 * x_mm, 0.95 * d_mm)
        return As_mm2 * self.fyd * z_mm / 1e6

    # ── §6.2.2 — shear resistance without stirrups ───────────────────────────
    def _vrd_c_kn(self, beam: Beam, as_cm2: float) -> float:
        bw_mm  = beam.width_cm * 10.0
        d_mm   = beam.effective_depth_cm * 10.0
        As_mm2 = as_cm2 * 100.0

        CRdc  = 0.18 / 1.5                             # = 0.12
        k     = min(1.0 + math.sqrt(200.0 / d_mm), 2.0)
        rho_l = min(As_mm2 / (bw_mm * d_mm), 0.02)

        v_rdc = CRdc * k * (100.0 * rho_l * self.fck) ** (1.0 / 3.0)
        v_min = 0.035 * k ** 1.5 * self.fck ** 0.5

        return max(v_rdc, v_min) * bw_mm * d_mm / 1000.0   # kN

    # ── main ─────────────────────────────────────────────────────────────────
    def analyze(self, beam: Beam) -> BeamResult:
        gk = beam.total_gk()
        qk = beam.total_qk()
        qd     = self.comb.uls_fundamental(gk, qk)
        q_rare = self.comb.sls_rare(gk, qk)
        q_freq = self.comb.sls_frequent(gk, qk)
        q_qp   = self.comb.sls_quasi_permanent(gk, qk)
        l = beam.span_m

        msd = qd * l ** 2 / 8.0
        vsd = qd * l / 2.0

        as_min = self._as_min_cm2(beam)
        as_req = max(self._required_as_cm2(msd, beam.effective_depth_cm), as_min)

        vrd = self._vrd_c_kn(beam, as_req)
        mrd = self._mrd_knm(beam, as_req)

        inertia = rectangular_inertia_m4(beam.width_cm / 100.0, beam.height_cm / 100.0)
        d_inst, d_final = simply_supported_udl_deflection_mm(
            q_qp, l, self.e_cm, inertia, creep_factor=1.5)
        d_lim = span_limit_mm(l, 250.0)

        m_sls   = q_freq * l ** 2 / 8.0
        z_mm    = 0.9 * beam.effective_depth_cm * 10.0
        sigma_s = steel_stress_from_moment(m_sls, as_req, z_mm)
        crack   = estimate_crack_width_mm(sigma_s, bar_diameter_mm=12.0, spacing_factor=1.1)

        bending_util = msd / mrd if mrd > 0 else 999.0

        result = BeamResult(
            sd_uls_kn_m=qd, sd_sls_rare_kn_m=q_rare,
            sd_sls_freq_kn_m=q_freq, sd_sls_qp_kn_m=q_qp,
            msd_knm=round(msd, 2), vsd_kn=round(vsd, 2),
            reaction_left_kn=round(vsd, 2), reaction_right_kn=round(vsd, 2),
            required_as_cm2=round(as_req, 2),
            vrd_kn=round(vrd, 2),
            bending_utilization=round(bending_util, 3),
            shear_utilization=round(vsd / vrd, 3) if vrd > 0 else 999.0,
            deflection_inst_mm=round(d_inst, 1),
            deflection_final_mm=round(d_final, 1),
            deflection_limit_mm=round(d_lim, 1),
            deflection_utilization=round(d_final / d_lim, 3) if d_lim > 0 else 999.0,
            crack_width_mm=round(crack, 4),
            crack_limit_mm=0.3,
            crack_utilization=round(crack / 0.3, 3),
            mrd_knm=round(mrd, 2),
            vrd_c_kn=round(vrd, 2),
            as_min_cm2=round(as_min, 2),
        )
        beam.result = result
        return result
