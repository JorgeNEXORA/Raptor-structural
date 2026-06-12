import math
from core.model import Column, ColumnResult
from analysis.combinations import CombinationEngine


class ColumnAnalyzer:
    """
    EC2 column verification:
      - NRd = Ac·fcd + As·fyd                           §6.1
      - Slenderness λ vs λ_lim                           §5.8.3
      - Minimum eccentricity e₀ = max(h/30, 20 mm)      §6.1(4)
    """

    def __init__(self, fck_mpa: float = 25.0, fyk_mpa: float = 500.0):
        self.fck = fck_mpa
        self.fcd = fck_mpa / 1.5                          # §2.4.2.4  γc = 1.5
        self.fyk = fyk_mpa
        self.fyd = fyk_mpa / 1.15                         # §2.4.2.4  γs = 1.15
        self.fctm = (0.30 * fck_mpa ** (2.0 / 3.0)
                     if fck_mpa <= 50
                     else 2.12 * math.log(1.0 + (fck_mpa + 8.0) / 10.0))
        self.comb = CombinationEngine()

    # ── §9.5.2 — longitudinal reinforcement limits ───────────────────────────
    def _as_limits_cm2(self, nsd_kn: float, ac_cm2: float) -> tuple[float, float]:
        ac_mm2 = ac_cm2 * 100.0
        as_min = max(
            0.10 * nsd_kn * 1000.0 / self.fyd,   # 0.10·NEd/fyd
            0.002 * ac_mm2                         # 0.2 % Ac
        ) / 100.0
        as_max = 0.04 * ac_mm2 / 100.0            # 4 % Ac
        return as_min, as_max

    # ── §6.1 — axial resistance ──────────────────────────────────────────────
    def _nrd_kn(self, ac_cm2: float, as_cm2: float) -> float:
        ac_mm2 = ac_cm2 * 100.0
        as_mm2 = as_cm2 * 100.0
        return (self.fcd * ac_mm2 + self.fyd * as_mm2) / 1000.0

    # ── §5.8.3 — slenderness limit ───────────────────────────────────────────
    def _slenderness(self, nsd_kn: float, ac_cm2: float, as_cm2: float,
                     l0_cm: float, i_cm: float) -> tuple[float, float, bool]:
        lam = l0_cm / i_cm

        ac_mm2 = ac_cm2 * 100.0
        as_mm2 = as_cm2 * 100.0
        n = max(nsd_kn * 1000.0 / (self.fcd * ac_mm2), 0.01)   # relative axial force
        omega = (as_mm2 * self.fyd) / (ac_mm2 * self.fcd)       # mechanical reinf. ratio
        B = math.sqrt(1.0 + 2.0 * omega)
        # A = 0.7, C = 0.7  (conservative — creep and moment ratio unknown)
        lam_lim = 20.0 * 0.7 * B * 0.7 / math.sqrt(n)

        return round(lam, 1), round(lam_lim, 1), lam <= lam_lim

    # ── §6.1(4) — minimum eccentricity check ────────────────────────────────
    def _eccentricity(self, nsd_kn: float, h_cm: float,
                      as_cm2: float) -> tuple[float, float, float]:
        e0_cm = max(h_cm / 30.0, 2.0)              # ≥ 20 mm
        med_min = nsd_kn * e0_cm / 100.0            # kNm

        d_mm = h_cm * 10.0 - 40.0                   # approx. effective depth (40 mm cover)
        z_mm = max(0.9 * d_mm, 10.0)
        mrd = (as_cm2 * 50.0) * self.fyd * z_mm / 1e6   # symmetric: As/2 each side

        util = med_min / max(mrd, 0.001)
        return round(med_min, 2), round(mrd, 2), round(util, 3)

    # ── main ─────────────────────────────────────────────────────────────────
    def analyze(self, column: Column) -> ColumnResult:
        gk = column.total_gk() + 4.69              # tributary self-weight (kN)
        qk = column.total_qk()
        nsd = self.comb.uls_fundamental(gk, qk)

        ac_cm2 = column.area_cm2()
        i_cm   = column.radius_of_gyration_cm()    # handles both shapes

        as_min, as_max = self._as_limits_cm2(nsd, ac_cm2)
        req_as = max(as_min, 0.003 * ac_cm2)       # §9.5.2: ≥ 0.3 % Ac
        adopted_as = max(req_as, 4 * 0.785)        # minimum 4Ø10

        nrd = self._nrd_kn(ac_cm2, adopted_as)
        axial_util = nsd / nrd if nrd > 0 else 999.0

        l0_cm = column.height_m * 100.0             # pin-pin (conservative)
        lam, lam_lim, buckling_ok = self._slenderness(
            nsd, ac_cm2, adopted_as, l0_cm, i_cm)

        med_min, mrd, bend_util = self._eccentricity(nsd, column.depth_cm, adopted_as)

        utilization = round(max(axial_util, bend_util), 3)

        column.result = ColumnResult(
            nsd_kn=round(nsd, 2),
            nrd_kn=round(nrd, 2),
            required_as_cm2=round(req_as, 2),
            adopted_as_cm2=round(adopted_as, 2),
            slenderness=lam,
            utilization=utilization,
            lambda_lim=lam_lim,
            buckling_ok=buckling_ok,
            mrd_knm=mrd,
            med_min_knm=med_min,
            bending_utilization=bend_util,
        )
        return column.result
