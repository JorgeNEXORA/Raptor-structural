import math
from core.model import Footing, FootingResult, Column, FootingType


class FoundationAnalyzer:
    """
    EC2 footing verification:
      - Soil bearing check (SLS)
      - Bending design by cantilever from column face  (§9.8.2)
      - Punching shear at control perimeter 2d          (§6.4.3)
    """

    def __init__(self, soil_allowable_mpa: float,
                 fck_mpa: float = 25.0, fyk_mpa: float = 500.0):
        self.soil_mpa = soil_allowable_mpa
        self.fck = fck_mpa
        self.fcd = fck_mpa / 1.5
        self.fyk = fyk_mpa
        self.fyd = fyk_mpa / 1.15
        self.fctm = (0.30 * fck_mpa ** (2.0 / 3.0)
                     if fck_mpa <= 50
                     else 2.12 * math.log(1.0 + (fck_mpa + 8.0) / 10.0))

    # ── self-weight ───────────────────────────────────────────────────────────
    def _self_weight(self, f: Footing) -> float:
        return 25.0 * (f.width_a_cm / 100.0) * (f.width_b_cm / 100.0) * (f.height_cm / 100.0)

    # ── soil stress ───────────────────────────────────────────────────────────
    def _concentric_sigma(self, nsd: float, f: Footing) -> tuple[float, float]:
        s = nsd / (f.area_m2() * 1000.0)     # MPa
        return s, s

    def _eccentric_sigmas(self, nsd: float, f: Footing) -> tuple[float, float]:
        a = f.width_a_cm / 100.0
        b = f.width_b_cm / 100.0
        qavg = nsd / (a * b)                  # kN/m²
        ex = abs(getattr(f, "eccentricity_x_cm", 0.0)) / 100.0
        ey = abs(getattr(f, "eccentricity_y_cm", 0.0)) / 100.0
        mx = nsd * ey;  my = nsd * ex
        wx = b * a ** 2 / 6.0;  wy = a * b ** 2 / 6.0
        dx = my / wy if wy > 0 else 0.0
        dy = mx / wx if wx > 0 else 0.0
        return (qavg - dx - dy) / 1000.0, (qavg + dx + dy) / 1000.0   # MPa

    # ── §9.8.2 — bending design (cantilever from column face) ────────────────
    def _bending_design(self, sigma_max_mpa: float,
                         f: Footing, col: Column) -> tuple[float, float, float, float]:
        d_mm = f.effective_depth_cm * 10.0
        # cantilever length (critical section at column face)
        a_m = max((f.width_a_cm - col.width_cm) / 2.0 / 100.0, 0.05)
        q_kn_m2 = sigma_max_mpa * 1000.0
        med_m = q_kn_m2 * a_m ** 2 / 2.0                # kNm / m width

        z_mm = min(0.9 * d_mm, d_mm - 25.0)
        as_req_mm2_m = med_m * 1e6 / (self.fyd * z_mm) if med_m > 0 else 0.0
        as_min_mm2_m = max(
            0.26 * self.fctm / self.fyk * 1000.0 * d_mm,   # §9.3.1.1
            0.0013 * 1000.0 * d_mm
        )
        as_cm2_m = max(as_req_mm2_m, as_min_mm2_m) / 100.0

        # MRd with provided As
        x_mm = as_cm2_m * 100.0 * self.fyd / (0.8 * 1000.0 * self.fcd)
        z_act = min(d_mm - 0.4 * x_mm, 0.95 * d_mm)
        mrd_m = as_cm2_m * 100.0 * self.fyd * z_act / 1e6

        util = med_m / mrd_m if mrd_m > 0 else 0.0
        return round(med_m, 2), round(mrd_m, 2), round(as_cm2_m, 2), round(util, 3)

    # ── §6.4.3 — punching at control perimeter 2d ────────────────────────────
    def _punching_check(self, nsd: float, f: Footing, col: Column) -> tuple[float, float]:
        d_mm  = f.effective_depth_cm * 10.0
        bc_mm = col.width_cm * 10.0
        hc_mm = col.depth_cm * 10.0
        # control perimeter u₁ at 2d from column face
        u1_mm = 2.0 * (bc_mm + hc_mm) + 4.0 * math.pi * 2.0 * d_mm
        # net punching force (soil reaction inside perimeter subtracted)
        a_int_m2 = ((bc_mm + 4.0 * d_mm) * (hc_mm + 4.0 * d_mm)
                    + math.pi * (2.0 * d_mm) ** 2) / 1e6
        sigma_mpa = nsd / (f.area_m2() * 1000.0)
        ved = max(nsd - sigma_mpa * 1000.0 * a_int_m2, 0.5 * nsd)
        # vRd,c (§6.4.4)
        CRdc  = 0.18 / 1.5
        k     = min(1.0 + math.sqrt(200.0 / d_mm), 2.0)
        rho_l = 0.005                         # representative value
        v_rdc = max(
            CRdc * k * (100.0 * rho_l * self.fck) ** (1.0 / 3.0),
            0.035 * k ** 1.5 * self.fck ** 0.5
        )
        vrd = v_rdc * u1_mm * d_mm / 1000.0   # kN
        return round(ved, 2), round(vrd, 2)

    # ── main ─────────────────────────────────────────────────────────────────
    def analyze(self, footing: Footing, column: Column) -> FootingResult:
        if column.result is None:
            raise ValueError(f"Column {column.id} not analyzed before footing.")

        nsd      = column.result.nsd_kn + self._self_weight(footing)
        req_area = nsd / (self.soil_mpa * 1000.0)

        is_ecc = footing.footing_type == FootingType.ECCENTRIC
        sigma_min, sigma_max = (
            self._eccentric_sigmas(nsd, footing) if is_ecc
            else self._concentric_sigma(nsd, footing)
        )

        med_m, mrd_m, as_cm2_m, bend_util = self._bending_design(
            sigma_max, footing, column)
        ved_p, vrd_p = self._punching_check(nsd, footing, column)

        adopted_as = max(as_cm2_m * footing.width_b_cm / 100.0, 4.71)

        uplift        = sigma_min < 0.0
        needs_balance = is_ecc and (uplift or sigma_max > self.soil_mpa * 0.95)

        footing.result = FootingResult(
            nsd_kn=round(nsd, 2),
            soil_stress_mpa=round(sigma_max, 4),
            required_area_m2=round(req_area, 3),
            punching_vsd_kn=ved_p,
            punching_vrd_kn=vrd_p,
            required_as_cm2=as_cm2_m,
            adopted_as_cm2=round(adopted_as, 2),
            soil_utilization=round(sigma_max / self.soil_mpa, 3) if self.soil_mpa > 0 else 999.0,
            punching_utilization=round(ved_p / vrd_p, 3) if vrd_p > 0 else 999.0,
            sigma_min_mpa=round(sigma_min, 4),
            sigma_max_mpa=round(sigma_max, 4),
            uplift_detected=uplift,
            needs_balance_beam=needs_balance,
            med_knm_m=med_m,
            mrd_knm_m=mrd_m,
            bending_utilization=bend_util,
        )
        return footing.result
