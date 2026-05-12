import math
from core.model import ShearWall, ShearWallResult
from analysis.combinations import CombinationEngine


class ShearWallAnalyzer:
    """
    EC2 shear wall (parede estrutural) verification:
      - Vertical compression:  NRd = Ac·fcd + As_v·fyd       §6.1
      - In-plane shear:        VRd,c  (§6.2.2, web section)
      - Flexure at base:       MRd from boundary bars + NEd   §6.1
      - Slenderness:           λ = l0/i_w vs λ_lim            §5.8.3
      - Reinforcement limits:  §9.6
    """

    def __init__(self, fck_mpa: float = 25.0, fyk_mpa: float = 500.0):
        self.fck = fck_mpa
        self.fcd = fck_mpa / 1.5
        self.fyk = fyk_mpa
        self.fyd = fyk_mpa / 1.15
        self.fctm = (0.30 * fck_mpa ** (2.0 / 3.0)
                     if fck_mpa <= 50
                     else 2.12 * math.log(1.0 + (fck_mpa + 8.0) / 10.0))
        self.comb = CombinationEngine()

    # ── §9.6.2 — minimum wall reinforcement ─────────────────────────────────
    def _as_min_v_cm2(self, wall: ShearWall) -> float:
        ac_mm2 = wall.length_m * 1000.0 * wall.thickness_cm * 10.0
        return max(0.002 * ac_mm2, 0.0013 * wall.thickness_cm * 10.0 * 1000.0) / 100.0

    def _as_min_h_cm2_m(self, wall: ShearWall) -> float:
        bw_mm = wall.thickness_cm * 10.0
        return max(0.001 * bw_mm * 1000.0, 150.0) / 100.0   # ≥ 0.1%·bw/m, ≥ 1.5 cm²/m

    # ── §6.1 — axial resistance ──────────────────────────────────────────────
    def _nrd_kn(self, wall: ShearWall, as_v_cm2: float) -> float:
        ac_mm2 = wall.length_m * 1000.0 * wall.thickness_cm * 10.0
        as_mm2 = as_v_cm2 * 100.0
        return (self.fcd * ac_mm2 + self.fyd * as_mm2) / 1000.0

    # ── §5.8.3 — wall slenderness (out-of-plane buckling) ────────────────────
    def _slenderness(self, wall: ShearWall, ned_kn: float,
                     as_v_cm2: float) -> tuple[float, float, bool]:
        bw_mm = wall.thickness_cm * 10.0
        i_mm  = bw_mm / math.sqrt(12.0)           # radius of gyration (thickness direction)
        l0_mm = wall.height_m * 1000.0             # effective length (pin-pin conservative)
        lam   = l0_mm / i_mm

        ac_mm2  = wall.length_m * 1000.0 * bw_mm
        as_mm2  = as_v_cm2 * 100.0
        n       = max(ned_kn * 1000.0 / (self.fcd * ac_mm2), 0.01)
        omega   = (as_mm2 * self.fyd) / (ac_mm2 * self.fcd)
        B       = math.sqrt(1.0 + 2.0 * omega)
        lam_lim = 20.0 * 0.7 * B * 0.7 / math.sqrt(n)

        return round(lam, 1), round(lam_lim, 1), lam <= lam_lim

    # ── §6.2.2 — in-plane shear resistance ──────────────────────────────────
    def _vrd_c_kn(self, wall: ShearWall, as_h_cm2_m: float) -> float:
        bw_mm = wall.thickness_cm * 10.0
        # Effective depth in shear = 0.8 × wall length (horizontal plane)
        d_mm  = wall.length_m * 1000.0 * 0.8
        # Total horizontal As over the wall height taken per linear meter × height
        As_mm2 = as_h_cm2_m * 100.0 * wall.length_m

        CRdc  = 0.18 / 1.5
        k     = min(1.0 + math.sqrt(200.0 / max(d_mm, 1.0)), 2.0)
        rho_l = min(As_mm2 / (bw_mm * d_mm), 0.02)

        v_rdc = CRdc * k * (100.0 * rho_l * self.fck) ** (1.0 / 3.0)
        v_min = 0.035 * k ** 1.5 * self.fck ** 0.5
        return max(v_rdc, v_min) * bw_mm * d_mm / 1000.0

    # ── §6.1 — bending resistance at base (simplified) ───────────────────────
    def _mrd_knm(self, wall: ShearWall, as_v_cm2: float, ned_kn: float) -> float:
        # 25 % of vertical bars concentrated at each boundary end
        As_end_mm2 = as_v_cm2 * 100.0 * 0.25
        z_mm = 0.8 * wall.length_m * 1000.0     # internal lever arm ≈ 0.8·Lw
        mrd_bars  = As_end_mm2 * self.fyd * z_mm / 1e6
        # NEd acts as stabilising moment on the compression side
        mrd_axial = ned_kn * wall.length_m / 4.0
        return round(mrd_bars + mrd_axial, 1)

    # ── main ─────────────────────────────────────────────────────────────────
    def analyze(self, wall: ShearWall) -> ShearWallResult:
        ned = wall.ned_kn
        ved = wall.ved_kn
        med = wall.med_knm

        as_min_v   = self._as_min_v_cm2(wall)
        as_min_h   = self._as_min_h_cm2_m(wall)
        as_v       = max(as_min_v, 0.004 * wall.length_m * wall.thickness_cm * 100.0)
        as_h       = max(as_min_h, 0.002 * wall.thickness_cm * 10.0 * 10.0 / 100.0)

        nrd                   = self._nrd_kn(wall, as_v)
        lam, lam_lim, b_ok    = self._slenderness(wall, ned, as_v)
        vrd                   = self._vrd_c_kn(wall, as_h)
        mrd                   = self._mrd_knm(wall, as_v, ned)

        ac_mm2  = wall.length_m * 1000.0 * wall.thickness_cm * 10.0
        sigma_v = ned * 1000.0 / ac_mm2 if ac_mm2 > 0 else 0.0

        axial_util = ned / nrd if nrd > 0 else 999.0
        shear_util = ved / vrd if vrd > 0 else (0.0 if ved == 0 else 999.0)
        bend_util  = med / mrd if mrd > 0 else (0.0 if med == 0 else 999.0)

        wall.result = ShearWallResult(
            ned_kn=round(ned, 2),
            nrd_kn=round(nrd, 2),
            ved_kn=round(ved, 2),
            vrd_kn=round(vrd, 2),
            med_knm=round(med, 2),
            mrd_knm=round(mrd, 2),
            sigma_v_mpa=round(sigma_v, 4),
            axial_utilization=round(axial_util, 3),
            shear_utilization=round(shear_util, 3),
            bending_utilization=round(bend_util, 3),
            slenderness=lam,
            lambda_lim=lam_lim,
            buckling_ok=b_ok,
            required_as_v_cm2=round(as_v, 2),
            required_as_h_cm2_m=round(as_h, 2),
        )
        return wall.result
