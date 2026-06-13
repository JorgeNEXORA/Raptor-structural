from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

_MODEL_VERSION = "2026.06.13"  # forces pycache invalidation on cloud

class BeamType(str, Enum):
    FRAME = "frame"

class SlabType(str, Enum):
    ONE_WAY   = "one_way"
    TWO_WAY   = "two_way"
    RIBBED    = "ribbed"       # laje aligeirada (vigotas pré-esforçadas)
    CANTILEVER = "cantilever"  # consola / balanço

class FootingType(str, Enum):
    CONCENTRIC = "concentric"
    ECCENTRIC = "eccentric"

@dataclass
class Alert:
    level: str
    message: str

@dataclass
class ColumnLoad:
    source_id: str
    gk_kn: float
    qk_kn: float

@dataclass
class LineLoad:
    source_id: str
    gk_kn_m: float
    qk_kn_m: float

@dataclass
class SlabResult:
    sd_uls_kn_m2: float
    sd_sls_rare_kn_m2: float
    sd_sls_freq_kn_m2: float
    sd_sls_qp_kn_m2: float
    msd_knm_m: float
    vsd_kn_m: float
    reaction_gk_kn_m: float
    reaction_qk_kn_m: float
    reaction_uls_kn_m: float
    deflection_inst_mm: float = 0.0
    deflection_final_mm: float = 0.0
    deflection_limit_mm: float = 0.0
    deflection_utilization: float = 0.0
    crack_width_mm: float = 0.0
    crack_limit_mm: float = 0.3
    crack_utilization: float = 0.0

@dataclass
class BeamResult:
    sd_uls_kn_m: float
    sd_sls_rare_kn_m: float
    sd_sls_freq_kn_m: float
    sd_sls_qp_kn_m: float
    msd_knm: float
    vsd_kn: float
    reaction_left_kn: float
    reaction_right_kn: float
    required_as_cm2: float
    vrd_kn: float = 0.0
    bending_utilization: float = 0.0
    shear_utilization: float = 0.0
    deflection_inst_mm: float = 0.0
    deflection_final_mm: float = 0.0
    deflection_limit_mm: float = 0.0
    deflection_utilization: float = 0.0
    crack_width_mm: float = 0.0
    crack_limit_mm: float = 0.3
    crack_utilization: float = 0.0
    # EC2 rigorous fields
    mrd_knm: float = 0.0
    vrd_c_kn: float = 0.0
    as_min_cm2: float = 0.0

@dataclass
class ColumnResult:
    nsd_kn: float
    nrd_kn: float
    required_as_cm2: float
    adopted_as_cm2: float
    slenderness: float
    utilization: float = 0.0
    # EC2 §5.8.3 buckling
    lambda_lim: float = 0.0
    buckling_ok: bool = True
    # EC2 §6.1(4) minimum eccentricity
    mrd_knm: float = 0.0
    med_min_knm: float = 0.0
    bending_utilization: float = 0.0

@dataclass
class FootingResult:
    nsd_kn: float
    soil_stress_mpa: float
    required_area_m2: float
    punching_vsd_kn: float
    punching_vrd_kn: float
    required_as_cm2: float
    adopted_as_cm2: float
    soil_utilization: float = 0.0
    punching_utilization: float = 0.0
    sigma_min_mpa: float = 0.0
    sigma_max_mpa: float = 0.0
    uplift_detected: bool = False
    needs_balance_beam: bool = False
    # EC2 bending design
    med_knm_m: float = 0.0
    mrd_knm_m: float = 0.0
    bending_utilization: float = 0.0

@dataclass
class SlabPanel:
    id: str
    span_m: float
    thickness_cm: float
    effective_depth_cm: float
    slab_type: SlabType
    gk_kn_m2: float
    qk_kn_m2: float
    support_beam_ids: List[str] = field(default_factory=list)
    support_beam_contributions: dict = field(default_factory=dict)
    direction: Optional[str] = None
    polygon_points: List[tuple] = field(default_factory=list)
    area_m2: Optional[float] = None
    catalog_id: Optional[str] = None   # Presdouro catalog reference, e.g. "P3-BL40x20-25"
    result: Optional[SlabResult] = None

@dataclass
class Beam:
    id: str
    start_node: str
    end_node: str
    width_cm: float
    height_cm: float
    effective_depth_cm: float
    span_m: float
    beam_type: BeamType
    line_loads: List[LineLoad] = field(default_factory=list)
    supported_slab_ids: List[str] = field(default_factory=list)
    result: Optional[BeamResult] = None
    continuous_result: Optional[dict] = None
    reinforcement_result: Optional[dict] = None
    def add_line_load(self, load: LineLoad) -> None:
        self.line_loads.append(load)
    def total_gk(self) -> float:
        return sum(l.gk_kn_m for l in self.line_loads)
    def total_qk(self) -> float:
        return sum(l.qk_kn_m for l in self.line_loads)

@dataclass
class Column:
    id: str
    x: float
    y: float
    width_cm: float        # rectangular: width;  circular: diameter
    depth_cm: float        # rectangular: depth;  circular: diameter (same as width_cm)
    height_m: float
    shape: str = "rectangular"   # "rectangular" or "circular"
    loads: List[ColumnLoad] = field(default_factory=list)
    result: Optional[ColumnResult] = None

    def add_load(self, load: ColumnLoad) -> None:
        self.loads.append(load)
    def total_gk(self) -> float:
        return sum(l.gk_kn for l in self.loads)
    def total_qk(self) -> float:
        return sum(l.qk_kn for l in self.loads)
    def area_cm2(self) -> float:
        import math
        if self.shape == "circular":
            return math.pi * self.width_cm ** 2 / 4.0   # width_cm = diameter
        return self.width_cm * self.depth_cm
    def radius_of_gyration_cm(self) -> float:
        """Minimum radius of gyration for slenderness (EC2 §5.8.3)."""
        import math
        if self.shape == "circular":
            return self.width_cm / 4.0                   # i = D/4
        h_min = min(self.width_cm, self.depth_cm)
        return h_min / math.sqrt(12.0)                   # i = h/√12
    def label(self) -> str:
        if self.shape == "circular":
            return f"Ø{int(self.width_cm)} cm"
        return f"{int(self.width_cm)}×{int(self.depth_cm)} cm"

