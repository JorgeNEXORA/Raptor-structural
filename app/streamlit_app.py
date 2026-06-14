import streamlit as st
import sys
import os
import io
import tempfile
import traceback
import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.model import BeamType, Column, ContinuousFooting, FlatSlab, Project, RetainingWall, ShearWall, SlabPanel, SlabType, StairSlab
from analysis.predim import ColumnPreDimensioner
from config.loads import (
    LoadConfigurator, LAJE, ISOLAMENTO, ACABAMENTO_PISO, ACABAMENTO_COB,
    IMPERMEABILIZACAO, BETONILHA_PENDENTE, EQUIPAMENTOS_COB, USE_CATEGORY,
)
try:
    from config.slab_catalog import CATALOG, catalog_names, select_slab
    _CATALOG_OK = bool(CATALOG)
except Exception:
    CATALOG = {}
    _CATALOG_OK = False
    def catalog_names(): return []
    def select_slab(*a, **k): return None
from pipeline.auto_pipeline import AutoPipeline
from analysis.visualization import PlanVisualizer
from analysis.importers import (
    CSVGeometryImporter,
    CSVBeamImporter,
    CSVSlabImporter,
    CSVSlabLoadImporter,
)
from analysis.dxf_export import DXFExporter
from analysis.dxf_import import SimpleDXFImporter
from analysis.report_export import ReportExporter
from analysis.advisor import ProjectAdvisor
from analysis.optimizer import AutoOptimizer
from analysis.history import store_snapshot

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Raptor",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Session state init ───────────────────────────────────────────────────────
for _key, _val in [
    ("project", None),
    ("png_bytes", None),
    ("dxf_bytes", None),
    ("docx_bytes", None),
    ("manual_walls", []),
    ("manual_flat_slabs", []),
    ("manual_stairs", []),
    ("manual_retaining_walls", []),
    ("manual_slabs", []),
    ("portico_slab_map", {}),
    ("portico_tramos", []),
    ("wall_slab_map", {}),
    ("beam_overrides", {}),
    ("col_config", None),
    ("cols_in_cont_footing", []),
    ("load_cfg", None),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _val


# ─── Helpers ──────────────────────────────────────────────────────────────────
def save_upload(uploaded) -> str | None:
    if uploaded is None:
        return None
    suffix = os.path.splitext(uploaded.name)[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded.read())
    tmp.flush()
    tmp.close()
    return tmp.name


def build_demo_columns():
    return [
        Column("P1", 0.0, 0.0, 25, 25, 3.0),
        Column("P2", 4.0, 0.0, 25, 25, 3.0),
        Column("P3", 8.0, 0.0, 25, 25, 3.0),
        Column("P4", 0.0, 4.5, 25, 25, 3.0),
        Column("P5", 4.0, 4.5, 25, 25, 3.0),
        Column("P6", 8.0, 4.5, 25, 25, 3.0),
    ]


def _util_color(val):
    try:
        v = float(val)
        if v >= 1.0:
            return "background-color: #c0392b; color: white"
        if v >= 0.80:
            return "background-color: #e67e22; color: white"
        return "background-color: #27ae60; color: white"
    except Exception:
        return ""


def style_df(df: pd.DataFrame, util_cols: list):
    cols_present = [c for c in util_cols if c in df.columns]
    if not cols_present:
        return df.style
    return df.style.map(_util_color, subset=cols_present)


def reset_project_results(p: Project) -> None:
    for c in p.columns:
        c.loads = []
        c.result = None
    for b in p.beams:
        b.line_loads = []
        b.supported_slab_ids = []
        b.result = None
        b.continuous_result = None
        b.reinforcement_result = None
    for s in p.slabs:
        s.support_beam_ids = []
        s.support_beam_contributions = {}
        s.result = None
    for f in p.footings:
        f.result = None
        f.reinforcement_result = None
    for w in p.walls:
        w.result = None
    for fs in p.flat_slabs:
        fs.result = None
    for ss in p.stairs:
        ss.result = None
    p.tie_beams = []
    p.alerts = []
    p.advice_messages = []


def run_outputs(project: Project):
    with tempfile.TemporaryDirectory() as tmp:
        png_path = os.path.join(tmp, "planta.png")
        dxf_path = os.path.join(tmp, "planta.dxf")
        PlanVisualizer().draw_project_plan(project, png_path)
        DXFExporter().export_project(project, dxf_path)
        with open(png_path, "rb") as f:
            st.session_state.png_bytes = f.read()
        with open(dxf_path, "rb") as f:
            st.session_state.dxf_bytes = f.read()
    st.session_state.docx_bytes = None  # reset on new run


def _rebuild_psmap(pt_list: list, ss) -> None:
    """Reconstrói portico_slab_map a partir de portico_tramos."""
    _m: dict = {}
    for _t in pt_list:
        _pid = _t["portico_id"]
        _m.setdefault(_pid, [])
        for _sid in [_t.get("laje_esq_piso"), _t.get("laje_dir_piso"),
                     _t.get("laje_esq_cob"), _t.get("laje_dir_cob")]:
            if _sid and _sid not in _m[_pid]:
                _m[_pid].append(_sid)
    ss.portico_slab_map = _m


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏗️ Raptor")
    st.caption("Análise estrutural EC2 — MVP")
    st.divider()

    # ── Guardar / Abrir projecto ──────────────────────────────────────────────
    from core.persistence import save_inputs as _save_inp, load_inputs as _load_inp
    _proj_now = st.session_state.get("project")

    # Guardar inputs (sempre visível — não precisa de cálculo)
    _inp_keys = ["manual_slabs", "manual_retaining_walls", "manual_flat_slabs",
                 "manual_stairs", "col_config", "cols_in_cont_footing",
                 "portico_slab_map", "portico_tramos", "beam_overrides"]
    _inp_snap = {k: st.session_state.get(k) for k in _inp_keys}
    _inp_bytes = _save_inp(_inp_snap)
    st.download_button(
        "💾  Guardar inputs",
        data=_inp_bytes,
        file_name="inputs.raptor",
        mime="application/json",
        use_container_width=True,
        help="Guarda lajes, muros, pilares e pórticos introduzidos, mesmo sem correr o cálculo.",
    )

    # Guardar projeto completo (com resultados) — só depois de calcular
    if _proj_now:
        st.success(f"**{_proj_now.name}**", icon="📂")
        from core.persistence import save_project as _save_proj
        _ss_to_save = {
            "col_config":           st.session_state.get("col_config"),
            "cols_in_cont_footing": st.session_state.get("cols_in_cont_footing", []),
            "portico_slab_map":     st.session_state.get("portico_slab_map", {}),
            "portico_tramos":       st.session_state.get("portico_tramos", []),
            "wall_slab_map":        st.session_state.get("wall_slab_map", {}),
            "beam_overrides":       st.session_state.get("beam_overrides", {}),
        }
        _proj_bytes = _save_proj(_proj_now, session_state=_ss_to_save)
        _safe_name  = _proj_now.name.replace(" ", "_").replace("/", "-")
        st.download_button(
            "💾  Guardar projeto + resultados (.raptor)",
            data=_proj_bytes,
            file_name=f"{_safe_name}.raptor",
            mime="application/json",
            use_container_width=True,
            help="Guarda geometria, resultados e armaduras calculadas.",
        )

    with st.expander("📂 Abrir projeto / inputs guardado"):
        st.caption("Carrega um ficheiro .raptor (inputs ou projeto completo).")
        raptor_upload = st.file_uploader("Ficheiro .raptor", type=["raptor", "json"],
                                         key="raptor_upload", label_visibility="collapsed")
        if raptor_upload is not None:
            # Guard: só processa quando é um ficheiro novo (evita loop infinito de reruns)
            _up_uid = f"{raptor_upload.name}_{raptor_upload.size}"
            if st.session_state.get("_raptor_loaded_id") != _up_uid:
                try:
                    _raw_bytes = raptor_upload.read()
                    _raw_json  = __import__("json").loads(_raw_bytes.decode("utf-8"))
                    if _raw_json.get("raptor_version", "").startswith("inputs_"):
                        # Inputs snapshot
                        _inp_loaded = _load_inp(_raw_bytes)
                        for _ik, _iv in _inp_loaded.items():
                            st.session_state[_ik] = _iv
                        st.session_state["_raptor_loaded_id"] = _up_uid
                        st.success("Inputs restaurados com sucesso.")
                        st.rerun()
                    else:
                        # Full project
                        from core.persistence import load_project as _load_proj
                        _loaded = _load_proj(_raw_bytes)
                        st.session_state.project = _loaded
                        st.session_state.drawings_ready = False
                        # Restaurar session state manuais
                        st.session_state.manual_retaining_walls = list(_loaded.retaining_walls or [])
                        st.session_state.manual_slabs = [s for s in (_loaded.slabs or [])
                                                         if not getattr(s, 'polygon_points', None)]
                        st.session_state.manual_flat_slabs = list(getattr(_loaded, 'flat_slabs', []) or [])
                        st.session_state.manual_stairs    = list(getattr(_loaded, 'stairs', []) or [])
                        st.session_state.manual_walls     = list(getattr(_loaded, 'walls', []) or [])
                        # Restaurar session_state guardado (col_config, pórticos)
                        _ss_saved = _raw_json.get("session_state", {})
                        if _ss_saved.get("col_config"):
                            st.session_state.col_config = _ss_saved["col_config"]
                        if _ss_saved.get("cols_in_cont_footing"):
                            st.session_state.cols_in_cont_footing = _ss_saved["cols_in_cont_footing"]
                        if _ss_saved.get("portico_slab_map"):
                            st.session_state.portico_slab_map = _ss_saved["portico_slab_map"]
                        else:
                            st.session_state.portico_slab_map = {}
                        if _ss_saved.get("portico_tramos"):
                            st.session_state.portico_tramos = _ss_saved["portico_tramos"]
                        else:
                            st.session_state.portico_tramos = []
                        st.session_state.wall_slab_map   = _ss_saved.get("wall_slab_map", {})
                        st.session_state.beam_overrides  = _ss_saved.get("beam_overrides", {})
                        st.session_state["_raptor_loaded_id"] = _up_uid
                        _n_rw = len(st.session_state.manual_retaining_walls)
                        _n_sl = len(st.session_state.manual_slabs)
                        st.success(f"Projeto '{_loaded.name}' carregado — {_n_rw} muros, {_n_sl} lajes.")
                        st.rerun()
                except Exception as _le:
                    st.error(f"Erro ao abrir ficheiro: {_le}")
            else:
                _proj_loaded = st.session_state.get("project")
                if _proj_loaded:
                    _n_rw = len(st.session_state.get("manual_retaining_walls", []))
                    _n_sl = len(st.session_state.get("manual_slabs", []))
                    st.success(f"'{_proj_loaded.name}' — {_n_rw} muros, {_n_sl} lajes")
    st.divider()

    mode = st.radio("Modo de entrada", ["CSV", "DXF"], horizontal=True)

    dxf_upload = col_csv = beam_csv = slab_csv = slab_loads_csv = None
    if mode == "DXF":
        dxf_upload = st.file_uploader("Ficheiro DXF", type=["dxf"])
        slab_loads_csv = st.file_uploader("CSV Cargas Lajes (opcional)", type=["csv"])
    else:
        col_csv = st.file_uploader("CSV Pilares", type=["csv"])
        beam_csv = st.file_uploader("CSV Vigas", type=["csv"])
        slab_csv = st.file_uploader("CSV Lajes", type=["csv"])
        slab_loads_csv = st.file_uploader("CSV Cargas Lajes", type=["csv"])

    st.divider()
    project_name = st.text_input("Nome do projeto", "Projeto Estrutural")
    location = st.text_input("Local", "Barcelos")
    owner = st.text_input("Requerente / Dono de Obra", value="", key="owner")
    building_type = st.selectbox("Tipo de Edifício",
        ["Habitação", "Comércio", "Serviços", "Industrial", "Equipamento", "Outro"],
        key="building_type")
    designer = st.text_input("Projectista", value="", key="designer")
    soil_mpa = st.number_input(
        "Tensão admissível solo (MPa)",
        value=0.20, min_value=0.05, max_value=2.0, step=0.05, format="%.2f",
    )
    _fck_options = {"C16/20": 16, "C20/25": 20, "C25/30": 25,
                    "C30/37": 30, "C35/45": 35, "C40/50": 40}
    _fyk_options = {"A400NR": 400, "A500NR": 500, "A600NR": 600}
    fck_label = st.selectbox("Betão", list(_fck_options.keys()), index=2)
    fyk_label = st.selectbox("Aço", list(_fyk_options.keys()), index=1)
    fck_mpa = _fck_options[fck_label]
    fyk_mpa = _fyk_options[fyk_label]

    st.divider()
    st.markdown("**Elementos avançados**")

    # ── Shear walls ──────────────────────────────────────────────────────────
    with st.expander(f"🧱 Paredes estruturais ({len(st.session_state.manual_walls)})"):
        _pw = st.session_state.get("_prefill_wall", {})
        with st.form("form_wall", clear_on_submit=True):
            wc1, wc2 = st.columns(2)
            w_id  = wc1.text_input("ID", value=_pw.get("id", "W1"))
            w_len = wc1.number_input("Comprimento (m)", value=float(_pw.get("length_m", 3.0)), min_value=0.5, step=0.5)
            w_thk = wc1.number_input("Espessura (cm)", value=int(_pw.get("thickness_cm", 20)), min_value=10, step=5)
            w_h   = wc1.number_input("Altura (m)", value=float(_pw.get("height_m", 3.0)), min_value=1.0, step=0.5)
            w_ned = wc2.number_input("NEd (kN)", value=float(_pw.get("ned_kn", 500.0)), min_value=0.0, step=50.0)
            w_ved = wc2.number_input("VEd horizontal (kN)", value=float(_pw.get("ved_kn", 50.0)), min_value=0.0, step=10.0)
            w_med = wc2.number_input("MEd base (kNm)", value=float(_pw.get("med_knm", 150.0)), min_value=0.0, step=10.0)
            _w_lbl = "✅ Atualizar parede" if _pw else "➕ Adicionar parede"
            if st.form_submit_button(_w_lbl):
                st.session_state.manual_walls.append(
                    ShearWall(w_id, 0.0, 0.0, w_len, w_thk, w_h, w_ned, w_ved, w_med))
                st.session_state.pop("_prefill_wall", None)
                st.rerun()
        if st.session_state.manual_walls:
            for _i, ww in enumerate(st.session_state.manual_walls):
                _ca, _cb, _cc = st.columns([5, 1, 1])
                _ca.caption(f"{ww.id}: L={ww.length_m}m  e={ww.thickness_cm}cm  N={ww.ned_kn}kN")
                if _cb.button("✏️", key=f"edit_wall_{_i}", help="Editar"):
                    st.session_state["_prefill_wall"] = {"id": ww.id, "length_m": ww.length_m,
                        "thickness_cm": ww.thickness_cm, "height_m": ww.height_m,
                        "ned_kn": ww.ned_kn, "ved_kn": ww.ved_kn, "med_knm": ww.med_knm}
                    st.session_state.manual_walls.pop(_i)
                    st.rerun()
                if _cc.button("🗑", key=f"del_wall_{_i}", help="Apagar"):
                    st.session_state.manual_walls.pop(_i)
                    st.rerun()

    # ── Flat slabs ───────────────────────────────────────────────────────────
    with st.expander(f"⚪ Lajes fungiformes ({len(st.session_state.manual_flat_slabs)})"):
        _pfs = st.session_state.get("_prefill_fs", {})
        _fs_panel_opts = ["interior", "edge", "corner"]
        with st.form("form_fs", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            fs_id   = fc1.text_input("ID", value=_pfs.get("id", "LF1"))
            fs_lx   = fc1.number_input("Lx — vão curto (m)", value=float(_pfs.get("lx_m", 5.0)), min_value=1.0, step=0.5)
            fs_ly   = fc1.number_input("Ly — vão longo (m)", value=float(_pfs.get("ly_m", 6.0)), min_value=1.0, step=0.5)
            fs_thk  = fc1.number_input("Espessura (cm)", value=int(_pfs.get("thickness_cm", 22)), min_value=12, step=2)
            fs_gk   = fc2.number_input("gk (kN/m²)", value=float(_pfs.get("gk_kn_m2", 5.0)), min_value=0.0, step=0.5)
            fs_qk   = fc2.number_input("qk (kN/m²)", value=float(_pfs.get("qk_kn_m2", 3.0)), min_value=0.0, step=0.5)
            fs_cw   = fc2.number_input("Lado pilar (cm)", value=int(_pfs.get("col_width_cm", 30)), min_value=15, step=5)
            _fs_pt_idx = _fs_panel_opts.index(_pfs.get("panel_type", "interior")) if _pfs.get("panel_type") in _fs_panel_opts else 0
            fs_type = fc2.selectbox("Tipo painel", _fs_panel_opts, index=_fs_pt_idx)
            _fs_lbl = "✅ Atualizar" if _pfs else "➕ Adicionar laje fungiforme"
            if st.form_submit_button(_fs_lbl):
                d_cm = fs_thk - 3.0
                st.session_state.manual_flat_slabs.append(
                    FlatSlab(fs_id, fs_lx, fs_ly, fs_thk, d_cm, fs_gk, fs_qk, fs_cw, fs_type))
                st.session_state.pop("_prefill_fs", None)
                st.rerun()
        if st.session_state.manual_flat_slabs:
            for _i, fs in enumerate(st.session_state.manual_flat_slabs):
                _ca, _cb, _cc = st.columns([5, 1, 1])
                _ca.caption(f"{fs.id}: {fs.lx_m}×{fs.ly_m}m  h={fs.thickness_cm}cm  gk={fs.gk_kn_m2}")
                if _cb.button("✏️", key=f"edit_fs_{_i}", help="Editar"):
                    st.session_state["_prefill_fs"] = {"id": fs.id, "lx_m": fs.lx_m, "ly_m": fs.ly_m,
                        "thickness_cm": fs.thickness_cm, "gk_kn_m2": fs.gk_kn_m2,
                        "qk_kn_m2": fs.qk_kn_m2, "col_width_cm": fs.col_width_cm, "panel_type": fs.panel_type}
                    st.session_state.manual_flat_slabs.pop(_i)
                    st.rerun()
                if _cc.button("🗑", key=f"del_fs_{_i}", help="Apagar"):
                    st.session_state.manual_flat_slabs.pop(_i)
                    st.rerun()

    # ── Stairs ───────────────────────────────────────────────────────────────
    with st.expander(f"🪜 Escadas ({len(st.session_state.manual_stairs)})"):
        _pst = st.session_state.get("_prefill_stair", {})
        with st.form("form_stair", clear_on_submit=True):
            sc1, sc2 = st.columns(2)
            st_id  = sc1.text_input("ID", value=_pst.get("id", "E1"))
            st_lh  = sc1.number_input("Projecção horiz. (m)", value=float(_pst.get("span_h_m", 3.5)), min_value=0.5, step=0.25)
            st_hv  = sc1.number_input("Altura total (m)", value=float(_pst.get("rise_m", 1.5)), min_value=0.2, step=0.1)
            st_w   = sc1.number_input("Largura (m)", value=float(_pst.get("width_m", 1.2)), min_value=0.5, step=0.1)
            st_thk = sc2.number_input("Espessura laje (cm)", value=int(_pst.get("thickness_cm", 14)), min_value=8, step=1)
            st_gk  = sc2.number_input("gk acabamentos (kN/m²)", value=float(_pst.get("gk_kn_m2", 1.5)), min_value=0.0, step=0.5)
            st_qk  = sc2.number_input("qk (kN/m²)", value=float(_pst.get("qk_kn_m2", 3.0)), min_value=0.0, step=0.5)
            _st_lbl = "✅ Atualizar" if _pst else "➕ Adicionar escada"
            if st.form_submit_button(_st_lbl):
                d_cm = st_thk - 2.0
                st.session_state.manual_stairs.append(
                    StairSlab(st_id, st_lh, st_hv, st_w, st_thk, d_cm, st_gk, st_qk))
                st.session_state.pop("_prefill_stair", None)
                st.rerun()
        if st.session_state.manual_stairs:
            for _i, ss in enumerate(st.session_state.manual_stairs):
                _ca, _cb, _cc = st.columns([5, 1, 1])
                _ca.caption(f"{ss.id}: Lh={ss.span_h_m}m  Hv={ss.rise_m}m  h={ss.thickness_cm}cm")
                if _cb.button("✏️", key=f"edit_stair_{_i}", help="Editar"):
                    st.session_state["_prefill_stair"] = {"id": ss.id, "span_h_m": ss.span_h_m,
                        "rise_m": ss.rise_m, "width_m": ss.width_m, "thickness_cm": ss.thickness_cm,
                        "gk_kn_m2": ss.gk_kn_m2, "qk_kn_m2": ss.qk_kn_m2}
                    st.session_state.manual_stairs.pop(_i)
                    st.rerun()
                if _cc.button("🗑", key=f"del_stair_{_i}", help="Apagar"):
                    st.session_state.manual_stairs.pop(_i)
                    st.rerun()

    # ── Muros de betão de suporte ────────────────────────────────────────────
    with st.expander(f"🧱 Muros de betão ({len(st.session_state.manual_retaining_walls)})"):
        _prw = st.session_state.get("_prefill_rw", {})
        _rw_tipo_opts = ["Suporte de terras", "Piscina"]
        _rw_lado_opts = ["Direito", "Esquerdo"]
        _rw_tipo_idx  = 1 if _prw.get("wall_type") == "piscina" else 0
        _rw_lado_idx  = 1 if _prw.get("load_side", "direito") == "esquerdo" else 0
        with st.form("form_rw", clear_on_submit=True):
            rw1, rw2 = st.columns(2)
            rw_id   = rw1.text_input("ID", value=_prw.get("id", "M1"))
            rw_h    = rw1.number_input("Altura do muro (m)", value=float(_prw.get("height_m", 2.5)),
                                        min_value=0.5, step=0.25, help="Altura do fuste, sem contar com a sapata")
            rw_st   = rw1.number_input("Espessura do fuste (cm)", value=int(_prw.get("stem_thickness_cm", 25)), min_value=15, step=5)
            rw_tipo = rw1.selectbox("Tipo", _rw_tipo_opts, index=_rw_tipo_idx)
            rw_lado = rw2.selectbox("Lado das terras/água", _rw_lado_opts, index=_rw_lado_idx)
            rw_gam  = rw2.number_input("γ solo (kN/m³)", value=float(_prw.get("gamma_soil_kn_m3", 18.0)), min_value=14.0, step=1.0)
            rw_phi  = rw2.number_input("φ (°)", value=int(_prw.get("phi_deg", 30)), min_value=15, max_value=45, step=1)
            rw_q    = rw2.number_input("Sobrecarga (kN/m²)", value=float(_prw.get("surcharge_kn_m2", 5.0)), min_value=0.0, step=1.0)
            _rw_lbl = "✅ Atualizar muro" if _prw else "➕ Adicionar muro"
            if st.form_submit_button(_rw_lbl):
                _rw_H  = rw_h
                _rw_st_m = rw_st / 100.0
                _rw_bw   = round(0.60 * _rw_H, 2)
                _rw_ht   = float(max(25, round(0.10 * _rw_H * 100 / 5) * 5))
                _rw_heel = round(0.40 * _rw_H, 2)
                _rw_toe  = max(0.10, round(_rw_bw - _rw_heel - _rw_st_m, 2))
                st.session_state.manual_retaining_walls.append(
                    RetainingWall(rw_id, _rw_H, rw_st, _rw_bw, _rw_ht, _rw_heel, _rw_toe,
                                  rw_gam, float(rw_phi), rw_q,
                                  "piscina" if rw_tipo == "Piscina" else "terras",
                                  rw_lado.lower()))
                st.session_state.pop("_prefill_rw", None)
                st.rerun()
        if st.session_state.manual_retaining_walls:
            _rw_slab_opts = [s.id for s in st.session_state.manual_slabs]
            _wsmap = st.session_state.get("wall_slab_map", {})
            for _i, rw in enumerate(st.session_state.manual_retaining_walls):
                _rw_tipo_lbl = "piscina" if getattr(rw, 'wall_type', 'terras') == 'piscina' else "terras"
                _ca, _cb, _cc = st.columns([5, 1, 1])
                _ca.caption(f"{rw.id}: H={rw.height_m}m  e={rw.stem_thickness_cm}cm  "
                            f"B={rw.base_width_m:.2f}m  [{_rw_tipo_lbl}]")
                if _cb.button("✏️", key=f"edit_rw_{_i}", help="Editar"):
                    st.session_state["_prefill_rw"] = {"id": rw.id, "height_m": rw.height_m,
                        "stem_thickness_cm": rw.stem_thickness_cm, "gamma_soil_kn_m3": rw.gamma_soil_kn_m3,
                        "phi_deg": rw.phi_deg, "surcharge_kn_m2": rw.surcharge_kn_m2,
                        "wall_type": getattr(rw, "wall_type", "terras"),
                        "load_side": getattr(rw, "load_side", "direito")}
                    st.session_state.manual_retaining_walls.pop(_i)
                    st.rerun()
                if _cc.button("🗑", key=f"del_rw_{_i}", help="Apagar"):
                    st.session_state.manual_retaining_walls.pop(_i)
                    st.rerun()
                # Lajes que apoiam neste muro — separadas por lado
                _ws_entry = _wsmap.get(rw.id, {})
                # Backward compat: se era lista simples, migrar para dict
                if isinstance(_ws_entry, list):
                    _ws_entry = {"direito": _ws_entry, "esquerdo": []}
                _ws_dir_cur = [s for s in _ws_entry.get("direito", []) if s in _rw_slab_opts]
                _ws_esq_cur = [s for s in _ws_entry.get("esquerdo", []) if s in _rw_slab_opts]
                _wsd, _wse  = st.columns(2)
                _ws_dir_sel = _wsd.multiselect(
                    f"Lajes lado dir. → {rw.id}",
                    options=_rw_slab_opts,
                    default=_ws_dir_cur,
                    key=f"wsmap_dir_{rw.id}_{_i}",
                    help="Lajes que apoiam no lado direito do muro",
                )
                _ws_esq_sel = _wse.multiselect(
                    f"Lajes lado esq. → {rw.id}",
                    options=_rw_slab_opts,
                    default=_ws_esq_cur,
                    key=f"wsmap_esq_{rw.id}_{_i}",
                    help="Lajes que apoiam no lado esquerdo do muro",
                )
                _wsmap[rw.id] = {"direito": _ws_dir_sel, "esquerdo": _ws_esq_sel}
            st.session_state.wall_slab_map = _wsmap

    # ── Pilares ──────────────────────────────────────────────────────────────
    _cc_cur = st.session_state.get("col_config") or {}
    _n_def  = _cc_cur.get("n", 6)
    with st.expander(f"🏛️ Pilares P1–P{_n_def} ({_n_def} pilares)"):
        st.caption("Define o número de pilares, pisos e alturas. "
                   "Se não fizeres upload de CSV, o programa usa esta configuração.")
        _pc1, _pc2 = st.columns(2)
        _n_pil = int(_pc1.number_input("Nº de pilares", value=_n_def, min_value=1, max_value=60, step=1, key="cc_n"))
        _n_pis = int(_pc1.number_input("Nº de pisos", value=_cc_cur.get("n_pisos", 2), min_value=1, max_value=15, step=1, key="cc_npisos"))
        _h_cav = float(_pc2.number_input("H sapata→piso 1 (m)", value=float(_cc_cur.get("h_cave", 2.80)), min_value=1.0, step=0.05, key="cc_hcave"))
        _h_pis = float(_pc2.number_input("H entre pisos (m)", value=float(_cc_cur.get("h_piso", 2.80)), min_value=2.0, step=0.05, key="cc_hpiso"))
        _b_col = int(_pc1.number_input("Secção b (cm)", value=_cc_cur.get("b", 30), min_value=20, max_value=120, step=5, key="cc_b"))
        _h_col = int(_pc2.number_input("Secção h (cm)", value=_cc_cur.get("h", 30), min_value=20, max_value=120, step=5, key="cc_h"))

        _all_pil_ids = [f"P{i}" for i in range(1, _n_pil + 1)]
        _cur_cont = [_p for _p in st.session_state.get("cols_in_cont_footing", []) if _p in _all_pil_ids]
        _pil_cont = st.multiselect(
            "Pilares em sapata corrida (muro cave)",
            options=_all_pil_ids,
            default=_cur_cont,
            help="Os restantes ficam em sapata isolada.",
            key="cc_cont_pils",
        )
        _isol_pils = [_p for _p in _all_pil_ids if _p not in _pil_cont]
        if _isol_pils:
            st.caption(f"Isoladas ({len(_isol_pils)}): {', '.join(_isol_pils[:8])}{'…' if len(_isol_pils)>8 else ''}")
        if _pil_cont:
            st.caption(f"Sapata corrida ({len(_pil_cont)}): {', '.join(_pil_cont)}")

        if st.button("✅ Aplicar configuração de pilares", key="btn_apply_col_config"):
            st.session_state["col_config"] = {
                "n": _n_pil, "n_pisos": _n_pis,
                "h_cave": _h_cav, "h_piso": _h_pis,
                "b": _b_col, "h": _h_col,
            }
            st.session_state["cols_in_cont_footing"] = list(_pil_cont)
            st.rerun()

        if _cc_cur:
            _h_tot_info = _cc_cur.get("h_cave", 2.8) + max(0, _cc_cur.get("n_pisos", 2) - 1) * _cc_cur.get("h_piso", 2.8)
            st.info(f"✅ {_cc_cur['n']} pilares | {_cc_cur['n_pisos']} pisos | "
                    f"H≈{_h_tot_info:.2f}m | {_cc_cur['b']}×{_cc_cur['h']}cm")
            if st.button("🗑 Limpar configuração de pilares", key="btn_clear_col_config"):
                st.session_state["col_config"] = None
                st.session_state["cols_in_cont_footing"] = []
                st.rerun()

    # ── Sapatas ───────────────────────────────────────────────────────────────
    with st.expander("⬛ Sapatas — tipo por pilar"):
        st.caption("Aqui podes ver e ajustar quais os pilares com sapata isolada vs sapata corrida do muro da cave. "
                   "Define primeiro os Pilares acima.")
        _cc2 = st.session_state.get("col_config")
        _cont2 = st.session_state.get("cols_in_cont_footing", [])
        if _cc2:
            _all2 = [f"P{i}" for i in range(1, _cc2["n"] + 1)]
            _new_cont2 = st.multiselect(
                "Pilares em sapata corrida do muro cave",
                options=_all2,
                default=[_p for _p in _cont2 if _p in _all2],
                key="sapatas_cont_pils",
            )
            if _new_cont2 != _cont2:
                st.session_state["cols_in_cont_footing"] = list(_new_cont2)
                st.rerun()
            _isol2 = [_p for _p in _all2 if _p not in _new_cont2]
            st.caption(f"**Sapatas isoladas ({len(_isol2)}):** {', '.join(_isol2)}")
            if _new_cont2:
                st.caption(f"**Sapata corrida ({len(_new_cont2)}):** {', '.join(_new_cont2)}")
        else:
            st.info("Define o número de pilares na secção 🏛️ Pilares.")

    # ── Lajes ────────────────────────────────────────────────────────────────
    _pavinorte_sb = [n for n in sorted(CATALOG.keys()) if n.startswith(("V3-","V5-","2V"))] if _CATALOG_OK else []
    _other_sb     = [n for n in sorted(CATALOG.keys()) if not n.startswith(("V3-","V5-","2V"))] if _CATALOG_OK else []
    _cat_sb_opts  = ["(automático)"] + _pavinorte_sb + _other_sb
    _lcfg_sb      = st.session_state.get("load_cfg") or {}
    _zona_map_sb  = {
        "Habitável": (_lcfg_sb.get("gk_piso", 6.15), _lcfg_sb.get("qk_piso", 2.0)),
        "Garagem":   (_lcfg_sb.get("gk_gar",  4.80), _lcfg_sb.get("qk_gar",  2.5)),
        "Varanda":   (_lcfg_sb.get("gk_var",  5.50), _lcfg_sb.get("qk_var",  3.0)),
        "Cobertura": (_lcfg_sb.get("gk_cob",  5.50), _lcfg_sb.get("qk_cob",  1.0)),
    }
    _sl_type_opts = ["Aligeirada", "Maciça 1D", "Maciça 2D", "Consola"]
    _sl_lvl_opts  = ["piso", "cobertura"]
    _sl_dir_opts  = ["X", "Y"]
    _sl_zona_opts = list(_zona_map_sb.keys())
    with st.expander(f"⬜ Lajes ({len(st.session_state.manual_slabs)})"):
        _pslab = st.session_state.get("_prefill_slab", {})
        _sl_type_idx  = _sl_type_opts.index(_pslab["slab_type_lbl"]) if _pslab.get("slab_type_lbl") in _sl_type_opts else 1
        _sl_lvl_idx   = _sl_lvl_opts.index(_pslab["level"]) if _pslab.get("level") in _sl_lvl_opts else 0
        _sl_dir_idx   = _sl_dir_opts.index(_pslab.get("direction", "x").upper()) if _pslab.get("direction", "x").upper() in _sl_dir_opts else 0
        _sl_cat_def   = _pslab.get("catalog_id") or "(automático)"
        _sl_cat_idx   = _cat_sb_opts.index(_sl_cat_def) if _sl_cat_def in _cat_sb_opts else 0
        with st.form("form_add_slab_sb", clear_on_submit=True):
            _sb1, _sb2 = st.columns(2)
            _sl_id_sb   = _sb1.text_input("ID", value=_pslab.get("id", f"LP{len(st.session_state.manual_slabs)+1}"))
            _sl_span_sb = _sb1.number_input("Vão (m)", value=float(_pslab.get("span_m", 4.0)), min_value=0.5, step=0.25)
            _sl_thk_sb  = _sb1.number_input("Esp. (cm)", value=int(_pslab.get("thickness_cm", 25)), min_value=8, max_value=50, step=1)
            _sl_d_sb    = _sb1.number_input("d útil (cm)", value=int(_pslab.get("effective_depth_cm", 20)), min_value=5, max_value=45, step=1)
            _sl_type_sb = _sb2.selectbox("Tipo", _sl_type_opts, index=_sl_type_idx)
            _sl_lvl_sb  = _sb2.selectbox("Nível", _sl_lvl_opts, index=_sl_lvl_idx)
            _sl_dir_sb  = _sb2.selectbox("Direção", _sl_dir_opts, index=_sl_dir_idx)
            _sl_zona_sb = _sb2.selectbox("Zona", _sl_zona_opts)
            _sl_cat_sb  = st.selectbox("Catálogo", _cat_sb_opts, index=_sl_cat_idx)
            _slab_lbl = "✅ Atualizar laje" if _pslab else "➕ Adicionar laje"
            if st.form_submit_button(_slab_lbl):
                _type_map_sb = {"Aligeirada": "ribbed", "Maciça 1D": "one_way",
                                "Maciça 2D": "two_way", "Consola": "cantilever"}
                _gk_sb, _qk_sb = _zona_map_sb[_sl_zona_sb]
                _ns = SlabPanel(
                    id=_sl_id_sb.strip() or f"LP{len(st.session_state.manual_slabs)+1}",
                    span_m=float(_sl_span_sb),
                    thickness_cm=float(_sl_thk_sb),
                    effective_depth_cm=float(_sl_d_sb),
                    slab_type=SlabType(_type_map_sb[_sl_type_sb]),
                    gk_kn_m2=_gk_sb,
                    qk_kn_m2=_qk_sb,
                    direction=_sl_dir_sb.lower(),
                )
                _ns.level = _sl_lvl_sb
                _ns.catalog_id = None if _sl_cat_sb == "(automático)" else _sl_cat_sb
                _ns.support_beam_ids = []
                st.session_state.manual_slabs.append(_ns)
                st.session_state.pop("_prefill_slab", None)
                st.rerun()
        if st.session_state.manual_slabs:
            _type_reverse_sb = {"ribbed": "Aligeirada", "one_way": "Maciça 1D",
                                "two_way": "Maciça 2D", "cantilever": "Consola"}
            for _i, _ms in enumerate(st.session_state.manual_slabs):
                _ca, _cb, _cc = st.columns([5, 1, 1])
                _ms_tp = _ms.slab_type.value if hasattr(_ms.slab_type, "value") else str(_ms.slab_type)
                _ca.caption(f"**{_ms.id}** {getattr(_ms,'level','piso')} | {_ms.span_m}m "
                            f"h={int(_ms.thickness_cm)}cm [{_type_reverse_sb.get(_ms_tp, _ms_tp)}]")
                if _cb.button("✏️", key=f"edit_slab_{_i}", help="Editar"):
                    st.session_state["_prefill_slab"] = {
                        "id": _ms.id, "span_m": _ms.span_m, "thickness_cm": _ms.thickness_cm,
                        "effective_depth_cm": _ms.effective_depth_cm,
                        "slab_type_lbl": _type_reverse_sb.get(_ms_tp, "Maciça 1D"),
                        "level": getattr(_ms, "level", "piso"),
                        "direction": getattr(_ms, "direction", "x") or "x",
                        "gk_kn_m2": _ms.gk_kn_m2, "qk_kn_m2": _ms.qk_kn_m2,
                        "catalog_id": getattr(_ms, "catalog_id", None),
                    }
                    st.session_state.manual_slabs.pop(_i)
                    st.rerun()
                if _cc.button("🗑", key=f"del_slab_{_i}", help="Apagar"):
                    st.session_state.manual_slabs.pop(_i)
                    st.rerun()

    # ── Pórticos — definição por tramo ───────────────────────────────────────
    _pt_list     = st.session_state.get("portico_tramos", [])
    _cc_pt       = st.session_state.get("col_config") or {}
    _n_pt_pil    = _cc_pt.get("n", 0)
    _pil_opts_pt = ["—"] + [f"P{i}" for i in range(1, _n_pt_pil + 1)]
    _pt_piso_ids = ["—"] + [s.id for s in st.session_state.manual_slabs
                             if getattr(s, "level", "piso") != "cobertura"]
    _pt_cob_ids  = ["—"] + [s.id for s in st.session_state.manual_slabs
                             if getattr(s, "level", "piso") == "cobertura"]
    _pt_by_pid: dict = {}
    for _pt in _pt_list:
        _pt_by_pid.setdefault(_pt["portico_id"], []).append(_pt)
    _n_pt_porticos = len(_pt_by_pid)

    with st.expander(f"🏗️ Pórticos ({_n_pt_porticos} pórtico(s))"):
        # ── Pórticos existentes ──
        for _ppid, _tramos in _pt_by_pid.items():
            _pa, _pb = st.columns([6, 1])
            _pa.markdown(f"**{_ppid}** — {len(_tramos)} tramos")
            if _pb.button("🗑", key=f"del_ptg_{_ppid}", help="Apagar pórtico"):
                st.session_state.portico_tramos = [t for t in _pt_list
                                                   if t["portico_id"] != _ppid]
                _rebuild_psmap(st.session_state.portico_tramos, st.session_state)
                st.rerun()
            for _tidx, _tr in enumerate(sorted(_tramos, key=lambda t: t["tramo"])):
                _ca, _cb = st.columns([9, 1])
                _cc_lbl = (f"  carga={_tr.get('carga_concentrada_kn',0):.0f}kN"
                           if _tr.get("carga_concentrada_kn", 0) else "")
                _alt_lbl = (f"  h={_tr.get('altura_m',0):.2f}m"
                            if _tr.get("altura_m") else "")
                _ca.caption(
                    f"  T{_tr['tramo']}: {_tr.get('pilar_esq','—')}→{_tr.get('pilar_dir','—')}  "
                    f"{_tr.get('span_m',0):.2f}m{_alt_lbl}{_cc_lbl}"
                )
                if _cb.button("🗑", key=f"del_ptr_{_ppid}_{_tidx}", help="Apagar tramo"):
                    st.session_state.portico_tramos = [
                        t for t in _pt_list
                        if not (t["portico_id"] == _ppid and t["tramo"] == _tr["tramo"])
                    ]
                    _rebuild_psmap(st.session_state.portico_tramos, st.session_state)
                    st.rerun()

        if _pt_list:
            st.divider()

        # ── Criar novo pórtico ──
        _draft_pt = st.session_state.get("_draft_portico")

        if _draft_pt is None:
            # Step 1: definir ID e nº de tramos
            with st.form("form_pt_header", clear_on_submit=False):
                _pt_id_new = st.text_input("ID do pórtico", value="Pórtico ",
                                           help="Ex: «Pórtico 1»")
                _pt_n_new  = st.number_input("Nº de tramos", value=3,
                                             min_value=1, max_value=20, step=1)
                if st.form_submit_button("➕ Criar pórtico"):
                    st.session_state["_draft_portico"] = {
                        "id": _pt_id_new.strip() or "Pórtico",
                        "n":  int(_pt_n_new),
                    }
                    st.rerun()
        else:
            # Step 2: preencher os N tramos
            _draft_n  = _draft_pt["n"]
            _draft_id = _draft_pt["id"]
            st.markdown(f"**{_draft_id}** — {_draft_n} tramo(s)")
            st.caption("Preenche cada tramo e clica Guardar.")

            with st.form("form_pt_fill"):
                # Default height from col_config
                _default_h = float((_cc_pt or {}).get("h_piso", 2.80))
                _tv: list = []   # (pe, pd, sp, alt, lep, ldp, lec, ldc, cc, dcc)
                for _i in range(_draft_n):
                    st.markdown(f"**Tramo {_i + 1}**")
                    _r1a, _r1b = st.columns(2)
                    _pe  = _r1a.selectbox("Pilar esq.", _pil_opts_pt,
                                          key=f"dp_pe_{_i}")
                    _pd  = _r1b.selectbox("Pilar dir.", _pil_opts_pt,
                                          key=f"dp_pd_{_i}")
                    _r2a, _r2b = st.columns(2)
                    _sp  = _r2a.number_input("Dist. entre pilares (m)", value=5.0,
                                             min_value=0.1, step=0.05,
                                             key=f"dp_sp_{_i}")
                    _alt = _r2b.number_input("Altura do piso (m)", value=_default_h,
                                             min_value=1.0, step=0.05,
                                             key=f"dp_alt_{_i}",
                                             help="Altura livre do piso neste tramo")
                    _r3a, _r3b = st.columns(2)
                    _lep = _r3a.selectbox("Laje esq piso", _pt_piso_ids,
                                          key=f"dp_lep_{_i}")
                    _ldp = _r3b.selectbox("Laje dir piso", _pt_piso_ids,
                                          key=f"dp_ldp_{_i}")
                    _r4a, _r4b = st.columns(2)
                    _lec = _r4a.selectbox("Laje esq cob", _pt_cob_ids,
                                          key=f"dp_lec_{_i}")
                    _ldc = _r4b.selectbox("Laje dir cob", _pt_cob_ids,
                                          key=f"dp_ldc_{_i}")
                    _r5a, _r5b = st.columns(2)
                    _cc_kn  = _r5a.number_input("Carga conc. (kN)", value=0.0,
                                                min_value=0.0, step=1.0,
                                                key=f"dp_cc_{_i}")
                    _cc_dpl = _r5b.number_input("Dist. ao P.dir (m)", value=0.0,
                                                min_value=0.0, step=0.05,
                                                key=f"dp_dcc_{_i}")
                    _tv.append((_pe, _pd, _sp, _alt, _lep, _ldp, _lec, _ldc,
                                _cc_kn, _cc_dpl))

                _col_ok, _col_cancel = st.columns(2)
                _pt_saved    = _col_ok.form_submit_button("✅ Guardar")
                _pt_canceled = _col_cancel.form_submit_button("❌ Cancelar")

                if _pt_saved:
                    for _i, (_pe, _pd, _sp, _alt, _lep, _ldp, _lec, _ldc,
                             _cc_kn, _cc_dpl) in enumerate(_tv):
                        _pt_list.append({
                            "portico_id": _draft_id,
                            "tramo":      _i + 1,
                            "pilar_esq":  "" if _pe  == "—" else _pe,
                            "pilar_dir":  "" if _pd  == "—" else _pd,
                            "span_m":     float(_sp),
                            "altura_m":   float(_alt),
                            "laje_esq_piso": "" if _lep == "—" else _lep,
                            "laje_dir_piso": "" if _ldp == "—" else _ldp,
                            "laje_esq_cob":  "" if _lec == "—" else _lec,
                            "laje_dir_cob":  "" if _ldc == "—" else _ldc,
                            "carga_concentrada_kn":    float(_cc_kn),
                            "dist_carga_pilar_dir_m":  float(_cc_dpl),
                        })
                    st.session_state.portico_tramos = _pt_list
                    _rebuild_psmap(_pt_list, st.session_state)
                    del st.session_state["_draft_portico"]
                    st.rerun()

                if _pt_canceled:
                    del st.session_state["_draft_portico"]
                    st.rerun()

    # ── Configuração de Cargas ───────────────────────────────────────────────
    st.divider()
    st.markdown("**Configuração de cargas**")
    with st.expander("🏠 Laje de piso"):
        _laje_opts  = {v[1]: k for k, v in LAJE.items()}
        _iso_opts   = {v[1]: k for k, v in ISOLAMENTO.items()}
        _acab_opts  = {v[1]: k for k, v in ACABAMENTO_PISO.items()}
        _uso_opts   = {v[1]: k for k, v in USE_CATEGORY.items()}

        lj_laje  = st.selectbox("Tipo de laje",    list(_laje_opts.keys()), index=2, key="lj_laje")
        lj_bet1  = st.number_input("1ª Betonilha (cm)", value=12, min_value=0, max_value=30, step=1, key="lj_bet1")
        lj_iso   = st.selectbox("Isolamento térmico", list(_iso_opts.keys()), index=1, key="lj_iso")
        lj_bet2  = st.number_input("2ª Betonilha regularização (cm)", value=5, min_value=0, max_value=15, step=1, key="lj_bet2")
        lj_acab  = st.selectbox("Acabamento piso", list(_acab_opts.keys()), index=0, key="lj_acab")
        lj_uso   = st.selectbox("Utilização", list(_uso_opts.keys()), index=0, key="lj_uso")
        lj_pared = st.checkbox("Paredes divisórias (+1 kN/m²)", value=True, key="lj_pared")

        _cfg_piso = LoadConfigurator()
        _gk_p, _qk_p, _bdown_p = _cfg_piso.calc_floor(
            _laje_opts[lj_laje], lj_bet1, _iso_opts[lj_iso],
            lj_bet2, _acab_opts[lj_acab], _uso_opts[lj_uso], lj_pared)
        st.success(f"**gk = {_gk_p} kN/m²  |  qk = {_qk_p} kN/m²**")
        with st.expander("Ver decomposição"):
            for _l in _bdown_p:
                st.caption(_l)

    with st.expander("🏗️ Laje de cobertura"):
        _imp_opts   = {v[1]: k for k, v in IMPERMEABILIZACAO.items()}
        _pend_opts  = {v[1]: k for k, v in BETONILHA_PENDENTE.items()}
        _acob_opts  = {v[1]: k for k, v in ACABAMENTO_COB.items()}
        _equip_opts = {v[1]: k for k, v in EQUIPAMENTOS_COB.items()}

        cb_laje  = st.selectbox("Tipo de laje",        list(_laje_opts.keys()), index=2, key="cb_laje")
        cb_imp   = st.selectbox("Impermeabilização",    list(_imp_opts.keys()),  index=1, key="cb_imp")
        cb_iso   = st.selectbox("Isolamento",           list(_iso_opts.keys()),  index=2, key="cb_iso")
        cb_pend  = st.selectbox("Betonilha de pendente",list(_pend_opts.keys()), index=2, key="cb_pend")
        cb_acab  = st.selectbox("Acabamento/protecção", list(_acob_opts.keys()), index=0, key="cb_acab")
        cb_equip = st.selectbox("Equipamentos",         list(_equip_opts.keys()),index=0, key="cb_equip")
        cb_uso   = st.selectbox("Utilização cobertura",
                                ["Cobertura — acesso manutenção", "Cobertura — acessível ao público"],
                                index=0, key="cb_uso")
        _uso_cob_key = "cobertura_manutencao" if "manutenção" in cb_uso else "cobertura_acessivel"

        _cfg_cob = LoadConfigurator()
        _gk_c, _qk_c, _bdown_c = _cfg_cob.calc_roof(
            _laje_opts[cb_laje], _imp_opts[cb_imp], _iso_opts[cb_iso],
            _pend_opts[cb_pend], _acob_opts[cb_acab], _equip_opts[cb_equip], _uso_cob_key)
        st.success(f"**gk = {_gk_c} kN/m²  |  qk = {_qk_c} kN/m²**")
        with st.expander("Ver decomposição"):
            for _l in _bdown_c:
                st.caption(_l)

    with st.expander("🚗 Zonas especiais"):
        _col1, _col2 = st.columns(2)
        with _col1:
            st.caption("**Varanda**")
            _gk_var, _qk_var = LoadConfigurator().calc_varanda()
            st.info(f"gk={_gk_var} | qk={_qk_var} kN/m²")
        with _col2:
            st.caption("**Garagem**")
            _gar_veh = st.selectbox("Tipo", ["garagem_ligeiros","garagem_pesados"], key="gar_veh")
            _gk_gar, _qk_gar = LoadConfigurator().calc_garagem(veiculos=_gar_veh)
            st.info(f"gk={_gk_gar} | qk={_qk_gar} kN/m²")

    # Store load config for use in analysis
    st.session_state["load_cfg"] = {
        "gk_piso": _gk_p, "qk_piso": _qk_p,
        "gk_cob":  _gk_c, "qk_cob":  _qk_c,
        "gk_var":  _gk_var, "qk_var": _qk_var,
        "gk_gar":  _gk_gar, "qk_gar": _qk_gar,
    }

    # ── Pre-dimensionamento de pilares ───────────────────────────────────────
    st.divider()
    st.markdown("**Pré-dimensionamento de pilares**")
    with st.expander("⚙️ Calcular secções automaticamente"):
        st.caption("O programa calcula as dimensões mínimas para cada pilar com base nas cargas e na área tributária.")
        pd_gk      = st.number_input("gk por piso (kN/m²)", value=5.0, min_value=1.0, step=0.5)
        pd_qk      = st.number_input("qk por piso (kN/m²)", value=2.0, min_value=0.5, step=0.5)
        pd_npisos  = st.number_input("Nº de pisos", value=3, min_value=1, max_value=30, step=1)
        pd_h       = st.number_input("Altura do piso (m)", value=3.0, min_value=2.0, step=0.25)
        pd_shape   = st.selectbox("Forma", ["rectangular", "circular"])
        pd_safety  = st.slider("Margem de segurança", 1.00, 1.30, 1.10, 0.05)
        pd_span    = st.number_input("Vão médio estimado (m)", value=4.0, min_value=2.0, step=0.5,
                                     help="Usado quando não há pilares adjacentes na direcção")
        predim_btn = st.button("📐 Pré-dimensionar", use_container_width=True)

    st.divider()
    run_btn = st.button("▶  Correr cálculo", type="primary", use_container_width=True) \
              or st.session_state.pop("_trigger_recalc", False)

    has_project = st.session_state.project is not None
    opt_btn = st.button(
        "⚡  Otimizar projeto",
        use_container_width=True,
        disabled=not has_project,
    )

    if has_project:
        st.divider()
        st.markdown("**Downloads**")

        if st.session_state.dxf_bytes:
            st.download_button(
                "⬇  DXF planta",
                data=st.session_state.dxf_bytes,
                file_name="planta_estrutura.dxf",
                mime="application/octet-stream",
                use_container_width=True,
            )

        gen_docx = st.button("📄  Gerar relatório DOCX", use_container_width=True)

        if st.session_state.docx_bytes:
            st.download_button(
                "⬇  Guardar DOCX",
                data=st.session_state.docx_bytes,
                file_name="relatorio_estrutural.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

        st.divider()
        st.markdown("**Peças Desenhadas**")
        gen_drawings = st.button("🖊  Gerar desenhos", use_container_width=True,
                                 help="Gera planta de fundações, lajes e quadro de pilares")
        if gen_drawings or st.session_state.get("drawings_ready"):
            try:
                from analysis.drawings import (draw_beam_schedule_dxf,
                                               draw_foundation_plan_dxf,
                                               draw_slab_plan_dxf,
                                               draw_column_schedule_dxf,
                                               draw_footing_schedule_dxf,
                                               draw_slab_schedule_dxf,
                                               draw_retaining_wall_schedule_dxf,
                                               draw_footing_detail_dxf,
                                               draw_column_section_dxf,
                                               draw_tie_beam_detail_dxf,
                                               draw_wall_detail_dxf)
                _p = st.session_state.project
                if not st.session_state.get("drawings_ready"):
                    with st.spinner("A gerar desenhos DXF…"):
                        st.session_state["dxf_vigas"]         = draw_beam_schedule_dxf(_p)
                        st.session_state["dxf_fundacoes"]     = draw_foundation_plan_dxf(_p)
                        st.session_state["dxf_piso"]          = draw_slab_plan_dxf(_p, "PLANTA DA LAJE DE PISO")
                        st.session_state["dxf_cobertura"]     = draw_slab_plan_dxf(_p, "PLANTA DA LAJE DE COBERTURA")
                        st.session_state["dxf_pilares"]       = draw_column_schedule_dxf(_p)
                        st.session_state["dxf_sapatas"]       = draw_footing_schedule_dxf(_p)
                        st.session_state["dxf_lajes"]         = draw_slab_schedule_dxf(_p)
                        st.session_state["dxf_muros"]         = draw_retaining_wall_schedule_dxf(_p)
                        st.session_state["dxf_porm_sapatas"]  = draw_footing_detail_dxf(_p)
                        st.session_state["dxf_porm_pilares"]  = draw_column_section_dxf(_p)
                        st.session_state["dxf_porm_equilib"]  = draw_tie_beam_detail_dxf(_p)
                        st.session_state["dxf_porm_muros"]    = draw_wall_detail_dxf(_p)
                        st.session_state["drawings_ready"] = True
                if st.session_state.get("dxf_fundacoes"):
                    st.download_button("⬇  Planta Fundações (DXF)",
                        data=st.session_state["dxf_fundacoes"],
                        file_name="planta_fundacoes.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_piso"):
                    st.download_button("⬇  Planta Laje Piso (DXF)",
                        data=st.session_state["dxf_piso"],
                        file_name="laje_piso.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_cobertura"):
                    st.download_button("⬇  Planta Laje Cobertura (DXF)",
                        data=st.session_state["dxf_cobertura"],
                        file_name="laje_cobertura.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_pilares"):
                    st.download_button("⬇  Quadro de Pilares (DXF)",
                        data=st.session_state["dxf_pilares"],
                        file_name="quadro_pilares.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_sapatas"):
                    st.download_button("⬇  Quadro de Sapatas (DXF)",
                        data=st.session_state["dxf_sapatas"],
                        file_name="quadro_sapatas.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_vigas"):
                    st.download_button("⬇  Quadro de Vigas (DXF)",
                        data=st.session_state["dxf_vigas"],
                        file_name="quadro_vigas.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_lajes"):
                    st.download_button("⬇  Quadro de Lajes (DXF)",
                        data=st.session_state["dxf_lajes"],
                        file_name="quadro_lajes.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_muros"):
                    st.download_button("⬇  Muros e Sapatas Corridas (DXF)",
                        data=st.session_state["dxf_muros"],
                        file_name="muros_sapatas_corridas.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                # Pormenores
                st.markdown("**Pormenores**")
                if st.session_state.get("dxf_porm_sapatas"):
                    st.download_button("⬇  Pormenor Sapatas Isoladas (DXF)",
                        data=st.session_state["dxf_porm_sapatas"],
                        file_name="pormenor_sapatas_isoladas.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_porm_pilares"):
                    st.download_button("⬇  Pormenor Pilares — Secção (DXF)",
                        data=st.session_state["dxf_porm_pilares"],
                        file_name="pormenor_pilares_seccao.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_porm_equilib"):
                    st.download_button("⬇  Pormenor Vigas de Equilíbrio (DXF)",
                        data=st.session_state["dxf_porm_equilib"],
                        file_name="pormenor_vigas_equilibrio.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
                if st.session_state.get("dxf_porm_muros"):
                    st.download_button("⬇  Pormenor Muro de Betão (DXF)",
                        data=st.session_state["dxf_porm_muros"],
                        file_name="pormenor_muro_betao.dxf",
                        mime="application/octet-stream",
                        use_container_width=True)
            except Exception as _e:
                st.error(f"Erro ao gerar desenhos: {_e}")
    else:
        gen_docx = False


# ─── Actions ──────────────────────────────────────────────────────────────────
if run_btn:
    with st.spinner("A correr o cálculo…"):
        try:
            if mode == "DXF":
                dxf_path = save_upload(dxf_upload)
                if not dxf_path:
                    st.error("Faz upload de um ficheiro DXF.")
                    st.stop()
                imp = SimpleDXFImporter()
                columns = imp.import_columns(dxf_path)
                if not columns:
                    st.error("O DXF não contém círculos na layer PILARES.")
                    st.stop()
                beams = imp.import_beams(dxf_path, columns)
                slabs = imp.import_slabs(dxf_path)
            else:
                col_path = save_upload(col_csv)
                beam_path = save_upload(beam_csv)
                slab_path = save_upload(slab_csv)
                if col_path:
                    columns = CSVGeometryImporter().load_columns(col_path)
                elif st.session_state.get("predim_cols"):
                    columns = st.session_state["predim_cols"]
                elif st.session_state.get("col_config"):
                    import math as _math
                    _cc3 = st.session_state["col_config"]
                    _n3 = _cc3["n"]
                    _cpr = max(1, _math.ceil(_math.sqrt(_n3)))
                    _h_col_total = _cc3["h_cave"]   # governing height for buckling = cave story
                    columns = [
                        Column(
                            id=f"P{_i3+1}",
                            x=float(_i3 % _cpr) * 5.0,
                            y=float(_i3 // _cpr) * 5.0,
                            width_cm=float(_cc3["b"]),
                            depth_cm=float(_cc3["h"]),
                            height_m=_h_col_total,
                        )
                        for _i3 in range(_n3)
                    ]
                else:
                    columns = build_demo_columns()
                beams = CSVBeamImporter().load_beams(beam_path, columns) if beam_path else []
                slabs = CSVSlabImporter().load_slabs(slab_path) if slab_path else []

            slab_loads_path = save_upload(slab_loads_csv)
            slab_loads = (
                CSVSlabLoadImporter().load_slab_loads(slab_loads_path)
                if slab_loads_path
                else None
            )

            lcfg = st.session_state.get("load_cfg") or {}
            # Merge manually added slabs (avoid duplicates by ID)
            _existing_ids = {s.id for s in slabs}
            for _ms in st.session_state.get("manual_slabs", []):
                if _ms.id not in _existing_ids:
                    slabs.append(_ms)
                    _existing_ids.add(_ms.id)
            # Apply pórtico→slab assignments: update slab.support_beam_ids and beam.supported_slab_ids
            _psmap = st.session_state.get("portico_slab_map", {})
            if _psmap:
                _bid_by_portico = {}
                for _b in beams:
                    _pid = getattr(_b, 'portico_id', '') or _b.id
                    if getattr(_b, 'beam_type', None) == BeamType.FRAME:
                        _bid_by_portico.setdefault(_pid, []).append(_b.id)
                _slab_by_id = {s.id: s for s in slabs}
                for _pid, _slab_ids in _psmap.items():
                    _beam_ids_in = _bid_by_portico.get(_pid, [])
                    for _sid in _slab_ids:
                        _s = _slab_by_id.get(_sid)
                        if _s:
                            for _bid in _beam_ids_in:
                                if _bid not in _s.support_beam_ids:
                                    _s.support_beam_ids.append(_bid)
                    for _b in beams:
                        if _b.id in _beam_ids_in:
                            for _sid in _slab_ids:
                                if _sid not in _b.supported_slab_ids:
                                    _b.supported_slab_ids.append(_sid)
            project = Project(
                name=project_name,
                location=location,
                soil_allowable_mpa=soil_mpa,
                columns=columns,
                beams=beams,
                slabs=slabs,
                walls=list(st.session_state.manual_walls),
                flat_slabs=list(st.session_state.manual_flat_slabs),
                stairs=list(st.session_state.manual_stairs),
                retaining_walls=list(st.session_state.manual_retaining_walls),
                fck_mpa=fck_mpa,
                fyk_mpa=fyk_mpa,
            )
            # Apply project metadata
            project.owner         = st.session_state.get("owner", "")
            project.building_type = st.session_state.get("building_type", "Habitação")
            project.designer      = st.session_state.get("designer", "")
            # Apply load configuration (safe even if model fields don't exist yet)
            project.gk_floor_kn_m2 = lcfg.get("gk_piso", 6.15)
            project.qk_floor_kn_m2 = lcfg.get("qk_piso", 2.0)
            project.gk_roof_kn_m2  = lcfg.get("gk_cob",  5.5)
            project.qk_roof_kn_m2  = lcfg.get("qk_cob",  1.0)
            # Apply user beam section overrides (e.g. vigas planas with h = slab thickness)
            _bov_run = st.session_state.get("beam_overrides", {})
            for _b in project.beams:
                _ov = _bov_run.get(_b.id, {})
                if _ov.get("width_cm"):
                    _b.width_cm = float(_ov["width_cm"])
                if _ov.get("height_cm"):
                    _b.height_cm = float(_ov["height_cm"])
                    _b.effective_depth_cm = float(_ov["height_cm"]) - 5.0
            AutoPipeline().run(project, slab_loads=slab_loads)
            ProjectAdvisor().project_score(project)
            ProjectAdvisor().generate_advice(project)
            store_snapshot(project, "baseline")
            run_outputs(project)
            st.session_state.project = project
            st.rerun()
        except Exception as exc:
            st.error(f"Erro: {exc}")
            st.code(traceback.format_exc())

if opt_btn and st.session_state.project:
    with st.spinner("A otimizar…"):
        try:
            p = st.session_state.project
            store_snapshot(p, "antes_otimizacao")
            changes = AutoOptimizer().optimize(p)
            if not changes:
                st.info("Não foram necessárias alterações automáticas.")
            else:
                reset_project_results(p)
                _bov_opt = st.session_state.get("beam_overrides", {})
                for _b in p.beams:
                    _ov = _bov_opt.get(_b.id, {})
                    if _ov.get("width_cm"):
                        _b.width_cm = float(_ov["width_cm"])
                    if _ov.get("height_cm"):
                        _b.height_cm = float(_ov["height_cm"])
                        _b.effective_depth_cm = float(_ov["height_cm"]) - 5.0
                AutoPipeline().run(p)
                ProjectAdvisor().project_score(p)
                ProjectAdvisor().generate_advice(p)
                store_snapshot(p, "depois_otimizacao")
                run_outputs(p)
                st.session_state.project = p
                st.rerun()
        except Exception as exc:
            st.error(f"Erro otimização: {exc}")
            st.code(traceback.format_exc())

if predim_btn:
    with st.spinner("A calcular secções dos pilares…"):
        try:
            # Build column list from CSV/DXF or demo
            if mode == "DXF":
                dxf_path_tmp = save_upload(dxf_upload)
                if dxf_path_tmp:
                    pd_cols = SimpleDXFImporter().import_columns(dxf_path_tmp)
                else:
                    pd_cols = build_demo_columns()
            else:
                col_path_tmp = save_upload(col_csv)
                pd_cols = (CSVGeometryImporter().load_columns(col_path_tmp)
                           if col_path_tmp else build_demo_columns())

            predimer = ColumnPreDimensioner(fck_mpa=fck_mpa, fyk_mpa=fyk_mpa)
            pd_results = predimer.run(
                pd_cols, pd_gk, pd_qk, int(pd_npisos),
                pd_h, pd_shape, pd_safety, pd_span,
            )
            st.session_state["predim_results"] = pd_results
            st.session_state["predim_cols"]    = pd_cols
            st.rerun()
        except Exception as exc:
            st.error(f"Erro pré-dimensionamento: {exc}")

if gen_docx and st.session_state.project:
    with st.spinner("A gerar relatório DOCX…"):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                docx_path = os.path.join(tmp, "relatorio.docx")
                ReportExporter().export_docx(st.session_state.project, docx_path)
                with open(docx_path, "rb") as f:
                    st.session_state.docx_bytes = f.read()
            st.rerun()
        except Exception as exc:
            st.error(f"Erro DOCX: {exc}")


# ─── Main content ─────────────────────────────────────────────────────────────
st.title("🏗️ Raptor — Análise Estrutural")

if "predim_results" in st.session_state and st.session_state["predim_results"]:
    st.subheader("📐 Pré-dimensionamento de pilares")
    pd_rows = []
    for r in st.session_state["predim_results"]:
        sec = (f"Ø{int(r.width_cm)} cm" if r.shape == "circular"
               else f"{int(r.width_cm)}×{int(r.depth_cm)} cm")
        pd_rows.append({
            "Pilar": r.col_id,
            "A. trib. (m²)": r.a_trib_m2,
            "NEd est. (kN)": r.ned_kn,
            "Secção": sec,
            "NRd (kN)": r.nrd_kn,
            "Utilização": round(r.utilization, 2),
        })
    df_pd = pd.DataFrame(pd_rows)
    st.dataframe(style_df(df_pd, ["Utilização"]), use_container_width=True, hide_index=True)
    if st.session_state.project is None:
        st.caption("💡 Estas dimensões foram aplicadas aos pilares. Clica **▶ Correr cálculo** para verificar a estrutura completa.")
    st.divider()

if st.session_state.project is None:
    st.info("Configura os parâmetros na barra lateral e clica **▶ Correr cálculo** para começar.")
    st.markdown("""
**Ficheiros de exemplo incluídos:**
| Ficheiro | Descrição |
|---|---|
| `inputs/columns_sample.csv` | Pilares com geometria |
| `inputs/beams_sample.csv` | Vigas |
| `inputs/slabs_sample.csv` | Lajes |
| `inputs/slab_loads_sample.csv` | Cargas de laje |
| `inputs/modelo_base.dxf` | Planta DXF de exemplo |

Se não fizeres upload de CSV, é usada uma **geometria demo** com 6 pilares.
    """)
    st.stop()

p: Project = st.session_state.project

# ── Recalculate scores inline (immune to module cache) ────────────────────
def _uls_beam(b):
    r = b.result
    if r is None: return 0.0
    bend  = getattr(r, "bending_utilization", 0.0)
    shear = min(getattr(r, "shear_utilization", 0.0), 1.0)  # cap: stirrups ≠ collapse
    return max(bend, shear)

def _score(worst):
    return round(max(0.0, min(1.0, 1.0 - max(0.0, worst - 0.20))), 2)

_b = [_uls_beam(b) for b in p.beams if b.result] or [0.0]
_c = [max(getattr(c.result,"utilization",0.0), 0.0) for c in p.columns if c.result] or [0.0]
_f = [max(getattr(f.result,"soil_utilization",0.0), getattr(f.result,"punching_utilization",0.0))
      for f in p.footings if f.result] or [0.0]
_els = ([max(getattr(b.result,"deflection_utilization",0.0), getattr(b.result,"crack_utilization",0.0))
         for b in p.beams if b.result]
      + [max(getattr(s.result,"deflection_utilization",0.0), getattr(s.result,"crack_utilization",0.0))
         for s in p.slabs if s.result]) or [0.0]

scores = {
    "seguranca_uls": _score(max(max(_b), max(_c), max(_f))),
    "servico_els":   _score(max(_els)),
    "fundacoes":     _score(max(_f)),
}
p.project_scores = scores

# ── Score badges ──────────────────────────────────────────────────────────────
if scores:
    c1, c2, c3, _, _ = st.columns([1, 1, 1, 1, 1])

    def _badge(col, label, key):
        v = scores.get(key, 0.0)
        color = "🟢" if v >= 0.80 else ("🟡" if v >= 0.60 else "🔴")
        col.metric(f"{color} {label}", f"{v:.2f}")

    _badge(c1, "Segurança ULS", "seguranca_uls")
    _badge(c2, "Serviço ELS", "servico_els")
    _badge(c3, "Fundações", "fundacoes")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_res, tab_porticos, tab_vfund, tab_vigas, tab_pilares, tab_lajes, tab_sapatas, tab_paredes, tab_muros, tab_fungi, tab_esc, tab_alertas, tab_planta = st.tabs([
    "📊 Resumo",
    "🏗️ Pórticos",
    "🔗 V. Fundação",
    "🔩 Vigas",
    "🏛️ Pilares",
    "⬜ Lajes",
    "⬛ Sapatas",
    "🧱 Paredes",
    "🪨 Muros",
    "⚪ L. Fungiforme",
    "🪜 Escadas",
    "⚠️ Alertas",
    "🗺️ Planta",
])

_beam_type_labels = {"frame": "Pórtico", "lintel": "Lintel/Estore", "vct": "VCT"}

# ── Resumo ────────────────────────────────────────────────────────────────────
with tab_res:
    mc = st.columns(5)
    mc[0].metric("Pilares",   len(p.columns))
    mc[1].metric("Vigas",     len(p.beams))
    mc[2].metric("Lajes",     len(p.slabs))
    mc[3].metric("Sapatas",   len(p.footings))
    mc[4].metric("Sap. Corridas", len(getattr(p, 'continuous_footings', []) or []))
    mc2 = st.columns(5)
    mc2[0].metric("V. Amarração", len(p.tie_beams))
    mc2[1].metric("Paredes",  len(p.walls))
    mc2[2].metric("Muros",    len(getattr(p, 'retaining_walls', []) or []))
    mc2[3].metric("L. Fungi.", len(p.flat_slabs))
    mc2[4].metric("Escadas",  len(p.stairs))

    if scores:
        st.subheader("Score global")
        for label, key in [
            ("Segurança ULS", "seguranca_uls"),
            ("Serviço ELS", "servico_els"),
            ("Fundações", "fundacoes"),
        ]:
            v = scores.get(key, 0.0)
            st.write(f"**{label}:** {v:.2f}")
            st.progress(min(v, 1.0))

    if p.tie_beams:
        st.subheader("Vigas de amarração / equilíbrio")
        tie_rows = [
            {
                "ID": t.id,
                "Ligação": f"{t.start_footing_id} → {t.end_footing_id}",
                "Vão (m)": round(t.span_m, 2),
                "T (kN)": round(t.tie_force_kn, 2),
                "As req (cm²)": round(t.required_as_cm2, 2),
                "Adotar": t.adopted_bars,
            }
            for t in p.tie_beams
        ]
        st.dataframe(pd.DataFrame(tie_rows), use_container_width=True, hide_index=True)

# ── Pórticos ──────────────────────────────────────────────────────────────────
with tab_porticos:
    # Deduplicate slabs from project + manual
    _seen_pt = set()
    _piso_slab_ids, _cob_slab_ids = [], []
    for _s in list(p.slabs) + list(st.session_state.manual_slabs):
        if _s.id in _seen_pt:
            continue
        _seen_pt.add(_s.id)
        if getattr(_s, "level", "piso") == "cobertura":
            _cob_slab_ids.append(_s.id)
        else:
            _piso_slab_ids.append(_s.id)

    # Beam lookup by portico_id (for results display only)
    _beam_by_pid: dict = {}
    _other_beams: list = []
    for _b in p.beams:
        _bpid = (getattr(_b, "portico_id", "") or "").strip()
        _btype = getattr(_b, "beam_type", BeamType.FRAME)
        if _btype == BeamType.FRAME and _bpid:
            _beam_by_pid.setdefault(_bpid, []).append(_b)
        elif _btype != BeamType.FRAME:
            _other_beams.append(_b)

    # Pórticos defined in sidebar via portico_tramos
    _pt_tramos_all = st.session_state.get("portico_tramos", [])
    _pt_groups: dict = {}   # portico_id → [tramo dicts]
    for _t in _pt_tramos_all:
        _pt_groups.setdefault(_t["portico_id"], []).append(_t)

    _ptop1, _ptop2 = st.columns([3, 1])
    _ptop1.caption(
        f"{len(_pt_groups)} pórtico(s) definido(s).  "
        "Confirma as lajes de cada pórtico e clica **▶ Recalcular**."
    )
    if _ptop2.button("▶ Recalcular", type="primary", key="btn_recalc_portico",
                     help="Aplica as atribuições e recalcula a estrutura"):
        st.session_state["_trigger_recalc"] = True
        st.rerun()

    if not _pt_groups:
        st.info("Ainda não tens pórticos definidos.  "
                "Usa o expander **🏗️ Pórticos** na barra lateral para os criar.")
    else:
        _psmap = st.session_state["portico_slab_map"]
        for _pid, _tramos in _pt_groups.items():
            st.subheader(f"🏗️ {_pid}")

            # Tramo summary table
            _tr_rows = []
            for _tr in sorted(_tramos, key=lambda x: x["tramo"]):
                _cc_txt = (f"{_tr.get('carga_concentrada_kn', 0):.0f} kN"
                           if _tr.get("carga_concentrada_kn", 0) else "—")
                _tr_rows.append({
                    "Tramo": _tr["tramo"],
                    "P. esq.": _tr.get("pilar_esq", "—") or "—",
                    "P. dir.": _tr.get("pilar_dir", "—") or "—",
                    "Dist. (m)": round(_tr.get("span_m", 0), 2),
                    "Alt. (m)":  round(_tr.get("altura_m", 0), 2) if _tr.get("altura_m") else "—",
                    "Laje esq.": _tr.get("laje_esq_piso", "") or _tr.get("laje_esq_cob", "") or "—",
                    "Laje dir.": _tr.get("laje_dir_piso", "") or _tr.get("laje_dir_cob", "") or "—",
                    "Carga conc.": _cc_txt,
                })
            st.dataframe(pd.DataFrame(_tr_rows), use_container_width=True, hide_index=True)

            # Seed portico_slab_map from tramos if not yet set
            if _pid not in _psmap:
                _seeded: list = []
                for _tr in _tramos:
                    for _sk in ("laje_esq_piso", "laje_dir_piso",
                                "laje_esq_cob", "laje_dir_cob"):
                        _sv = _tr.get(_sk, "")
                        if _sv and _sv not in _seeded:
                            _seeded.append(_sv)
                _psmap[_pid] = _seeded

            _cur_sel = _psmap[_pid]
            _lc1, _lc2 = st.columns(2)
            with _lc1:
                _sel_piso = st.multiselect(
                    "🏠 Lajes de piso",
                    options=_piso_slab_ids,
                    default=[s for s in _cur_sel if s in _piso_slab_ids],
                    key=f"pmap_{_pid}_piso",
                )
            with _lc2:
                _sel_cob = st.multiselect(
                    "🏗️ Lajes de cobertura",
                    options=_cob_slab_ids,
                    default=[s for s in _cur_sel if s in _cob_slab_ids],
                    key=f"pmap_{_pid}_cob",
                )
            _psmap[_pid] = _sel_piso + _sel_cob

            # Beam results (only if beams explicitly tagged with this portico_id)
            _pbeams = _beam_by_pid.get(_pid, [])
            if _pbeams:
                _p_rows = []
                for _b in _pbeams:
                    _r = _b.result
                    _p_rows.append({
                        "Viga": _b.id,
                        "b×h (cm)": f"{int(_b.width_cm)}×{int(_b.height_cm)}",
                        "Span (m)": round(_b.span_m, 2),
                        "Msd (kNm)": round(_r.msd_knm, 2) if _r else "—",
                        "Vsd (kN)": round(_r.vsd_kn, 2) if _r else "—",
                        "As req (cm²)": round(_r.required_as_cm2, 2) if _r else "—",
                        "Armadura": (_b.reinforcement_result or {}).get("bottom_text", "—"),
                        "U. Flex.": round(getattr(_r, "bending_utilization", 0.0), 2) if _r else "—",
                        "U. Corte": round(_r.shear_utilization, 2) if _r else "—",
                    })
                st.dataframe(
                    style_df(pd.DataFrame(_p_rows), ["U. Flex.", "U. Corte"]),
                    use_container_width=True, hide_index=True,
                )
            st.divider()

    # All FRAME beams without a portico_id assigned
    _untagged_frame = [_b for _b in p.beams
                       if getattr(_b, "beam_type", BeamType.FRAME) == BeamType.FRAME
                       and not (getattr(_b, "portico_id", "") or "").strip()]
    if _untagged_frame:
        with st.expander(f"🔩 Vigas de pórtico sem ID atribuído ({len(_untagged_frame)})"):
            _uf_rows = []
            for _b in _untagged_frame:
                _r = _b.result
                _uf_rows.append({
                    "Viga": _b.id,
                    "b×h (cm)": f"{int(_b.width_cm)}×{int(_b.height_cm)}",
                    "Span (m)": round(_b.span_m, 2),
                    "Msd (kNm)": round(_r.msd_knm, 2) if _r else "—",
                    "Vsd (kN)": round(_r.vsd_kn, 2) if _r else "—",
                    "U. Flex.": round(getattr(_r, "bending_utilization", 0.0), 2) if _r else "—",
                    "U. Corte": round(_r.shear_utilization, 2) if _r else "—",
                })
            st.dataframe(
                style_df(pd.DataFrame(_uf_rows), ["U. Flex.", "U. Corte"]),
                use_container_width=True, hide_index=True,
            )

    # VCT + LINTEL beams summary
    if _other_beams:
        with st.expander(f"🔩 Outros tipos de viga ({len(_other_beams)}) — Lintéis / VCT"):
            _ot_rows = []
            for _b in _other_beams:
                _r = _b.result
                _ot_rows.append({
                    "ID": _b.id,
                    "Tipo": _beam_type_labels.get(getattr(_b, "beam_type", BeamType.FRAME).value, "-"),
                    "b×h (cm)": f"{int(_b.width_cm)}×{int(_b.height_cm)}",
                    "Span (m)": round(_b.span_m, 2),
                    "Msd (kNm)": round(_r.msd_knm, 2) if _r else "—",
                    "Vsd (kN)": round(_r.vsd_kn, 2) if _r else "—",
                    "U. Flex.": round(getattr(_r, "bending_utilization", 0.0), 2) if _r else "—",
                    "U. Corte": round(_r.shear_utilization, 2) if _r else "—",
                })
            st.dataframe(
                style_df(pd.DataFrame(_ot_rows), ["U. Flex.", "U. Corte"]),
                use_container_width=True, hide_index=True,
            )

# ── Vigas de Fundação ─────────────────────────────────────────────────────────
with tab_vfund:
    _cont_footings = getattr(p, 'continuous_footings', []) or []

    if p.tie_beams:
        st.subheader("🔗 Vigas de amarração / equilíbrio (CB.)")
        st.caption("Vigas de amarração geradas automaticamente entre sapatas excêntricas (EC2 §9.10.2 — força de tração mínima).")
        _tb_rows = []
        for _tb in p.tie_beams:
            _tb_rows.append({
                "ID": _tb.id,
                "Sapata A": _tb.start_footing_id,
                "Sapata B": _tb.end_footing_id,
                "b×h (cm)": f"{int(_tb.width_cm)}×{int(_tb.height_cm)}",
                "Span (m)": round(_tb.span_m, 2),
                "T (kN)": round(_tb.tie_force_kn, 2),
                "As req (cm²)": round(_tb.required_as_cm2, 2),
                "Adotar": _tb.adopted_bars,
            })
        st.dataframe(pd.DataFrame(_tb_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Sem vigas de amarração geradas (não há sapatas excêntricas ou o modelo não gerou CB.).")

    if _cont_footings:
        st.divider()
        st.subheader("📐 Sapatas corridas")
        _cf_rows = []
        for _cf in _cont_footings:
            _cr = _cf.result
            _cf_rows.append({
                "ID": _cf.id,
                "Muro": _cf.related_wall_id,
                "Larg (cm)": _cf.width_cm,
                "Alt (cm)": _cf.height_cm,
                "Comp (m)": round(_cf.length_m, 2),
                "σ (kPa)": round(_cr.soil_stress_mpa * 1000, 1) if _cr else "-",
                "U. Solo": round(_cr.soil_utilization, 2) if _cr else "-",
                "As (cm²/m)": round(_cr.required_as_cm2_m, 2) if _cr else "-",
                "U. Flex.": round(_cr.bending_utilization, 2) if _cr else "-",
                "U. Corte": round(_cr.shear_utilization, 2) if _cr else "-",
            })
        st.dataframe(
            style_df(pd.DataFrame(_cf_rows), ["U. Solo", "U. Flex.", "U. Corte"]),
            use_container_width=True, hide_index=True,
        )

# ── Vigas ─────────────────────────────────────────────────────────────────────
with tab_vigas:
    # Editor: set max_height_cm per beam (for caixa de estore)
    _beams_with_limit = [b for b in p.beams if getattr(b, 'max_height_cm', 0.0) > 0]
    with st.expander(f"✏️ Editar restrições de altura (caixa de estore) — {len(_beams_with_limit)} viga(s) com limite"):
        st.caption("Define altura máxima para vigas em caixa de estore. 0 = sem restrição.")
        _bec_cols = st.columns(min(4, max(1, len(p.beams))))
        for _bi, _beam in enumerate(p.beams):
            _bec = _bec_cols[_bi % len(_bec_cols)]
            _cur_mh = float(getattr(_beam, 'max_height_cm', 0.0))
            _new_mh = _bec.number_input(
                f"{_beam.id} (cm)", value=_cur_mh, min_value=0.0, step=5.0,
                key=f"mh_{_beam.id}", help="0 = sem restrição de altura"
            )
            if _new_mh != _cur_mh:
                _beam.max_height_cm = _new_mh

    # Editor: set beam cross-section b×h (useful for vigas planas where h = slab thickness)
    _bov_state = st.session_state.get("beam_overrides", {})
    _bov_changed = dict(_bov_state)
    with st.expander("✏️ Editar secção das vigas (b×h) — vigas planas e ajustes manuais"):
        st.caption("Altera b×h de qualquer viga. Clica **▶ Correr cálculo** para aplicar as dimensões alteradas.")
        _bsec_hdr = st.columns([0.35, 0.32, 0.33])
        _bsec_hdr[0].markdown("**Viga**")
        _bsec_hdr[1].markdown("**b (cm)**")
        _bsec_hdr[2].markdown("**h (cm)**")
        for _beam in p.beams:
            _ov = _bov_changed.get(_beam.id, {})
            _cur_b = float(_ov.get("width_cm",  _beam.width_cm))
            _cur_h = float(_ov.get("height_cm", _beam.height_cm))
            _col_lbl, _col_b, _col_h = st.columns([0.35, 0.32, 0.33])
            _col_lbl.markdown(f"**{_beam.id}** ({int(_beam.width_cm)}×{int(_beam.height_cm)})")
            _new_b = _col_b.number_input(
                "b", value=_cur_b, min_value=10.0, max_value=150.0, step=5.0,
                key=f"bov_b_{_beam.id}", label_visibility="collapsed"
            )
            _new_h = _col_h.number_input(
                "h", value=_cur_h, min_value=10.0, max_value=200.0, step=5.0,
                key=f"bov_h_{_beam.id}", label_visibility="collapsed"
            )
            _bov_changed[_beam.id] = {"width_cm": _new_b, "height_cm": _new_h}
    st.session_state.beam_overrides = _bov_changed

    rows = []
    for b in p.beams:
        r = b.result
        rr = b.reinforcement_result or {}
        bt_label = _beam_type_labels.get(getattr(b, 'beam_type', 'frame'), getattr(b, 'beam_type', 'frame'))
        mh = getattr(b, 'max_height_cm', 0.0)
        rows.append({
            "ID": b.id,
            "Pórtico": getattr(b, 'portico_id', '') or "-",
            "Tipo": bt_label,
            "Nós": f"{b.start_node}→{b.end_node}",
            "b×h (cm)": f"{int(b.width_cm)}×{int(b.height_cm)}",
            "h.max (cm)": f"{int(mh)}" if mh > 0 else "-",
            "Span (m)": round(b.span_m, 2),
            "Msd (kNm)": round(r.msd_knm, 2) if r else "-",
            "MRd (kNm)": round(getattr(r, "mrd_knm", 0.0), 2) if r else "-",
            "Vsd (kN)": round(r.vsd_kn, 2) if r else "-",
            "VRd (kN)": round(getattr(r, "vrd_kn", 0.0), 2) if r else "-",
            "As req (cm²)": round(r.required_as_cm2, 2) if r else "-",
            "Armadura": rr.get("bottom_text", "-"),
            "Estribos": rr.get("stirrups_text", "-"),
            "U. Flexão": round(getattr(r, "bending_utilization", 0.0), 2) if r else "-",
            "U. Corte": round(r.shear_utilization, 2) if r else "-",
            "U. Flecha": round(r.deflection_utilization, 2) if r else "-",
            "U. Fissura": round(r.crack_utilization, 2) if r else "-",
        })
    df_beams = pd.DataFrame(rows)
    st.dataframe(
        style_df(df_beams, ["U. Flexão", "U. Corte", "U. Flecha", "U. Fissura"]),
        use_container_width=True, hide_index=True,
    )

# ── Pilares ───────────────────────────────────────────────────────────────────
with tab_pilares:
    # Building heights info banner
    _cc_tab = st.session_state.get("col_config")
    if _cc_tab:
        _h_tot_tab = _cc_tab["h_cave"] + max(0, _cc_tab["n_pisos"] - 1) * _cc_tab["h_piso"]
        _cont_tab = st.session_state.get("cols_in_cont_footing", [])
        _info_cols = st.columns(4)
        _info_cols[0].metric("Pilares", f"{_cc_tab['n']} (P1–P{_cc_tab['n']})")
        _info_cols[1].metric("Pisos", _cc_tab["n_pisos"])
        _info_cols[2].metric("H cave→piso1", f"{_cc_tab['h_cave']:.2f} m")
        _info_cols[3].metric("H entre pisos", f"{_cc_tab['h_piso']:.2f} m")
        if _cont_tab:
            st.caption(f"Sapata corrida: {', '.join(_cont_tab)} | "
                       f"Sapatas isoladas: {', '.join(c.id for c in p.columns if c.id not in _cont_tab)}")
        st.divider()

    # Editor: set stops_at per column
    with st.expander("✏️ Editar nível dos pilares (termina em piso / cobertura)"):
        st.caption("Pilares que terminam na laje de piso não aparecem no nível de Cobertura do quadro.")
        _n_cols = min(4, len(p.columns))
        _col_editor_cols = st.columns(_n_cols) if _n_cols > 0 else []
        for _ci, _col in enumerate(p.columns):
            _ec = _col_editor_cols[_ci % _n_cols] if _col_editor_cols else st
            _current = getattr(_col, 'stops_at', 'cobertura')
            _new = _ec.selectbox(
                _col.id,
                options=["cobertura", "piso"],
                index=0 if _current == "cobertura" else 1,
                key=f"stops_at_{_col.id}",
                label_visibility="visible",
            )
            if _new != _current:
                _col.stops_at = _new

    rows = []
    for c in p.columns:
        r = c.result
        rows.append({
            "ID": c.id,
            "Termina em": getattr(c, 'stops_at', 'cobertura').capitalize(),
            "x (m)": round(c.x, 2),
            "y (m)": round(c.y, 2),
            "Secção": c.label(),
            "Forma": c.shape,
            "h (m)": round(c.height_m, 2),
            "Nsd (kN)": round(r.nsd_kn, 2) if r else "-",
            "Nrd (kN)": round(r.nrd_kn, 2) if r else "-",
            "As req (cm²)": round(r.required_as_cm2, 2) if r else "-",
            "As adot (cm²)": round(r.adopted_as_cm2, 2) if r else "-",
            "Esbelteza": round(r.slenderness, 1) if r else "-",
            "Utilização": round(r.utilization, 2) if r else "-",
        })
    df_cols = pd.DataFrame(rows)
    st.dataframe(
        style_df(df_cols, ["Utilização"]),
        use_container_width=True, hide_index=True,
    )

# ── Lajes ─────────────────────────────────────────────────────────────────────
with tab_lajes:
    # Lajes manuais — adicionadas na barra lateral
    if st.session_state.manual_slabs:
        with st.expander(f"✅ {len(st.session_state.manual_slabs)} laje(s) adicionada(s) manualmente — ver lista"):
            for _ms in st.session_state.manual_slabs:
                _bids = ", ".join(_ms.support_beam_ids) if _ms.support_beam_ids else "(atribuir na tab Pórticos)"
                st.caption(f"**{_ms.id}** | {getattr(_ms,'level','piso')} | vão {_ms.span_m}m | "
                           f"h={int(_ms.thickness_cm)}cm | gk={_ms.gk_kn_m2:.1f} qk={_ms.qk_kn_m2:.1f} | apoios: {_bids}")
    else:
        st.caption("Adiciona lajes na **barra lateral** (secção ⬜ Lajes) e clica **▶ Correr cálculo**.")
    st.divider()

    # Presdouro catalog selector
    if _CATALOG_OK:
        with st.expander(f"📖 Catálogo ({len(CATALOG)} lajes — PAVINORTE + Presdouro)"):
            st.caption("Seleciona a laje para cada painel ou deixa o programa escolher automaticamente.")
            cc1, cc2, cc3 = st.columns(3)
            cat_span = cc1.number_input("Vão (m)", value=4.0, min_value=1.0, step=0.5, key="cat_span")
            cat_gk   = cc2.number_input("gk (kN/m²)", value=5.5, min_value=0.0, step=0.5, key="cat_gk")
            cat_qk   = cc3.number_input("qk (kN/m²)", value=2.0, min_value=0.0, step=0.5, key="cat_qk")
            if st.button("🔍 Encontrar laje mínima"):
                from analysis.combinations import CombinationEngine
                _comb = CombinationEngine()
                _qd  = _comb.uls_fundamental(cat_gk, cat_qk)
                _med = _qd * cat_span**2 / 8.0
                _ved = _qd * cat_span / 2.0
                _best = select_slab(_med, _ved, max_height_cm=35.0, safety=1.0)
                if _best:
                    st.success(f"**{_best.nome}** — h={_best.altura_cm:.0f}cm | "
                               f"peso={_best.pesom2:.2f} kN/m² | "
                               f"MRd={_best.mrd_knm_m:.1f} kNm/m | "
                               f"VRd={_best.vrd_kn_m:.1f} kN/m | "
                               f"EI={_best.ei_kn_m2_m:.0f} kN·m²/m")
                    st.caption(f"MEd={_med:.1f} kNm/m | VEd={_ved:.1f} kN/m")
                else:
                    st.warning("Nenhuma laje do catálogo satisfaz estes requisitos.")
        st.divider()

    # Per-slab editor: level, load zone and catalog assignment
    _pavinorte_names = [n for n in sorted(CATALOG.keys()) if n.startswith(("V3-","V5-","2V"))]
    _other_names     = [n for n in sorted(CATALOG.keys()) if not n.startswith(("V3-","V5-","2V"))]
    _cat_options = ["(automático)"] + _pavinorte_names + _other_names if _CATALOG_OK else ["(automático)"]
    _lcfg = st.session_state.get("load_cfg", {})
    _zona_loads = {
        "Habitável": (_lcfg.get("gk_piso", 6.15), _lcfg.get("qk_piso", 2.0)),
        "Garagem":   (_lcfg.get("gk_gar",  4.80), _lcfg.get("qk_gar",  2.5)),
        "Varanda":   (_lcfg.get("gk_var",  5.50), _lcfg.get("qk_var",  3.0)),
        "Cobertura": (_lcfg.get("gk_cob",  5.50), _lcfg.get("qk_cob",  1.0)),
    }
    _stype_opts = {"Aligeirada (vigotas)": "ribbed", "Maciça 1 dir.": "one_way",
                   "Maciça 2 dir.": "two_way", "Consola": "cantilever"}
    _stype_rev = {v: k for k, v in _stype_opts.items()}
    with st.expander("✏️ Editar tipo, nível, zona de carga e catálogo por laje"):
        st.caption("Zona de carga: Habitável = piso normal, Garagem = LP7; LM = Laje Maciça.")
        for _si, _sl in enumerate(p.slabs):
            _lc0, _lc1, _lc2, _lc3, _lc4 = st.columns([1, 1, 1, 2, 1])
            _lc0.markdown(f"**{_sl.id}**")
            # Slab type
            from core.model import SlabType
            _cur_st_val = _sl.slab_type.value if hasattr(_sl.slab_type, 'value') else str(_sl.slab_type)
            _cur_st_label = _stype_rev.get(_cur_st_val, "Aligeirada (vigotas)")
            _new_st_label = _lc0.selectbox(
                f"{_sl.id} — tipo", options=list(_stype_opts.keys()),
                index=list(_stype_opts.keys()).index(_cur_st_label) if _cur_st_label in _stype_opts else 0,
                key=f"slab_type_{_sl.id}", label_visibility="collapsed",
            )
            _new_st_val = _stype_opts[_new_st_label]
            if _new_st_val != _cur_st_val:
                _sl.slab_type = SlabType(_new_st_val)
                if _new_st_val in ("two_way", "cantilever"):
                    _sl.catalog_id = None  # maciças don't use PAVINORTE catalog

            _cur_lv = getattr(_sl, 'level', 'piso')
            _new_lv = _lc1.selectbox(
                f"{_sl.id} — nível", options=["piso", "cobertura"],
                index=0 if _cur_lv == 'piso' else 1,
                key=f"slab_level_{_sl.id}",
            )
            # Infer current zona from gk/qk
            _cur_zona_key = "slab_zona_" + _sl.id
            if _cur_zona_key not in st.session_state:
                _gk_now, _qk_now = _sl.gk_kn_m2, _sl.qk_kn_m2
                _best_zona = "Habitável"
                _best_diff = 9999.0
                for _zn, (_zg, _zq) in _zona_loads.items():
                    _diff = abs(_zg - _gk_now) + abs(_zq - _qk_now)
                    if _diff < _best_diff:
                        _best_diff = _diff
                        _best_zona = _zn
                st.session_state[_cur_zona_key] = _best_zona
            _zona_list = list(_zona_loads.keys())
            _new_zona = _lc2.selectbox(
                f"{_sl.id} — zona", options=_zona_list,
                index=_zona_list.index(st.session_state[_cur_zona_key]),
                key=_cur_zona_key,
            )
            _cur_cat = getattr(_sl, 'catalog_id', None) or "(automático)"
            _cat_idx = _cat_options.index(_cur_cat) if _cur_cat in _cat_options else 0
            _new_cat = _lc3.selectbox(
                f"{_sl.id} — catálogo", options=_cat_options,
                index=_cat_idx, key=f"slab_cat_{_sl.id}",
            )
            _lc4.caption(f"gk={_sl.gk_kn_m2:.2f}\nqk={_sl.qk_kn_m2:.2f}")
            if _new_lv != _cur_lv:
                _sl.level = _new_lv
            _sl.catalog_id = None if _new_cat == "(automático)" else _new_cat
            # Apply zone loads
            _zg, _zq = _zona_loads[_new_zona]
            _sl.gk_kn_m2 = _zg
            _sl.qk_kn_m2 = _zq

    _stype_map = {"one_way": "Vig.1D", "ribbed": "Alig.", "two_way": "Maç.2D", "cantilever": "Cons."}
    rows = []
    for s in p.slabs:
        r = s.result
        sv = s.slab_type.value if s.slab_type else "one_way"
        h_str = (f"{int(s.thickness_cm-5)}+5" if sv in ("ribbed","one_way") and s.thickness_cm > 5
                 else f"{s.thickness_cm:.0f}")
        rows.append({
            "ID": s.id,
            "Nível": getattr(s, 'level', 'piso').capitalize(),
            "Tipo": _stype_map.get(sv, sv),
            "Catálogo": s.catalog_id or "(auto)",
            "Span (m)": round(s.span_m, 2),
            "h1+h2": h_str,
            "Gk": round(s.gk_kn_m2, 2),
            "Qk": round(s.qk_kn_m2, 2),
            "Msd (kNm/m)": round(r.msd_knm_m, 2) if r else "-",
            "U. Flecha": round(r.deflection_utilization, 2) if r else "-",
            "U. Fissura": round(r.crack_utilization, 2) if r else "-",
        })
    df_slabs = pd.DataFrame(rows)
    st.dataframe(
        style_df(df_slabs, ["U. Flecha", "U. Fissura"]),
        use_container_width=True, hide_index=True,
    )

# ── Sapatas ───────────────────────────────────────────────────────────────────
with tab_sapatas:
    # ── Sapata corrida do muro da cave ────────────────────────────────────────
    _cont_col_set = set(st.session_state.get("cols_in_cont_footing", []))
    _rw_ids = [rw.id for rw in (p.retaining_walls or [])]
    _sw_ids = [sw.id for sw in (p.walls or [])]
    _all_wall_ids = _rw_ids + _sw_ids

    if _cont_col_set or _all_wall_ids:
        with st.expander("🔗 Sapata corrida do muro da cave", expanded=True):
            _sf_col1, _sf_col2 = st.columns(2)
            with _sf_col1:
                st.markdown("**Pilares na sapata corrida:**")
                if _cont_col_set:
                    for _cp in sorted(_cont_col_set):
                        st.caption(f"• {_cp}")
                else:
                    st.caption("Nenhum — define na barra lateral.")
            with _sf_col2:
                st.markdown("**Muro que descarrega:**")
                if _all_wall_ids:
                    for _wid in _all_wall_ids:
                        st.caption(f"• {_wid}")
                else:
                    st.caption("Sem muros definidos.")
        st.divider()

    # ── Sapatas isoladas ──────────────────────────────────────────────────────
    _isol_ftgs = [f for f in p.footings if f.related_column_id not in _cont_col_set]
    _cont_ftgs = [f for f in p.footings if f.related_column_id in _cont_col_set]
    if _cont_ftgs:
        st.caption(f"ℹ️ {len(_cont_ftgs)} pilar(es) em sapata corrida ({', '.join(f.related_column_id for f in _cont_ftgs)}) — mostrados separadamente acima.")

    # Editor: toggle footing type (concentric ↔ eccentric)
    _ftg_needs_ecc = [f for f in p.footings if f.result and f.result.needs_balance_beam]
    with st.expander(f"✏️ Editar orientação das sapatas — {len(_ftg_needs_ecc)} sapata(s) com viga de equilíbrio"):
        st.caption("Sapatas excêntricas são usadas em bordas de lote onde não é possível centrar a sapata no pilar.")
        from core.model import FootingType
        _ftg_cols = st.columns(min(4, max(1, len(p.footings))))
        for _fi, _ftg in enumerate(p.footings):
            _fc = _ftg_cols[_fi % len(_ftg_cols)]
            _cur_ft = getattr(_ftg, 'footing_type', FootingType.CONCENTRIC)
            _cur_label = "Excêntrica" if _cur_ft == FootingType.ECCENTRIC else "Concêntrica"
            _new_label = _fc.selectbox(
                _ftg.id, options=["Concêntrica", "Excêntrica"],
                index=1 if _cur_ft == FootingType.ECCENTRIC else 0,
                key=f"ftype_{_ftg.id}",
            )
            _new_ft = FootingType.ECCENTRIC if _new_label == "Excêntrica" else FootingType.CONCENTRIC
            if _new_ft != _cur_ft:
                _ftg.footing_type = _new_ft

    rows = []
    for f in p.footings:
        r = f.result
        rows.append({
            "ID": f.id,
            "Tipo": "Excêntrica" if f.footing_type == FootingType.ECCENTRIC else "Concêntrica",
            "Dim. (cm)": f"{int(f.width_a_cm)}×{int(f.width_b_cm)}×{int(f.height_cm)}",
            "Nsd (kN)": round(r.nsd_kn, 2),
            "σmin (MPa)": round(r.sigma_min_mpa, 3),
            "σmax (MPa)": round(r.sigma_max_mpa, 3),
            "U. Solo": round(r.soil_utilization, 2),
            "U. Punç.": round(r.punching_utilization, 2),
            "Levantamento": "⚠️ Sim" if r.uplift_detected else "OK",
            "Viga Eq.": "⚠️ Sim" if r.needs_balance_beam else "Não",
            "As adot (cm²)": round(r.adopted_as_cm2, 2),
        })
    df_ftg = pd.DataFrame(rows)
    st.dataframe(
        style_df(df_ftg, ["U. Solo", "U. Punç."]),
        use_container_width=True, hide_index=True,
    )

# ── Paredes estruturais ───────────────────────────────────────────────────────
with tab_paredes:
    if not p.walls:
        st.info("Sem paredes estruturais no projeto. Adiciona na barra lateral.")
    else:
        rows = []
        for w in p.walls:
            r = w.result
            rows.append({
                "ID": w.id,
                "L (m)": round(w.length_m, 2),
                "e (cm)": round(w.thickness_cm, 1),
                "H (m)": round(w.height_m, 2),
                "NEd (kN)": round(r.ned_kn, 2),
                "NRd (kN)": round(r.nrd_kn, 2),
                "VEd (kN)": round(r.ved_kn, 2),
                "VRd (kN)": round(r.vrd_kn, 2),
                "MEd (kNm)": round(r.med_knm, 2),
                "MRd (kNm)": round(r.mrd_knm, 2),
                "λ": round(r.slenderness, 1),
                "U. Axial": round(r.axial_utilization, 2),
                "U. Corte": round(r.shear_utilization, 2),
                "U. Flex.": round(r.bending_utilization, 2),
                "Encurv.": "OK" if r.buckling_ok else "⚠️ VERIFICAR",
            })
        df_walls = pd.DataFrame(rows)
        st.dataframe(
            style_df(df_walls, ["U. Axial", "U. Corte", "U. Flex."]),
            use_container_width=True, hide_index=True,
        )
        st.caption("As,v mín. (cm²) | As,h mín. (cm²/m)")
        reinf_rows = [
            {"ID": w.id,
             "As,v req. (cm²)": round(w.result.required_as_v_cm2, 2),
             "As,h req. (cm²/m)": round(w.result.required_as_h_cm2_m, 2)}
            for w in p.walls
        ]
        st.dataframe(pd.DataFrame(reinf_rows), use_container_width=True, hide_index=True)

# ── Muros de betão ───────────────────────────────────────────────────────────
with tab_muros:
    rws = getattr(p, 'retaining_walls', [])
    cfs = getattr(p, 'continuous_footings', [])
    if not rws:
        st.info("Sem muros de betão no projeto. Adiciona na barra lateral.")
    else:
        st.subheader("Muros de suporte em consola")
        rows = []
        for w in rws:
            r = w.result
            rows.append({
                "ID": w.id,
                "H ret. (m)": round(w.height_m, 2),
                "e topo (cm)": round(w.stem_thickness_cm, 0),
                "Largura base (m)": round(w.base_width_m, 2),
                "Fh (kN/m)": round(r.earth_pressure_kn_m, 1) if r else "-",
                "SF Desliz.": round(r.sliding_safety, 2) if r else "-",
                "SF Derrub.": round(r.overturning_safety, 2) if r else "-",
                "σ solo (kPa)": round(r.bearing_stress_mpa*1000, 1) if r else "-",
                "U. Solo": round(r.bearing_utilization, 2) if r else "-",
                "As haste (cm²/m)": round(r.required_as_stem_cm2_m, 2) if r else "-",
                "As calcan. (cm²/m)": round(r.required_as_heel_cm2_m, 2) if r else "-",
                "Estado": ("✓ OK" if r and r.sliding_ok and r.overturning_ok and r.bearing_ok
                           else "⚠️ VERIFICAR"),
            })
        df_rw = pd.DataFrame(rows)
        st.dataframe(style_df(df_rw, ["U. Solo"]), use_container_width=True, hide_index=True)
        st.caption("SF Deslizamento ≥ 1.5 | SF Derrubamento ≥ 2.0 | σ ≤ σ_adm")

    if cfs:
        st.subheader("Sapatas corridas")
        rows2 = []
        for cf in cfs:
            r = cf.result
            rows2.append({
                "ID": cf.id,
                "Muro": cf.related_wall_id,
                "Largura (cm)": round(cf.width_cm, 0),
                "Altura (cm)": round(cf.height_cm, 0),
                "Comp. (m)": round(cf.length_m, 1),
                "σ solo (kPa)": round(r.soil_stress_mpa*1000, 1) if r else "-",
                "U. Solo": round(r.soil_utilization, 2) if r else "-",
                "MEd (kNm/m)": round(r.med_knm_m, 2) if r else "-",
                "MRd (kNm/m)": round(r.mrd_knm_m, 2) if r else "-",
                "U. Flex.": round(r.bending_utilization, 2) if r else "-",
                "As req. (cm²/m)": round(r.required_as_cm2_m, 2) if r else "-",
            })
        df_cf = pd.DataFrame(rows2)
        st.dataframe(style_df(df_cf, ["U. Solo", "U. Flex."]), use_container_width=True, hide_index=True)

# ── Lajes fungiformes ─────────────────────────────────────────────────────────
with tab_fungi:
    if not p.flat_slabs:
        st.info("Sem lajes fungiformes no projeto. Adiciona na barra lateral.")
    else:
        rows = []
        for fs in p.flat_slabs:
            r = fs.result
            rows.append({
                "ID": fs.id,
                "Lx (m)": round(fs.lx_m, 2),
                "Ly (m)": round(fs.ly_m, 2),
                "h (cm)": round(fs.thickness_cm, 1),
                "Tipo": fs.panel_type,
                "gk (kN/m²)": round(fs.gk_kn_m2, 2),
                "qk (kN/m²)": round(fs.qk_kn_m2, 2),
                "MEd col. (kNm/m)": round(r.med_column_strip_knm_m, 2),
                "MRd col. (kNm/m)": round(r.mrd_column_strip_knm_m, 2),
                "U. Flex.": round(r.bending_utilization, 2),
                "VEd pun. (kN)": round(r.punching_ved_kn, 2),
                "VRd pun. (kN)": round(r.punching_vrd_kn, 2),
                "U. Punç.": round(r.punching_utilization, 2),
                "U. Flecha": round(r.deflection_utilization, 2),
                "As col. (cm²/m)": round(r.required_as_col_cm2_m, 2),
                "As mid. (cm²/m)": round(r.required_as_mid_cm2_m, 2),
            })
        df_fs = pd.DataFrame(rows)
        st.dataframe(
            style_df(df_fs, ["U. Flex.", "U. Punç.", "U. Flecha"]),
            use_container_width=True, hide_index=True,
        )

# ── Escadas ───────────────────────────────────────────────────────────────────
with tab_esc:
    if not p.stairs:
        st.info("Sem escadas no projeto. Adiciona na barra lateral.")
    else:
        rows = []
        for ss in p.stairs:
            r = ss.result
            rows.append({
                "ID": ss.id,
                "Lh (m)": round(ss.span_h_m, 2),
                "Hv (m)": round(ss.rise_m, 2),
                "α (°)": round(r.inclination_deg, 1),
                "h (cm)": round(ss.thickness_cm, 1),
                "qd (kN/m²)": round(r.sd_uls_kn_m2, 2),
                "MEd (kNm/m)": round(r.msd_knm_m, 2),
                "MRd (kNm/m)": round(r.mrd_knm_m, 2),
                "U. Flex.": round(r.bending_utilization, 2),
                "U. Corte": round(r.shear_utilization, 2),
                "U. Flecha": round(r.deflection_utilization, 2),
                "As req. (cm²/m)": round(r.required_as_cm2_m, 2),
            })
        df_stairs = pd.DataFrame(rows)
        st.dataframe(
            style_df(df_stairs, ["U. Flex.", "U. Corte", "U. Flecha"]),
            use_container_width=True, hide_index=True,
        )
        st.caption("Limite de flecha: L/350 (EC2 §7.4 — elementos susceptíveis a danos).")

# ── Alertas ───────────────────────────────────────────────────────────────────
with tab_alertas:
    warnings = [a for a in p.alerts if a.level == "warning"]
    criticals = [a for a in p.alerts if a.level in ("critical", "error")]
    infos = [a for a in p.alerts if a.level == "info"]

    if not p.alerts:
        st.success("Sem alertas.")

    if criticals:
        st.subheader(f"🚨 Críticos ({len(criticals)})")
        for a in criticals:
            st.error(a.message)

    if warnings:
        st.subheader(f"⚠️ Avisos ({len(warnings)})")
        for a in warnings:
            st.warning(a.message)

    if infos:
        with st.expander(f"ℹ️ Informativos ({len(infos)})"):
            for a in infos:
                st.info(a.message)

    if p.advice_messages:
        with st.expander("🧠 Modo Engenheiro"):
            for m in p.advice_messages:
                st.write(m)

# ── Planta ────────────────────────────────────────────────────────────────────
with tab_planta:
    if st.session_state.png_bytes:
        st.image(
            st.session_state.png_bytes,
            caption=f"Planta estrutural — {p.name}",
            use_container_width=True,
        )
    else:
        st.info("Planta não disponível.")
