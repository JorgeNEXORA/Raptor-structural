import math
from core.model import SlabPanel, SlabResult, SlabType
from analysis.combinations import CombinationEngine
from analysis.deflections import slab_strip_inertia_m4, simply_supported_udl_deflection_mm, span_limit_mm
from analysis.serviceability import estimate_crack_width_mm, steel_stress_from_moment
try:
    from config.slab_catalog import CATALOG, SlabCatalogEntry
    _CATALOG_AVAILABLE = bool(CATALOG)
except Exception:
    CATALOG = {}
    _CATALOG_AVAILABLE = False

# ── Marcus table for simply-supported two-way slabs ──────────────────────────
# ratio = Ly/Lx (≥ 1)  →  (αx, αy)   where MEd,x = αx·qd·Lx²  (kNm/m)
_MARCUS_TABLE = [
    (1.00, 0.0479, 0.0479),
    (1.10, 0.0554, 0.0399),
    (1.20, 0.0627, 0.0327),
    (1.30, 0.0694, 0.0268),
    (1.40, 0.0753, 0.0220),
    (1.50, 0.0812, 0.0179),
    (1.75, 0.0908, 0.0112),
    (2.00, 0.0965, 0.0073),
]
_ALPHA_ONE_WAY = 0.1250   # qd·Lx²/8


def _marcus_alpha(ratio: float) -> tuple[float, float]:
    """Linearly interpolate Marcus factors for given Ly/Lx ratio."""
    if ratio >= 2.0:
        return _ALPHA_ONE_WAY, 0.0
    for i in range(len(_MARCUS_TABLE) - 1):
        r0, ax0, ay0 = _MARCUS_TABLE[i]
        r1, ax1, ay1 = _MARCUS_TABLE[i + 1]
        if r0 <= ratio <= r1:
            t = (ratio - r0) / (r1 - r0)
            return ax0 + t * (ax1 - ax0), ay0 + t * (ay1 - ay0)
    return _MARCUS_TABLE[0][1], _MARCUS_TABLE[0][2]


