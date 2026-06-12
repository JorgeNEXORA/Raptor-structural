"""
analysis/predim.py
──────────────────
Pre-dimensionamento de pilares por área tributária.

Método:
  1. Para cada pilar calcula a área tributária (metade da distância
     aos vizinhos em cada quadrante).
  2. Estima NEd = (1.35·gk + 1.50·qk) × A_trib × n_pisos  +  peso_próprio
  3. Determina a secção mínima normalizada tal que NRd ≥ NEd
     NRd = Ac·fcd + As·fyd   (As = ρ_min · Ac)

Secções normalizadas (cm):
  Retangulares: 20×20, 20×25, 25×25, 25×30, 30×30, 30×35, 30×40,
                35×35, 40×40, 40×45, 45×45, 50×50, 55×55, 60×60
  Circulares  : Ø25, Ø30, Ø35, Ø40, Ø45, Ø50, Ø55, Ø60, Ø70, Ø80
"""

import math
from dataclasses import dataclass
from typing import List

from core.model import Column


# ── Standard sections ────────────────────────────────────────────────────────
RECT_SECTIONS = [
    (20, 20), (20, 25), (25, 25), (25, 30), (30, 30),
    (30, 35), (30, 40), (35, 35), (40, 40), (40, 45),
    (45, 45), (50, 50), (55, 55), (60, 60), (70, 70),
]
CIRC_DIAMETERS = [25, 30, 35, 40, 45, 50, 55, 60, 70, 80]


@dataclass
class PreDimResult:
    col_id: str
    ned_kn: float           # estimated design axial force
    a_trib_m2: float        # tributary area
    width_cm: float
    depth_cm: float
    shape: str
    nrd_kn: float
    utilization: float


