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

from core.model import Column, ContinuousFooting, FlatSlab, Project, RetainingWall, ShearWall, StairSlab
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


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏗️ Raptor")
    st.caption("Análise estrutural EC2 — MVP")
    st.divider()

    # ── Abrir / Guardar projecto ──────────────────────────────────────────────
    st.markdown("### 📁 Projecto")
    raptor_upload = st.file_uploader("Abrir projecto (.raptor)", type=["raptor", "json"],
                                     key="raptor_upload")
    if raptor_upload is not None:
        try:
            from core.persistence import load_project as _load_proj
            _loaded = _load_proj(raptor_upload.read())
            st.session_state.project = _loaded
            st.session_state.drawings_ready = False
            st.success(f"Projecto '{_loaded.name}' carregado.")
        except Exception as _le:
            st.error(f"Erro ao abrir projecto: {_le}")

    if st.session_state.get("project"):
        from core.persistence import save_project as _save_proj
        _proj_bytes = _save_proj(st.session_state.project)
        _safe_name  = st.session_state.project.name.replace(" ", "_").replace("/", "-")
        st.download_button(
            "💾  Guardar projecto",
            data=_proj_bytes,
            file_name=f"{_safe_name}.raptor",
            mime="application/json",
            use_container_width=True,
        )
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
        with st.form("form_wall", clear_on_submit=True):
            wc1, wc2 = st.columns(2)
            w_id  = wc1.text_input("ID", "W1")
            w_len = wc1.number_input("Comprimento (m)", value=3.0, min_value=0.5, step=0.5)
            w_thk = wc1.number_input("Espessura (cm)", value=20, min_value=10, step=5)
            w_h   = wc1.number_input("Altura (m)", value=3.0, min_value=1.0, step=0.5)
            w_ned = wc2.number_input("NEd (kN)", value=500.0, min_value=0.0, step=50.0)
            w_ved = wc2.number_input("VEd horizontal (kN)", value=50.0, min_value=0.0, step=10.0)
            w_med = wc2.number_input("MEd base (kNm)", value=150.0, min_value=0.0, step=10.0)
            if st.form_submit_button("➕ Adicionar parede"):
                st.session_state.manual_walls.append(
                    ShearWall(w_id, 0.0, 0.0, w_len, w_thk, w_h, w_ned, w_ved, w_med))
                st.rerun()
        if st.session_state.manual_walls:
            for i, ww in enumerate(st.session_state.manual_walls):
                st.caption(f"{ww.id}: L={ww.length_m}m  e={ww.thickness_cm}cm  "
                           f"N={ww.ned_kn}kN  V={ww.ved_kn}kN")
            if st.button("🗑 Limpar paredes"):
                st.session_state.manual_walls = []
                st.rerun()

    # ── Flat slabs ───────────────────────────────────────────────────────────
    with st.expander(f"⚪ Lajes fungiformes ({len(st.session_state.manual_flat_slabs)})"):
        with st.form("form_fs", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            fs_id   = fc1.text_input("ID", "LF1")
            fs_lx   = fc1.number_input("Lx — vão curto (m)", value=5.0, min_value=1.0, step=0.5)
            fs_ly   = fc1.number_input("Ly — vão longo (m)", value=6.0, min_value=1.0, step=0.5)
            fs_thk  = fc1.number_input("Espessura (cm)", value=22, min_value=12, step=2)
            fs_gk   = fc2.number_input("gk (kN/m²)", value=5.0, min_value=0.0, step=0.5)
            fs_qk   = fc2.number_input("qk (kN/m²)", value=3.0, min_value=0.0, step=0.5)
            fs_cw   = fc2.number_input("Lado pilar (cm)", value=30, min_value=15, step=5)
            fs_type = fc2.selectbox("Tipo painel", ["interior", "edge", "corner"])
            if st.form_submit_button("➕ Adicionar laje fungiforme"):
                d_cm = fs_thk - 3.0
                st.session_state.manual_flat_slabs.append(
                    FlatSlab(fs_id, fs_lx, fs_ly, fs_thk, d_cm, fs_gk, fs_qk,
                             fs_cw, fs_type))
                st.rerun()
        if st.session_state.manual_flat_slabs:
            for fs in st.session_state.manual_flat_slabs:
                st.caption(f"{fs.id}: {fs.lx_m}×{fs.ly_m}m  h={fs.thickness_cm}cm  "
                           f"gk={fs.gk_kn_m2} qk={fs.qk_kn_m2} kN/m²")
            if st.button("🗑 Limpar lajes fungiformes"):
                st.session_state.manual_flat_slabs = []
                st.rerun()

    # ── Stairs ───────────────────────────────────────────────────────────────
    with st.expander(f"🪜 Escadas ({len(st.session_state.manual_stairs)})"):
        with st.form("form_stair", clear_on_submit=True):
            sc1, sc2 = st.columns(2)
            st_id  = sc1.text_input("ID", "E1")
            st_lh  = sc1.number_input("Projecção horiz. (m)", value=3.5, min_value=0.5, step=0.25)
            st_hv  = sc1.number_input("Altura total (m)", value=1.5, min_value=0.2, step=0.1)
            st_w   = sc1.number_input("Largura (m)", value=1.2, min_value=0.5, step=0.1)
            st_thk = sc2.number_input("Espessura laje (cm)", value=14, min_value=8, step=1)
            st_gk  = sc2.number_input("gk acabamentos (kN/m²)", value=1.5, min_value=0.0, step=0.5)
            st_qk  = sc2.number_input("qk (kN/m²)", value=3.0, min_value=0.0, step=0.5)
            if st.form_submit_button("➕ Adicionar escada"):
                d_cm = st_thk - 2.0
                st.session_state.manual_stairs.append(
                    StairSlab(st_id, st_lh, st_hv, st_w, st_thk, d_cm, st_gk, st_qk))
                st.rerun()
        if st.session_state.manual_stairs:
            for ss in st.session_state.manual_stairs:
                st.caption(f"{ss.id}: Lh={ss.span_h_m}m  Hv={ss.rise_m}m  "
                           f"h={ss.thickness_cm}cm")
            if st.button("🗑 Limpar escadas"):
                st.session_state.manual_stairs = []
                st.rerun()

    # ── Muros de betão de suporte ────────────────────────────────────────────
    with st.expander(f"🧱 Muros de betão ({len(st.session_state.manual_retaining_walls)})"):
        with st.form("form_rw", clear_on_submit=True):
            rw1, rw2 = st.columns(2)
            rw_id   = rw1.text_input("ID", "M1")
            rw_h    = rw1.number_input("Altura ret. (m)", value=2.5, min_value=0.5, step=0.25)
            rw_st   = rw1.number_input("Espessura topo (cm)", value=25, min_value=15, step=5)
            rw_bw   = rw1.number_input("Largura base (m)", value=1.5, min_value=0.5, step=0.1)
            rw_ht   = rw1.number_input("Esp. base (cm)", value=30, min_value=20, step=5)
            rw_heel = rw2.number_input("Calcanhar (m)", value=0.80, min_value=0.1, step=0.1)
            rw_toe  = rw2.number_input("Ponta (m)", value=0.45, min_value=0.1, step=0.05)
            rw_gam  = rw2.number_input("γ solo (kN/m³)", value=18.0, min_value=14.0, step=1.0)
            rw_phi  = rw2.number_input("φ (°)", value=30, min_value=15, max_value=45, step=1)
            rw_q    = rw2.number_input("Sobrecarga solo (kN/m²)", value=5.0, min_value=0.0, step=1.0)
            if st.form_submit_button("➕ Adicionar muro"):
                st.session_state.manual_retaining_walls.append(
                    RetainingWall(rw_id, rw_h, rw_st, rw_bw, rw_ht, rw_heel, rw_toe,
                                  rw_gam, float(rw_phi), rw_q))
                st.rerun()
        if st.session_state.manual_retaining_walls:
            for rw in st.session_state.manual_retaining_walls:
                st.caption(f"{rw.id}: H={rw.height_m}m  e={rw.stem_thickness_cm}cm  "
                           f"B={rw.base_width_m}m  φ={rw.phi_deg}°")
            if st.button("🗑 Limpar muros"):
                st.session_state.manual_retaining_walls = []
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
    run_btn = st.button("▶  Correr cálculo", type="primary", use_container_width=True)

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
                                               draw_retaining_wall_schedule_dxf)
                _p = st.session_state.project
                if not st.session_state.get("drawings_ready"):
                    with st.spinner("A gerar desenhos DXF…"):
                        st.session_state["dxf_vigas"]      = draw_beam_schedule_dxf(_p)
                        st.session_state["dxf_fundacoes"]  = draw_foundation_plan_dxf(_p)
                        st.session_state["dxf_piso"]       = draw_slab_plan_dxf(_p, "PLANTA DA LAJE DE PISO")
                        st.session_state["dxf_cobertura"]  = draw_slab_plan_dxf(_p, "PLANTA DA LAJE DE COBERTURA")
                        st.session_state["dxf_pilares"]    = draw_column_schedule_dxf(_p)
                        st.session_state["dxf_sapatas"]    = draw_footing_schedule_dxf(_p)
                        st.session_state["dxf_lajes"]      = draw_slab_schedule_dxf(_p)
                        st.session_state["dxf_muros"]      = draw_retaining_wall_schedule_dxf(_p)
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
                if st.session_state.get("predim_cols") and not col_path:
                    columns = st.session_state["predim_cols"]
                elif col_path:
                    columns = CSVGeometryImporter().load_columns(col_path)
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
tab_res, tab_vigas, tab_pilares, tab_lajes, tab_sapatas, tab_paredes, tab_muros, tab_fungi, tab_esc, tab_alertas, tab_planta = st.tabs([
    "📊 Resumo",
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

# ── Resumo ────────────────────────────────────────────────────────────────────
with tab_res:
    mc = st.columns(9)
    mc[0].metric("Pilares", len(p.columns))
    mc[1].metric("Vigas", len(p.beams))
    mc[2].metric("Lajes", len(p.slabs))
    mc[3].metric("Sapatas", len(p.footings))
    mc[4].metric("V. Amarração", len(p.tie_beams))
    mc[5].metric("Paredes", len(p.walls))
    mc[6].metric("Muros", len(getattr(p, 'retaining_walls', [])))
    mc[7].metric("L. Fungi.", len(p.flat_slabs))
    mc[8].metric("Escadas", len(p.stairs))

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

    _beam_type_labels = {"frame": "Pórtico", "lintel": "Lintel/Estore", "vct": "VCT"}
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