class SlabAnalyzer:
    """
    EC2 slab strip verification:
      - One-way:  MEd = qd·L²/8
      - Two-way:  MEd = αx·qd·Lx²  (Marcus method)
      - As,min per §9.3.1.1
      - Deflection L/250  (§7.4)
      - Crack width wk ≤ 0.3 mm  (§7.3)
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

    # ── catalog-based analysis (ribbed slabs) ────────────────────────────────
    def _analyze_ribbed(self, slab: SlabPanel) -> SlabResult:
        """
        Laje aligeirada com vigotas pré-esforçadas.
        MRd e VRd vêm do catálogo do fabricante (Presdouro).
        Deflexão calculada com EI do catálogo.
        """
        gk = slab.gk_kn_m2
        qk = slab.qk_kn_m2
        sd_uls = self.comb.uls_fundamental(gk, qk)
        sd_rare = self.comb.sls_rare(gk, qk)
        sd_freq = self.comb.sls_frequent(gk, qk)
        sd_qp   = self.comb.sls_quasi_permanent(gk, qk)
        lx = slab.span_m

        msd = sd_uls * lx ** 2 / 8.0
        vsd = sd_uls * lx / 2.0

        # MRd / VRd from catalog if available
        entry = CATALOG.get(slab.catalog_id) if slab.catalog_id else None
        if entry:
            mrd = entry.mrd_knm_m
            vrd = entry.vrd_kn_m
            ei  = entry.ei_kn_m2_m   # kN·m²/m
            e_use = ei / (slab.thickness_cm / 100.0) ** 3 * 12.0   # back-calc E for deflection
            inertia = slab_strip_inertia_m4(slab.thickness_cm / 100.0, 1.0)
            # Use catalog EI directly for deflection
            q_n = sd_qp * 1000.0
            span = lx
            d_inst_m = 5 * q_n * span ** 4 / (384 * ei * 1000.0)   # EI in kN·m²
            d_inst = d_inst_m * 1000.0
            d_final = d_inst * 3.0   # creep factor 2 → total = 3×inst
        else:
            # Fall back to equivalent solid slab
            mrd = self._mrd_from_as(msd, slab.effective_depth_cm)
            vrd = 999.0
            inertia = slab_strip_inertia_m4(slab.thickness_cm / 100.0, 1.0)
            d_inst, d_final = simply_supported_udl_deflection_mm(
                sd_qp, lx, self.e_cm, inertia, creep_factor=2.0)

        d_lim = span_limit_mm(lx, 250.0)
        bend_util  = msd / mrd if mrd > 0 else 999.0
        shear_util = vsd / vrd if vrd > 0 else 0.0

        as_min = self._as_min_cm2_m(slab.effective_depth_cm)
        as_req = max(self._required_as_cm2_m(msd, slab.effective_depth_cm), as_min)
        m_sls   = sd_freq * lx ** 2 / 8.0
        z_mm    = 0.9 * slab.effective_depth_cm * 10.0
        sigma_s = steel_stress_from_moment(m_sls, as_req, z_mm)
        crack   = estimate_crack_width_mm(sigma_s, bar_diameter_mm=8.0, spacing_factor=1.0)

        slab.result = SlabResult(
            sd_uls_kn_m2=sd_uls, sd_sls_rare_kn_m2=sd_rare,
            sd_sls_freq_kn_m2=sd_freq, sd_sls_qp_kn_m2=sd_qp,
            msd_knm_m=round(msd, 2), vsd_kn_m=round(vsd, 2),
            reaction_gk_kn_m=round(gk * lx / 2, 2),
            reaction_qk_kn_m=round(qk * lx / 2, 2),
            reaction_uls_kn_m=round(sd_uls * lx / 2, 2),
            deflection_inst_mm=round(d_inst, 1),
            deflection_final_mm=round(d_final, 1),
            deflection_limit_mm=round(d_lim, 1),
            deflection_utilization=round(d_final / d_lim, 3) if d_lim > 0 else 999.0,
            crack_width_mm=round(crack, 4),
            crack_limit_mm=0.3,
            crack_utilization=round(crack / 0.3, 3),
        )
        return slab.result

    def _mrd_from_as(self, msd: float, d_cm: float) -> float:
        as_req = max(self._required_as_cm2_m(msd, d_cm), self._as_min_cm2_m(d_cm))
        z_mm = 0.9 * d_cm * 10.0
        return as_req * 100.0 * self.fyd * z_mm / 1e6

    # ── cantilever analysis ───────────────────────────────────────────────────
    def _analyze_cantilever(self, slab: SlabPanel) -> SlabResult:
        """Consola — MEd = qd·L²/2  (encastramento na viga/pilar)."""
        gk = slab.gk_kn_m2
        qk = slab.qk_kn_m2
        sd_uls = self.comb.uls_fundamental(gk, qk)
        sd_rare = self.comb.sls_rare(gk, qk)
        sd_freq = self.comb.sls_frequent(gk, qk)
        sd_qp   = self.comb.sls_quasi_permanent(gk, qk)
        lx = slab.span_m

        msd = sd_uls * lx ** 2 / 2.0     # cantilever
        vsd = sd_uls * lx                 # reaction at root

        as_min = self._as_min_cm2_m(slab.effective_depth_cm)
        as_req = max(self._required_as_cm2_m(msd, slab.effective_depth_cm), as_min)
        mrd = self._mrd_from_as(msd, slab.effective_depth_cm)

        inertia = slab_strip_inertia_m4(slab.thickness_cm / 100.0, 1.0)
        # Cantilever tip deflection: δ = qp·L⁴/(8·EI)
        q_n = sd_qp * 1000.0
        d_inst_m = q_n * lx ** 4 / (8.0 * self.e_cm * 1e6 * inertia)
        d_inst = d_inst_m * 1000.0
        d_final = d_inst * 3.0
        d_lim = span_limit_mm(lx, 250.0)   # L/250 tip deflection

        m_sls   = sd_freq * lx ** 2 / 2.0
        z_mm    = 0.9 * slab.effective_depth_cm * 10.0
        sigma_s = steel_stress_from_moment(m_sls, as_req, z_mm)
        crack   = estimate_crack_width_mm(sigma_s, bar_diameter_mm=8.0, spacing_factor=1.0)

        slab.result = SlabResult(
            sd_uls_kn_m2=sd_uls, sd_sls_rare_kn_m2=sd_rare,
            sd_sls_freq_kn_m2=sd_freq, sd_sls_qp_kn_m2=sd_qp,
            msd_knm_m=round(msd, 2), vsd_kn_m=round(vsd, 2),
            reaction_gk_kn_m=round(gk * lx, 2),
            reaction_qk_kn_m=round(qk * lx, 2),
            reaction_uls_kn_m=round(sd_uls * lx, 2),
            deflection_inst_mm=round(d_inst, 1),
            deflection_final_mm=round(d_final, 1),
            deflection_limit_mm=round(d_lim, 1),
            deflection_utilization=round(d_final / d_lim, 3) if d_lim > 0 else 999.0,
            crack_width_mm=round(crack, 4),
            crack_limit_mm=0.3,
            crack_utilization=round(crack / 0.3, 3),
        )
        return slab.result

    # ── main ─────────────────────────────────────────────────────────────────
    def analyze(self, slab: SlabPanel) -> SlabResult:
        stype = slab.slab_type
        if stype == SlabType.RIBBED:
            return self._analyze_ribbed(slab)
        if stype == SlabType.CANTILEVER:
            return self._analyze_cantilever(slab)

        gk = slab.gk_kn_m2
        qk = slab.qk_kn_m2
        sd_uls  = self.comb.uls_fundamental(gk, qk)
        sd_rare = self.comb.sls_rare(gk, qk)
        sd_freq = self.comb.sls_frequent(gk, qk)
        sd_qp   = self.comb.sls_quasi_permanent(gk, qk)
        lx = slab.span_m

        # Determine two-way ratio from area if available
        if (stype == SlabType.TWO_WAY
                and slab.area_m2 is not None and slab.area_m2 > 0 and lx > 0):
            ly = slab.area_m2 / lx
            ratio = max(ly / lx, lx / ly)
            ratio = max(ratio, 1.0)
        else:
            ratio = 2.0

        if stype == SlabType.TWO_WAY and ratio < 2.0:
            ax, _ = _marcus_alpha(ratio)
            msd = ax * sd_uls * lx ** 2
        else:
            msd = sd_uls * lx ** 2 / 8.0

        vsd  = sd_uls * lx / 2.0
        rg   = gk * lx / 2.0
        rq   = qk * lx / 2.0
        ruls = sd_uls * lx / 2.0

        inertia = slab_strip_inertia_m4(slab.thickness_cm / 100.0, 1.0)
        d_inst, d_final = simply_supported_udl_deflection_mm(
            sd_qp, lx, self.e_cm, inertia, creep_factor=2.0)
        d_lim = span_limit_mm(lx, 250.0)

        m_sls   = sd_freq * lx ** 2 / 8.0
        as_min  = self._as_min_cm2_m(slab.effective_depth_cm)
        as_req  = max(self._required_as_cm2_m(msd, slab.effective_depth_cm), as_min)
        z_mm    = 0.9 * slab.effective_depth_cm * 10.0
        sigma_s = steel_stress_from_moment(m_sls, as_req, z_mm)
        crack   = estimate_crack_width_mm(sigma_s, bar_diameter_mm=8.0, spacing_factor=1.0)

        slab.result = SlabResult(
            sd_uls_kn_m2=sd_uls,
            sd_sls_rare_kn_m2=sd_rare,
            sd_sls_freq_kn_m2=sd_freq,
            sd_sls_qp_kn_m2=sd_qp,
            msd_knm_m=round(msd, 2),
            vsd_kn_m=round(vsd, 2),
            reaction_gk_kn_m=round(rg, 2),
            reaction_qk_kn_m=round(rq, 2),
            reaction_uls_kn_m=round(ruls, 2),
            deflection_inst_mm=round(d_inst, 1),
            deflection_final_mm=round(d_final, 1),
            deflection_limit_mm=round(d_lim, 1),
            deflection_utilization=round(d_final / d_lim, 3) if d_lim > 0 else 999.0,
            crack_width_mm=round(crack, 4),
            crack_limit_mm=0.3,
            crack_utilization=round(crack / 0.3, 3),
        )
        return slab.result