@dataclass
class FoundationTieBeam:
    id: str
    start_footing_id: str
    end_footing_id: str
    width_cm: float
    height_cm: float
    span_m: float
    recommendation: str
    tie_force_kn: float = 0.0
    required_as_cm2: float = 0.0
    adopted_bars: str = "-"

@dataclass
class Footing:
    id: str
    related_column_id: str
    footing_type: FootingType
    width_a_cm: float
    width_b_cm: float
    height_cm: float
    effective_depth_cm: float
    eccentricity_x_cm: float = 0.0
    eccentricity_y_cm: float = 0.0
    result: Optional[FootingResult] = None
    reinforcement_result: Optional[dict] = None
    def area_m2(self) -> float:
        return (self.width_a_cm / 100.0) * (self.width_b_cm / 100.0)

@dataclass
class ShearWallResult:
    ned_kn: float
    nrd_kn: float
    ved_kn: float
    vrd_kn: float
    med_knm: float
    mrd_knm: float
    sigma_v_mpa: float
    axial_utilization: float = 0.0
    shear_utilization: float = 0.0
    bending_utilization: float = 0.0
    slenderness: float = 0.0
    lambda_lim: float = 0.0
    buckling_ok: bool = True
    required_as_v_cm2: float = 0.0
    required_as_h_cm2_m: float = 0.0


@dataclass
class ShearWall:
    id: str
    x: float
    y: float
    length_m: float
    thickness_cm: float
    height_m: float
    ned_kn: float = 0.0
    ved_kn: float = 0.0
    med_knm: float = 0.0
    result: Optional[ShearWallResult] = None

    def area_m2(self) -> float:
        return self.length_m * (self.thickness_cm / 100.0)


@dataclass
class FlatSlabResult:
    sd_uls_kn_m2: float
    med_column_strip_knm_m: float
    med_middle_strip_knm_m: float
    mrd_column_strip_knm_m: float
    mrd_middle_strip_knm_m: float
    bending_utilization: float = 0.0
    punching_ved_kn: float = 0.0
    punching_vrd_kn: float = 0.0
    punching_utilization: float = 0.0
    deflection_inst_mm: float = 0.0
    deflection_final_mm: float = 0.0
    deflection_limit_mm: float = 0.0
    deflection_utilization: float = 0.0
    required_as_col_cm2_m: float = 0.0
    required_as_mid_cm2_m: float = 0.0


@dataclass
class FlatSlab:
    id: str
    lx_m: float
    ly_m: float
    thickness_cm: float
    effective_depth_cm: float
    gk_kn_m2: float
    qk_kn_m2: float
    col_width_cm: float = 30.0
    panel_type: str = "interior"
    result: Optional[FlatSlabResult] = None


@dataclass
class StairSlabResult:
    span_h_m: float
    sd_uls_kn_m2: float
    msd_knm_m: float
    vsd_kn_m: float
    mrd_knm_m: float
    vrd_c_kn_m: float
    required_as_cm2_m: float
    deflection_final_mm: float = 0.0
    deflection_limit_mm: float = 0.0
    deflection_utilization: float = 0.0
    bending_utilization: float = 0.0
    shear_utilization: float = 0.0
    inclination_deg: float = 0.0


@dataclass
class StairSlab:
    id: str
    span_h_m: float
    rise_m: float
    width_m: float
    thickness_cm: float
    effective_depth_cm: float
    gk_kn_m2: float
    qk_kn_m2: float
    result: Optional[StairSlabResult] = None


@dataclass
class Project:
    name: str
    location: str
    soil_allowable_mpa: float
    columns: List[Column] = field(default_factory=list)
    beams: List[Beam] = field(default_factory=list)
    slabs: List[SlabPanel] = field(default_factory=list)
    footings: List[Footing] = field(default_factory=list)
    tie_beams: List[FoundationTieBeam] = field(default_factory=list)
    walls: List[ShearWall] = field(default_factory=list)
    flat_slabs: List[FlatSlab] = field(default_factory=list)
    stairs: List[StairSlab] = field(default_factory=list)
    alerts: List[Alert] = field(default_factory=list)
    advice_messages: List[str] = field(default_factory=list)
    project_scores: dict = field(default_factory=dict)
    history_snapshots: List[dict] = field(default_factory=list)
    # EC2 material properties
    fck_mpa: float = 25.0   # concrete characteristic compressive strength (C25/30)
    fyk_mpa: float = 500.0  # steel characteristic yield strength (A500NR)
    # Default floor/roof loads (used when slabs are auto-generated)
    gk_floor_kn_m2: float = 6.15
    qk_floor_kn_m2: float = 2.0
    gk_roof_kn_m2: float  = 5.5
    qk_roof_kn_m2: float  = 1.0
    # Project metadata
    owner: str = ""           # Dono de obra / Requerente
    building_type: str = ""   # Tipo de edifício (Habitação, Comércio, etc.)
    designer: str = ""        # Projectista
    def add_alert(self, level: str, message: str) -> None:
        self.alerts.append(Alert(level=level, message=message))
    def add_advice(self, message: str) -> None:
        self.advice_messages.append(message)
