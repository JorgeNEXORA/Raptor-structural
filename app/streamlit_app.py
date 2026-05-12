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

from core.model import Column, FlatSlab, Project, ShearWall, StairSlab
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
    page_title="Structural AI",
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


def style_df(df: pd.DataFrame, util_cols: list) -> pd.io.formats.style.Styler:
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
    st.markdown("## 🏗️ Structural AI")
    st.caption("Análise estrutural EC2 — MVP")
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
                columns = (
                    CSVGeometryImporter().load_columns(col_path)
                    if col_path
                    else build_demo_columns()
                )
                beams = CSVBeamImporter().load_beams(beam_path, columns) if beam_path else []
                slabs = CSVSlabImporter().load_slabs(slab_path) if slab_path else []

            slab_loads_path = save_upload(slab_loads_csv)
            slab_loads = (
                CSVSlabLoadImporter().load_slab_loads(slab_loads_path)
                if slab_loads_path
                else None
            )

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
                fck_mpa=fck_mpa,
                fyk_mpa=fyk_mpa,
            )
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
st.title("🏗️ Structural AI — Análise Estrutural")

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
scores = getattr(p, "project_scores", {})

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
tab_res, tab_vigas, tab_pilares, tab_lajes, tab_sapatas, tab_paredes, tab_fungi, tab_esc, tab_alertas, tab_planta = st.tabs([
    "📊 Resumo",
    "🔩 Vigas",
    "🏛️ Pilares",
    "⬜ Lajes",
    "⬛ Sapatas",
    "🧱 Paredes",
    "⚪ L. Fungiforme",
    "🪜 Escadas",
    "⚠️ Alertas",
    "🗺️ Planta",
])

# ── Resumo ────────────────────────────────────────────────────────────────────
with tab_res:
    mc = st.columns(8)
    mc[0].metric("Pilares", len(p.columns))
    mc[1].metric("Vigas", len(p.beams))
    mc[2].metric("Lajes", len(p.slabs))
    mc[3].metric("Sapatas", len(p.footings))
    mc[4].metric("V. Amarração", len(p.tie_beams))
    mc[5].metric("Paredes", len(p.walls))
    mc[6].metric("L. Fungi.", len(p.flat_slabs))
    mc[7].metric("Escadas", len(p.stairs))

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
    rows = []
    for b in p.beams:
        r = b.result
        rr = b.reinforcement_result or {}
        rows.append({
            "ID": b.id,
            "Nós": f"{b.start_node}→{b.end_node}",
            "b×h (cm)": f"{int(b.width_cm)}×{int(b.height_cm)}",
            "Span (m)": round(b.span_m, 2),
            "Msd (kNm)": round(r.msd_knm, 2),
            "Vsd (kN)": round(r.vsd_kn, 2),
            "As req (cm²)": round(r.required_as_cm2, 2),
            "Armadura": rr.get("bottom_text", "-"),
            "Estribos": rr.get("stirrups_text", "-"),
            "U. Corte": round(r.shear_utilization, 2),
            "U. Flecha": round(r.deflection_utilization, 2),
            "U. Fissura": round(r.crack_utilization, 2),
        })
    df_beams = pd.DataFrame(rows)
    st.dataframe(
        style_df(df_beams, ["U. Corte", "U. Flecha", "U. Fissura"]),
        use_container_width=True, hide_index=True,
    )

# ── Pilares ───────────────────────────────────────────────────────────────────
with tab_pilares:
    rows = []
    for c in p.columns:
        r = c.result
        rows.append({
            "ID": c.id,
            "x (m)": round(c.x, 2),
            "y (m)": round(c.y, 2),
            "b×h (cm)": f"{int(c.width_cm)}×{int(c.depth_cm)}",
            "h (m)": round(c.height_m, 2),
            "Nsd (kN)": round(r.nsd_kn, 2),
            "Nrd (kN)": round(r.nrd_kn, 2),
            "As req (cm²)": round(r.required_as_cm2, 2),
            "As adot (cm²)": round(r.adopted_as_cm2, 2),
            "Esbelteza": round(r.slenderness, 1),
            "Utilização": round(r.utilization, 2),
        })
    df_cols = pd.DataFrame(rows)
    st.dataframe(
        style_df(df_cols, ["Utilização"]),
        use_container_width=True, hide_index=True,
    )

# ── Lajes ─────────────────────────────────────────────────────────────────────
with tab_lajes:
    rows = []
    for s in p.slabs:
        r = s.result
        rows.append({
            "ID": s.id,
            "Span (m)": round(s.span_m, 2),
            "h (cm)": round(s.thickness_cm, 1),
            "Tipo": s.slab_type.value if s.slab_type else "-",
            "Dir": s.direction or "-",
            "Gk (kN/m²)": round(s.gk_kn_m2, 2),
            "Qk (kN/m²)": round(s.qk_kn_m2, 2),
            "Msd (kNm/m)": round(r.msd_knm_m, 2),
            "U. Flecha": round(r.deflection_utilization, 2),
            "U. Fissura": round(r.crack_utilization, 2),
        })
    df_slabs = pd.DataFrame(rows)
    st.dataframe(
        style_df(df_slabs, ["U. Flecha", "U. Fissura"]),
        use_container_width=True, hide_index=True,
    )

# ── Sapatas ───────────────────────────────────────────────────────────────────
with tab_sapatas:
    rows = []
    for f in p.footings:
        r = f.result
        rows.append({
            "ID": f.id,
            "Tipo": f.footing_type.value,
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
