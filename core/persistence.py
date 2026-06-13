"""
Raptor — Project persistence
Save/load Project objects as .raptor (JSON) files.
"""
import dataclasses
import json
from typing import Any

from core.model import (
    Alert, Beam, BeamResult, BeamType, Column, ColumnLoad, ColumnResult,
    ContinuousFooting, ContinuousFootingResult,
    Footing, FootingResult, FootingType, FoundationTieBeam, LineLoad,
    Project, RetainingWall, RetainingWallResult, SlabPanel, SlabResult, SlabType,
    ShearWall, ShearWallResult, FlatSlab, StairSlab,
)

FILE_VERSION = "1.1"


# ── Serialisation ─────────────────────────────────────────────────────────────

class _Enc(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        if isinstance(obj, (BeamType, SlabType, FootingType)):
            return obj.value
        return super().default(obj)


def save_project(project: Project) -> bytes:
    """Serialise Project to UTF-8 JSON bytes (.raptor file)."""
    payload = {
        "raptor_version": FILE_VERSION,
        "project": dataclasses.asdict(project),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, cls=_Enc).encode("utf-8")


# ── Deserialisation helpers ───────────────────────────────────────────────────

def _opt(d: dict | None, cls, *args):
    """Reconstruct optional dataclass from dict, or return None."""
    if d is None:
        return None
    try:
        return cls(**{k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(cls)}})
    except Exception:
        return None


def _slab_type(v: str) -> SlabType:
    try:
        return SlabType(v)
    except Exception:
        return SlabType.ONE_WAY


def _beam_type(v: str) -> BeamType:
    try:
        return BeamType(v)
    except Exception:
        return BeamType.FRAME


def _footing_type(v: str) -> FootingType:
    try:
        return FootingType(v)
    except Exception:
        return FootingType.CONCENTRIC


def _col_from_dict(d: dict) -> Column:
    col = Column(
        id=d["id"], x=d["x"], y=d["y"],
        width_cm=d["width_cm"], depth_cm=d["depth_cm"],
        height_m=d["height_m"],
        shape=d.get("shape", "rectangular"),
    )
    col.loads   = [ColumnLoad(**l) for l in d.get("loads", [])]
    col.result  = _opt(d.get("result"), ColumnResult)
    return col


def _beam_from_dict(d: dict) -> Beam:
    b = Beam(
        id=d["id"],
        start_node=d["start_node"], end_node=d["end_node"],
        width_cm=d["width_cm"], height_cm=d["height_cm"],
        effective_depth_cm=d["effective_depth_cm"],
        span_m=d["span_m"],
        beam_type=_beam_type(d.get("beam_type", "frame")),
    )
    b.line_loads           = [LineLoad(**l) for l in d.get("line_loads", [])]
    b.supported_slab_ids   = d.get("supported_slab_ids", [])
    b.result               = _opt(d.get("result"), BeamResult)
    b.reinforcement_result = d.get("reinforcement_result")
    return b


def _slab_from_dict(d: dict) -> SlabPanel:
    pts = d.get("polygon_points") or []
    pts = [tuple(p) for p in pts]
    s = SlabPanel(
        id=d["id"],
        span_m=d["span_m"],
        thickness_cm=d["thickness_cm"],
        effective_depth_cm=d["effective_depth_cm"],
        slab_type=_slab_type(d.get("slab_type", "one_way")),
        gk_kn_m2=d["gk_kn_m2"],
        qk_kn_m2=d["qk_kn_m2"],
        direction=d.get("direction"),
        polygon_points=pts,
        area_m2=d.get("area_m2"),
        catalog_id=d.get("catalog_id"),
    )
    s.support_beam_ids          = d.get("support_beam_ids", [])
    s.support_beam_contributions = d.get("support_beam_contributions", {})
    s.result                    = _opt(d.get("result"), SlabResult)
    return s


def _footing_from_dict(d: dict) -> Footing:
    f = Footing(
        id=d["id"],
        related_column_id=d["related_column_id"],
        footing_type=_footing_type(d.get("footing_type", "concentric")),
        width_a_cm=d["width_a_cm"], width_b_cm=d["width_b_cm"],
        height_cm=d["height_cm"],
        effective_depth_cm=d["effective_depth_cm"],
        eccentricity_x_cm=d.get("eccentricity_x_cm", 0.0),
        eccentricity_y_cm=d.get("eccentricity_y_cm", 0.0),
    )
    f.result               = _opt(d.get("result"), FootingResult)
    f.reinforcement_result = d.get("reinforcement_result")
    return f


