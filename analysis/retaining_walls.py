"""
EC2 / geotechnical design of cantilever retaining walls and strip footings.

Checks performed:
  - Sliding (EC7 simplified):  Fv·tan(φ_d) / Fh ≥ 1.5
  - Overturning:               M_stab / M_overturning ≥ 2.0
  - Bearing:                   σ_max ≤ σ_adm
  - Stem flexure (EC2):        As,stem at base
  - Heel flexure (EC2):        As,heel
"""
import math
from core.model import (
    ContinuousFooting, ContinuousFootingResult,
    RetainingWall, RetainingWallResult,
)


class RetainingWallAnalyzer:
    def __init__(self, fck_mpa: float = 25.0, fyk_mpa: float = 500.0,
                 soil_allowable_mpa: float = 0.20):
        self.fck = fck_mpa
        self.fyk = fyk_mpa
        self.sigma_adm = soil_allowable_mpa
        # EC2 material partial factors
        self.gamma_c = 1.5
        self.gamma_s = 1.15
        self.fcd = fck_mpa / self.gamma_c
        self.fyd = min(fyk_mpa / self.gamma_s, 435.0)

    def analyze(self, wall: RetainingWall) -> None:
        H  = wall.height_m
        bw = wall.base_width_m
        ht = wall.base_thickness_cm / 100.0   # base slab height in m
        st = wall.stem_thickness_cm / 100.0   # stem thickness at base
        heel = wall.heel_m
        toe  = wall.toe_m
        γ    = wall.gamma_soil_kn_m3
        φ    = math.radians(wall.phi_deg)
        q    = wall.surcharge_kn_m2

        # Rankine active earth pressure coefficient
        Ka = (1 - math.sin(φ)) / (1 + math.sin(φ))

        # Total height of retained fill above base underside
        H_total = H + ht

        # Horizontal earth force (per metre width)
        Fh_earth  = 0.5 * Ka * γ * H_total**2
        Fh_surch  = Ka * q * H_total
        Fh = Fh_earth + Fh_surch

        # Application heights for overturning (from base underside)
        arm_earth = H_total / 3.0
        arm_surch = H_total / 2.0

        # Overturning moment about toe
        M_overturning = Fh_earth * arm_earth + Fh_surch * arm_surch

        # Stabilising forces (self-weight of wall + soil on heel)
        # Stem self-weight: average thickness × H (simplified)
        stem_avg = st * 0.85  # taper factor
        W_stem = stem_avg * H * 25.0  # kN/m (γ_concrete = 25 kN/m³)
        W_base = bw * ht * 25.0
        W_soil = heel * H * γ   # soil on heel

        # Positions from toe
        x_stem = toe + st / 2.0
        x_base = bw / 2.0
        x_soil = toe + st + heel / 2.0

        M_stab = W_stem * x_stem + W_base * x_base + W_soil * x_soil
        Fv     = W_stem + W_base + W_soil

        # Bearing pressure (assuming linear distribution)
        e = bw / 2.0 - (M_stab - M_overturning) / Fv   # eccentricity from centre
        e = max(e, 0.0)
        if e < bw / 6.0:
            sigma_max = Fv / bw * (1 + 6 * e / bw)
            sigma_min = Fv / bw * (1 - 6 * e / bw)
        else:
            # Triangular distribution
            sigma_max = 2 * Fv / (3 * (bw / 2.0 - e)) if (bw / 2.0 - e) > 0 else 9999
            sigma_min = 0.0

        sigma_max_mpa = sigma_max / 1000.0   # kPa → MPa

        # Safety checks
        tan_phi_d = math.tan(math.atan(math.tan(φ) / 1.25))  # design friction
        sliding_sf     = Fv * tan_phi_d / max(Fh, 0.001)
        overturning_sf = M_stab / max(M_overturning, 0.001)
        bearing_util   = sigma_max_mpa / max(self.sigma_adm, 0.001)

        # EC2 stem reinforcement (at base, cantilever beam)
        # ULS moment: γG=1.35 × Fh moment at base of stem
        M_stem_uls = 1.35 * (0.5 * Ka * γ * H**2 * H/3.0 + Ka * q * H * H/2.0)
        d_stem = st - 0.05   # effective depth (50mm cover)
        As_stem = self._as_required(M_stem_uls, d_stem, 1.0)

        # EC2 heel reinforcement (base slab acts as cantilever)
        # Load: soil weight on heel minus upward soil reaction
        q_heel = γ * H - sigma_min   # net upward pressure difference (simplification)
        q_heel = max(q_heel, 0.0)
        M_heel_uls = 1.35 * q_heel * heel**2 / 2.0
        d_heel = ht - 0.05
        As_heel = self._as_required(M_heel_uls, d_heel, 1.0)

        wall.result = RetainingWallResult(
            earth_pressure_kn_m=Fh,
            moment_base_knm_m=M_overturning,
            shear_base_kn_m=Fh,
            axial_base_kn_m=Fv,
            sliding_safety=round(sliding_sf, 2),
            overturning_safety=round(overturning_sf, 2),
            bearing_stress_mpa=round(sigma_max_mpa, 4),
            bearing_utilization=round(bearing_util, 3),
            required_as_stem_cm2_m=round(As_stem * 10000, 2),   # m² → cm²
            required_as_heel_cm2_m=round(As_heel * 10000, 2),
            sliding_ok=sliding_sf >= 1.5,
            overturning_ok=overturning_sf >= 2.0,
            bearing_ok=bearing_util <= 1.0,
        )

    def _as_required(self, Med_knm_m: float, d_m: float, width_m: float) -> float:
        """Return required steel area (m²/m) for rectangular section."""
        if Med_knm_m <= 0 or d_m <= 0:
            return 0.0
        Med = Med_knm_m * 1000  # Nm/m
        fcd_pa = self.fcd * 1e6
        fyd_pa = self.fyd * 1e6
        mu = Med / (width_m * d_m**2 * fcd_pa)
        mu = min(mu, 0.295)  # limit to avoid compression rebar
        omega = 1.0 - math.sqrt(max(1.0 - 2 * mu, 0.0))
        As = omega * width_m * d_m * fcd_pa / fyd_pa
        # Minimum: 0.0013 × b × d
        As_min = 0.0013 * width_m * d_m
        return max(As, As_min)