class ColumnPreDimensioner:
    """
    Pre-dimension all columns in a project given floor loads and storey count.
    Call `run()` to update column.width_cm / column.depth_cm / column.shape.
    """

    def __init__(self, fck_mpa: float = 25.0, fyk_mpa: float = 500.0,
                 rho_s: float = 0.01):
        """
        fck_mpa  — concrete strength
        fyk_mpa  — steel yield strength
        rho_s    — assumed reinforcement ratio for pre-dim (default 1 %)
        """
        self.fcd   = fck_mpa  / 1.5
        self.fyd   = fyk_mpa  / 1.15
        self.rho_s = rho_s
        self.gamma_c = 25.0   # kN/m³  RC self-weight

    # ── Resistance ───────────────────────────────────────────────────────────
    def _nrd(self, ac_cm2: float) -> float:
        """NRd (kN) with assumed reinforcement ratio ρ_s."""
        ac_mm2 = ac_cm2 * 100.0
        as_mm2 = self.rho_s * ac_mm2
        return (self.fcd * ac_mm2 + self.fyd * as_mm2) / 1000.0

    # ── Tributary area ───────────────────────────────────────────────────────
    def _tributary_area(self, col: Column, all_cols: List[Column],
                        default_span_m: float = 3.5) -> float:
        """
        Estimate tributary area for `col`.

        Strategy: for each of the 4 quadrants (±x, ±y) find the nearest
        neighbour column.  The tributary half-span in that direction is
        half the distance to that neighbour (or `default_span_m/2` if
        there is no neighbour in the quadrant).
        """
        dx_pos = dx_neg = dy_pos = dy_neg = default_span_m / 2.0

        for c in all_cols:
            if c.id == col.id:
                continue
            ddx = c.x - col.x
            ddy = c.y - col.y
            dist = math.hypot(ddx, ddy)
            if dist < 0.01:
                continue

            # Quadrant detection (allow ±30° cone around each axis)
            angle = abs(math.degrees(math.atan2(ddy, ddx)))
            in_x  = angle <= 30 or angle >= 150       # mostly horizontal
            in_y  = 60 <= angle <= 120                 # mostly vertical

            if in_x:
                half = abs(ddx) / 2.0
                if ddx > 0:
                    dx_pos = min(dx_pos, half)
                else:
                    dx_neg = min(dx_neg, half)
            if in_y:
                half = abs(ddy) / 2.0
                if ddy > 0:
                    dy_pos = min(dy_pos, half)
                else:
                    dy_neg = min(dy_neg, half)

        return (dx_pos + dx_neg) * (dy_pos + dy_neg)

    # ── Minimum standard section ─────────────────────────────────────────────
    def _min_section(self, ned_kn: float, shape: str,
                     safety: float = 1.0) -> tuple[float, float, float]:
        """
        Return (width_cm, depth_cm, nrd_kn) for the smallest standard
        section where NRd ≥ ned_kn × safety.
        """
        target = ned_kn * safety

        if shape == "circular":
            for diam in CIRC_DIAMETERS:
                ac = math.pi * diam ** 2 / 4.0
                nrd = self._nrd(ac)
                if nrd >= target:
                    return diam, diam, nrd
            d = CIRC_DIAMETERS[-1]
            return d, d, self._nrd(math.pi * d ** 2 / 4.0)
        else:
            for w, d in RECT_SECTIONS:
                nrd = self._nrd(w * d)
                if nrd >= target:
                    return w, d, nrd
            w, d = RECT_SECTIONS[-1]
            return w, d, self._nrd(w * d)

    # ── Main entry point ─────────────────────────────────────────────────────
    def run(self,
            columns: List[Column],
            gk_kn_m2: float,
            qk_kn_m2: float,
            n_floors: int,
            floor_height_m: float = 3.0,
            shape: str = "rectangular",
            safety: float = 1.10,
            default_span_m: float = 3.5) -> List[PreDimResult]:
        """
        Pre-dimension all columns and update their width_cm / depth_cm / shape
        in-place.

        Parameters
        ----------
        gk_kn_m2       permanent load per floor (kN/m²) — excluding self-weight
        qk_kn_m2       variable load per floor (kN/m²)
        n_floors        number of storeys above foundation
        floor_height_m  typical storey height (for column self-weight)
        shape           "rectangular" or "circular"
        safety          NRd ≥ safety × NEd  (default 1.10 = 10 % reserve)
        default_span_m  assumed span when no adjacent column found
        """
        gamma_g = 1.35
        gamma_q = 1.50
        results = []

        for col in columns:
            a_trib = self._tributary_area(col, columns, default_span_m)

            # Floor loads × n floors
            ned_floors = (gamma_g * gk_kn_m2 + gamma_q * qk_kn_m2) * a_trib * n_floors

            # Column self-weight (iterative: first estimate with 30×30 cm)
            ac_est_m2  = 0.09                       # 30×30 first guess
            ned_sw     = gamma_g * self.gamma_c * ac_est_m2 * floor_height_m * n_floors

            ned_total  = ned_floors + ned_sw

            w, d, nrd = self._min_section(ned_total, shape, safety)

            # Refine self-weight with chosen section
            ac_final_m2 = (math.pi * w ** 2 / 4.0 if shape == "circular"
                           else w * d) / 10000.0
            ned_sw2     = gamma_g * self.gamma_c * ac_final_m2 * floor_height_m * n_floors
            ned_final   = ned_floors + ned_sw2
            w, d, nrd   = self._min_section(ned_final, shape, safety)

            # Update column in-place
            col.width_cm  = w
            col.depth_cm  = d
            col.shape     = shape

            util = ned_final / nrd if nrd > 0 else 0.0
            results.append(PreDimResult(
                col_id=col.id,
                ned_kn=round(ned_final, 1),
                a_trib_m2=round(a_trib, 2),
                width_cm=w,
                depth_cm=d,
                shape=shape,
                nrd_kn=round(nrd, 1),
                utilization=round(util, 3),
            ))

        return results