def _tie_beam_from_dict(d: dict) -> FoundationTieBeam:
    return FoundationTieBeam(
        id=d["id"],
        start_footing_id=d["start_footing_id"],
        end_footing_id=d["end_footing_id"],
        width_cm=d["width_cm"], height_cm=d["height_cm"],
        span_m=d["span_m"],
        recommendation=d.get("recommendation", ""),
        tie_force_kn=d.get("tie_force_kn", 0.0),
        required_as_cm2=d.get("required_as_cm2", 0.0),
        adopted_bars=d.get("adopted_bars", "-"),
    )


def _rw_from_dict(d: dict) -> RetainingWall:
    rw = RetainingWall(
        id=d["id"], height_m=d["height_m"],
        stem_thickness_cm=d["stem_thickness_cm"],
        base_width_m=d["base_width_m"],
        base_thickness_cm=d["base_thickness_cm"],
        heel_m=d["heel_m"], toe_m=d["toe_m"],
        gamma_soil_kn_m3=d.get("gamma_soil_kn_m3", 18.0),
        phi_deg=d.get("phi_deg", 30.0),
        surcharge_kn_m2=d.get("surcharge_kn_m2", 5.0),
        x=d.get("x", 0.0), y=d.get("y", 0.0),
    )
    if d.get("result"):
        try:
            rw.result = RetainingWallResult(**{k: v for k, v in d["result"].items()
                                               if k in {f.name for f in dataclasses.fields(RetainingWallResult)}})
        except Exception:
            pass
    return rw


def _cf_from_dict(d: dict) -> ContinuousFooting:
    cf = ContinuousFooting(
        id=d["id"], related_wall_id=d["related_wall_id"],
        width_cm=d["width_cm"], height_cm=d["height_cm"],
        length_m=d["length_m"],
        load_gk_kn_m=d.get("load_gk_kn_m", 0.0),
        load_qk_kn_m=d.get("load_qk_kn_m", 0.0),
        effective_depth_cm=d.get("effective_depth_cm", 0.0),
    )
    if d.get("result"):
        try:
            cf.result = ContinuousFootingResult(**{k: v for k, v in d["result"].items()
                                                   if k in {f.name for f in dataclasses.fields(ContinuousFootingResult)}})
        except Exception:
            pass
    return cf


def load_project(data: bytes) -> Project:
    """Deserialise .raptor bytes back to a Project object."""
    raw = json.loads(data.decode("utf-8"))
    pd  = raw.get("project", raw)   # support both wrapped and bare formats

    p = Project(
        name=pd.get("name", "Projeto"),
        location=pd.get("location", ""),
        soil_allowable_mpa=pd.get("soil_allowable_mpa", 0.2),
        fck_mpa=pd.get("fck_mpa", 25.0),
        fyk_mpa=pd.get("fyk_mpa", 500.0),
        gk_floor_kn_m2=pd.get("gk_floor_kn_m2", 6.15),
        qk_floor_kn_m2=pd.get("qk_floor_kn_m2", 2.0),
        gk_roof_kn_m2=pd.get("gk_roof_kn_m2", 5.5),
        qk_roof_kn_m2=pd.get("qk_roof_kn_m2", 1.0),
        owner=pd.get("owner", ""),
        building_type=pd.get("building_type", ""),
        designer=pd.get("designer", ""),
        retaining_walls=[],
        continuous_footings=[],
    )

    p.columns   = [_col_from_dict(d)      for d in pd.get("columns",   [])]
    p.beams     = [_beam_from_dict(d)     for d in pd.get("beams",     [])]
    p.slabs     = [_slab_from_dict(d)     for d in pd.get("slabs",     [])]
    p.footings  = [_footing_from_dict(d)  for d in pd.get("footings",  [])]
    p.tie_beams = [_tie_beam_from_dict(d) for d in pd.get("tie_beams", [])]
    p.retaining_walls     = [_rw_from_dict(d)  for d in pd.get("retaining_walls", [])]
    p.continuous_footings = [_cf_from_dict(d)  for d in pd.get("continuous_footings", [])]
    p.alerts    = [Alert(**a)             for a in pd.get("alerts",     [])]
    p.advice_messages   = pd.get("advice_messages", [])
    p.project_scores    = pd.get("project_scores", {})

    return p