class ContinuousFootingAnalyzer:
    def __init__(self, fck_mpa: float = 25.0, fyk_mpa: float = 500.0,
                 soil_allowable_mpa: float = 0.20):
        self.fck = fck_mpa
        self.fyk = fyk_mpa
        self.sigma_adm = soil_allowable_mpa
        self.gamma_c = 1.5
        self.gamma_s = 1.15
        self.fcd = fck_mpa / self.gamma_c
        self.fyd = min(fyk_mpa / self.gamma_s, 435.0)

    def analyze(self, footing: ContinuousFooting) -> None:
        b = footing.width_cm / 100.0    # footing width in m
        h = footing.height_cm / 100.0
        L = footing.length_m
        Gk = footing.load_gk_kn_m
        Qk = footing.load_qk_kn_m
        d  = footing.effective_depth_cm / 100.0 if footing.effective_depth_cm > 0 else h - 0.05

        # Soil bearing (SLS)
        N_sls = (Gk + Qk) * L
        sigma = N_sls / (b * L)   # kN/m²
        sigma_mpa = sigma / 1000.0

        # ULS bending (footing acts as cantilever from wall face)
        # Assume wall stem ≈ 0.25m wide → cantilever = (b - 0.25)/2
        c_cant = max((b - 0.25) / 2.0, 0.05)
        q_uls = (1.35 * Gk + 1.5 * Qk) / b  # ULS pressure kN/m per unit length
        Med = q_uls * c_cant**2 / 2.0         # kNm/m

        fcd_pa = self.fcd * 1e6
        fyd_pa = self.fyd * 1e6
        mu = Med * 1000 / (1.0 * d**2 * fcd_pa)
        mu = min(mu, 0.295)
        omega = 1.0 - math.sqrt(max(1 - 2 * mu, 0.0))
        As = omega * 1.0 * d * fcd_pa / fyd_pa
        As_min = 0.0013 * 1.0 * d
        As = max(As, As_min)
        As_cm2_m = As * 10000

        # MRd
        z = d * (1 - 0.4 * omega)
        Mrd = As * fyd_pa * z / 1000  # kNm/m

        # Shear (EC2 §6.2.2, no shear reinforcement)
        Vsd = q_uls * c_cant
        rho = min(As / (1.0 * d), 0.02)
        k = min(1 + math.sqrt(0.2 / d), 2.0)
        fck_pa = self.fck * 1e6
        vrd_c = max(0.18 / self.gamma_c * k * (100 * rho * self.fck) ** (1/3),
                    0.035 * k**1.5 * self.fck**0.5)
        Vrd_c = vrd_c * 1.0 * d * 1000  # kN/m

        footing.result = ContinuousFootingResult(
            soil_stress_mpa=round(sigma_mpa, 4),
            soil_utilization=round(sigma_mpa / max(self.sigma_adm, 0.001), 3),
            required_as_cm2_m=round(As_cm2_m, 2),
            med_knm_m=round(Med, 2),
            mrd_knm_m=round(Mrd, 2),
            bending_utilization=round(Med / max(Mrd, 0.001), 3),
            vsd_kn_m=round(Vsd, 2),
            vrd_c_kn_m=round(Vrd_c, 2),
            shear_utilization=round(Vsd / max(Vrd_c, 0.001), 3),
        )
