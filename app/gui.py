import os
import sys
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.model import Column, Project
from pipeline.auto_pipeline import AutoPipeline
from analysis.visualization import PlanVisualizer
from analysis.importers import CSVGeometryImporter, CSVBeamImporter, CSVSlabImporter, CSVSlabLoadImporter
from analysis.dxf_export import DXFExporter
from analysis.dxf_import import SimpleDXFImporter
from analysis.report_export import ReportExporter
from analysis.advisor import ProjectAdvisor
from analysis.optimizer import AutoOptimizer
from analysis.history import store_snapshot, build_comparison_text

class StructuralAIGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Structural AI - MVP")
        self.root.geometry("1020x760")
        self.input_mode = tk.StringVar(value="csv")
        self.dxf_path = tk.StringVar(value=os.path.join(ROOT_DIR, "inputs", "modelo_base.dxf"))
        self.columns_csv = tk.StringVar(value=os.path.join(ROOT_DIR, "inputs", "columns_sample.csv"))
        self.beams_csv = tk.StringVar(value=os.path.join(ROOT_DIR, "inputs", "beams_sample.csv"))
        self.slabs_csv = tk.StringVar(value=os.path.join(ROOT_DIR, "inputs", "slabs_sample.csv"))
        self.slab_loads_csv = tk.StringVar(value=os.path.join(ROOT_DIR, "inputs", "slab_loads_sample.csv"))
        self.soil_mpa = tk.StringVar(value="0.20")
        self.fck_mpa = tk.StringVar(value="25")
        self.fyk_mpa = tk.StringVar(value="500")
        self.project_name = tk.StringVar(value="Projeto Estrutural")
        self.location = tk.StringVar(value="Barcelos")
        self.last_project = None
        self._build_ui()

    def _build_ui(self):
        mode = ttk.LabelFrame(self.root, text="Modo de entrada", padding=10)
        mode.pack(fill="x", padx=12, pady=8)
        ttk.Radiobutton(mode, text="CSV", value="csv", variable=self.input_mode).grid(row=0, column=0, padx=4, pady=4, sticky="w")
        ttk.Radiobutton(mode, text="DXF", value="dxf", variable=self.input_mode).grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ttk.Label(mode, text="DXF").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(mode, textvariable=self.dxf_path, width=90).grid(row=1, column=1, sticky="we", padx=4, pady=4)
        ttk.Button(mode, text="...", width=4, command=lambda: self.browse_file(self.dxf_path, dxf=True)).grid(row=1, column=2, padx=4, pady=4)

        top = ttk.LabelFrame(self.root, text="Ficheiros CSV", padding=10)
        top.pack(fill="x", padx=12, pady=8)
        self._path_row(top, "CSV Pilares", self.columns_csv, 0)
        self._path_row(top, "CSV Vigas", self.beams_csv, 1)
        self._path_row(top, "CSV Lajes", self.slabs_csv, 2)
        self._path_row(top, "CSV Cargas Lajes", self.slab_loads_csv, 3)

        cfg = ttk.LabelFrame(self.root, text="Configuração", padding=12)
        cfg.pack(fill="x", padx=12, pady=8)
        ttk.Label(cfg, text="Nome do projeto").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(cfg, textvariable=self.project_name, width=30).grid(row=0, column=1, sticky="we", padx=4, pady=4)
        ttk.Label(cfg, text="Local").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(cfg, textvariable=self.location, width=20).grid(row=0, column=3, sticky="we", padx=4, pady=4)
        ttk.Label(cfg, text="Tensão admissível do solo (MPa)").grid(row=0, column=4, sticky="w", padx=4, pady=4)
        ttk.Entry(cfg, textvariable=self.soil_mpa, width=10).grid(row=0, column=5, sticky="w", padx=4, pady=4)
        ttk.Label(cfg, text="Betão fck (MPa)").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(cfg, textvariable=self.fck_mpa, width=10,
                     values=["16","20","25","30","35","40","45","50"],
                     state="readonly").grid(row=1, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(cfg, text="Aço fyk (MPa)").grid(row=1, column=2, sticky="w", padx=4, pady=4)
        ttk.Combobox(cfg, textvariable=self.fyk_mpa, width=10,
                     values=["400","500","600"],
                     state="readonly").grid(row=1, column=3, sticky="w", padx=4, pady=4)

        btns = ttk.Frame(self.root, padding=(12, 4))
        btns.pack(fill="x")
        ttk.Button(btns, text="Correr cálculo", command=self.run_pipeline).pack(side="left", padx=4)
        ttk.Button(btns, text="Otimizar projeto", command=self.optimize_project).pack(side="left", padx=4)
        ttk.Button(btns, text="Gerar relatório DOCX", command=self.export_report).pack(side="left", padx=4)
        ttk.Button(btns, text="Abrir pasta outputs", command=self.open_outputs).pack(side="left", padx=4)
        ttk.Button(btns, text="Limpar", command=self.clear_output).pack(side="left", padx=4)

        out = ttk.LabelFrame(self.root, text="Saída", padding=8)
        out.pack(fill="both", expand=True, padx=12, pady=8)
        self.text = tk.Text(out, wrap="word", font=("Consolas", 10))
        self.text.pack(fill="both", expand=True)

    def _path_row(self, parent, label, variable, row):
        ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(parent, textvariable=variable, width=90).grid(row=row, column=1, sticky="we", padx=4, pady=4)
        ttk.Button(parent, text="...", width=4, command=lambda v=variable: self.browse_file(v, dxf=False)).grid(row=row, column=2, padx=4, pady=4)

    def browse_file(self, variable, dxf=False):
        filetypes = [("DXF files", "*.dxf"), ("All files", "*.*")] if dxf else [("CSV files", "*.csv"), ("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            variable.set(path)

    def append(self, text=""):
        self.text.insert("end", text + "\n")
        self.text.see("end")
        self.root.update_idletasks()

    def clear_output(self):
        self.text.delete("1.0", "end")

    def open_outputs(self):
        output_dir = os.path.join(ROOT_DIR, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        try:
            os.startfile(output_dir)
        except Exception:
            messagebox.showinfo("Outputs", output_dir)

    def build_demo_columns(self):
        return [
            Column("P1",0.0,0.0,25,25,3.0), Column("P2",4.0,0.0,25,25,3.0), Column("P3",8.0,0.0,25,25,3.0),
            Column("P4",0.0,4.5,25,25,3.0), Column("P5",4.0,4.5,25,25,3.0), Column("P6",8.0,4.5,25,25,3.0),
        ]

    def load_from_csv(self):
        columns_path = self.columns_csv.get().strip()
        columns = CSVGeometryImporter().load_columns(columns_path) if columns_path and os.path.exists(columns_path) else self.build_demo_columns()
        self.append(f"Geometria carregada do CSV: {columns_path}" if columns_path and os.path.exists(columns_path) else "CSV de pilares não encontrado, a usar geometria demo.")
        beams_path = self.beams_csv.get().strip()
        beams = CSVBeamImporter().load_beams(beams_path, columns) if beams_path and os.path.exists(beams_path) else []
        self.append(f"Vigas carregadas do CSV: {beams_path}" if beams_path and os.path.exists(beams_path) else "CSV de vigas não encontrado, a usar geração automática.")
        slabs_path = self.slabs_csv.get().strip()
        slabs = CSVSlabImporter().load_slabs(slabs_path) if slabs_path and os.path.exists(slabs_path) else []
        self.append(f"Lajes carregadas do CSV: {slabs_path}" if slabs_path and os.path.exists(slabs_path) else "CSV de lajes não encontrado, a usar geração automática.")
        slab_loads_path = self.slab_loads_csv.get().strip()
        slab_loads = CSVSlabLoadImporter().load_slab_loads(slab_loads_path) if slab_loads_path and os.path.exists(slab_loads_path) else None
        self.append(f"Cargas de laje carregadas do CSV: {slab_loads_path}" if slab_loads_path and os.path.exists(slab_loads_path) else "CSV de cargas de laje não encontrado.")
        return columns, beams, slabs, slab_loads

    def load_from_dxf(self):
        dxf_path = self.dxf_path.get().strip()
        if not dxf_path or not os.path.exists(dxf_path):
            raise FileNotFoundError("DXF não encontrado.")
        self.append(f"Geometria carregada do DXF: {dxf_path}")
        importer = SimpleDXFImporter()
        columns = importer.import_columns(dxf_path)
        if not columns:
            raise ValueError("O DXF não contém círculos na layer PILARES.")
        beams = importer.import_beams(dxf_path, columns)
        slabs = importer.import_slabs(dxf_path)
        self.append(f"Pilares importados do DXF: {len(columns)}")
        self.append(f"Vigas importadas do DXF: {len(beams)}")
        self.append(f"Lajes importadas do DXF: {len(slabs)}")
        slab_loads_path = self.slab_loads_csv.get().strip()
        slab_loads = CSVSlabLoadImporter().load_slab_loads(slab_loads_path) if slab_loads_path and os.path.exists(slab_loads_path) else None
        self.append(f"Cargas de laje carregadas do CSV: {slab_loads_path}" if slab_loads_path and os.path.exists(slab_loads_path) else "CSV de cargas de laje não encontrado.")
        return columns, beams, slabs, slab_loads

    def run_pipeline(self):
        self.clear_output()
        try:
            columns, beams, slabs, slab_loads = self.load_from_dxf() if self.input_mode.get() == "dxf" else self.load_from_csv()
            project = Project(
                name=self.project_name.get().strip() or "Projeto Estrutural",
                location=self.location.get().strip() or "Local",
                soil_allowable_mpa=float(self.soil_mpa.get().replace(",", ".")),
                columns=columns,
                beams=beams,
                slabs=slabs,
                fck_mpa=float(self.fck_mpa.get()),
                fyk_mpa=float(self.fyk_mpa.get()),
            )
            AutoPipeline().run(project, slab_loads=slab_loads)
            self.last_project = project
            output_dir = os.path.join(ROOT_DIR, "outputs")
            os.makedirs(output_dir, exist_ok=True)
            png_path = PlanVisualizer().draw_project_plan(project, os.path.join(output_dir, "planta_estrutura.png"))
            dxf_path = DXFExporter().export_project(project, os.path.join(output_dir, "planta_estrutura.dxf"))
            self.append("")
            self.append("=== RESUMO ===")
            self.append(f"Pilares: {len(project.columns)}")
            self.append(f"Vigas: {len(project.beams)}")
            self.append(f"Lajes: {len(project.slabs)}")
            self.append(f"Sapatas: {len(project.footings)}")
            self.append(f"Vigas de amarração: {len(project.tie_beams)}")
            self.append(f"Planta PNG: {png_path}")
            self.append(f"Planta DXF: {dxf_path}")
            self.append("")
            self.append("=== LAJES ===")
            for s in project.slabs:
                area = f"{s.area_m2:.2f}" if s.area_m2 is not None else "-"
                self.append(f"{s.id}: span={s.span_m:.2f} m | área={area} m² | dir={s.direction or '-'} | apoios={','.join(s.support_beam_ids) if s.support_beam_ids else '-'} | Gk={s.gk_kn_m2:.2f} | Qk={s.qk_kn_m2:.2f}")
            self.append("")
            self.append("=== VIGAS ===")
            for b in project.beams:
                self.append(f"{b.id}: Msd={b.result.msd_knm:.2f} | Vsd={b.result.vsd_kn:.2f} | Vrd={b.result.vrd_kn:.2f} | corte={b.result.shear_utilization:.2f} | flecha={b.result.deflection_final_mm:.1f}/{b.result.deflection_limit_mm:.1f} mm ({b.result.deflection_utilization:.2f}) | fiss={b.result.crack_width_mm:.3f}/{b.result.crack_limit_mm:.3f} mm ({b.result.crack_utilization:.2f})")
            self.append("")
            self.append("=== SAPATAS ===")
            for f in project.footings:
                self.append(f"{f.id}: σmin={f.result.sigma_min_mpa:.3f} | σmax={f.result.sigma_max_mpa:.3f} MPa | solo={f.result.soil_utilization:.2f} | punçoamento={f.result.punching_utilization:.2f} | uplift={f.result.uplift_detected} | viga_eq={f.result.needs_balance_beam}")
            self.append("")
            self.append("=== VIGAS DE EQUILÍBRIO ===")
            for t in project.tie_beams:
                self.append(f"{t.id}: {t.start_footing_id}->{t.end_footing_id} | vão={t.span_m:.2f} m | T={t.tie_force_kn:.2f} kN | As={t.required_as_cm2:.2f} cm² | adotar {t.adopted_bars}")
            advisor = ProjectAdvisor()
            scores = advisor.project_score(project)
            advisor.generate_advice(project)
            self.append("")
            self.append("=== SCORE GLOBAL ===")
            self.append(f"Segurança ULS: {scores['seguranca_uls']:.2f}")
            self.append(f"Serviço ELS: {scores['servico_els']:.2f}")
            self.append(f"Fundações: {scores['fundacoes']:.2f}")
            self.append("")
            self.append("=== MODO ENGENHEIRO ===")
            for msg in project.advice_messages:
                self.append(msg)
            if not self.last_project.history_snapshots:
                store_snapshot(self.last_project, "baseline")
            self.append("")
            self.append("=== ALERTAS ===")
            for a in project.alerts:
                self.append(f"[{a.level}] {a.message}")
            messagebox.showinfo("Concluído", "Cálculo concluído com sucesso.\nForam gerados PNG e DXF na pasta outputs.")
        except Exception as e:
            self.append("")
            self.append("=== ERRO ===")
            self.append(str(e))
            self.append("")
            self.append(traceback.format_exc())
            messagebox.showerror("Erro", str(e))


    def optimize_project(self):
        if self.last_project is None:
            messagebox.showwarning("Otimização", "Corre primeiro o cálculo.")
            return
        try:
            before_snapshot = store_snapshot(self.last_project, "antes_otimizacao")
            changes = AutoOptimizer().optimize(self.last_project)
            if not changes:
                messagebox.showinfo("Otimização", "Não foram necessárias alterações automáticas.")
                return

            from pipeline.auto_pipeline import AutoPipeline
            for c in self.last_project.columns:
                c.loads = []
                c.result = None
            for b in self.last_project.beams:
                b.line_loads = []
                b.supported_slab_ids = []
                b.result = None
                b.continuous_result = None
                b.reinforcement_result = None
            for s in self.last_project.slabs:
                s.support_beam_ids = []
                s.support_beam_contributions = {}
                s.result = None
            for f in self.last_project.footings:
                f.result = None
                f.reinforcement_result = None
            self.last_project.tie_beams = []
            self.last_project.alerts = []
            self.last_project.advice_messages = []

            AutoPipeline().run(self.last_project)

            output_dir = os.path.join(ROOT_DIR, "outputs")
            os.makedirs(output_dir, exist_ok=True)
            png_path = PlanVisualizer().draw_project_plan(self.last_project, os.path.join(output_dir, "planta_estrutura.png"))
            dxf_path = DXFExporter().export_project(self.last_project, os.path.join(output_dir, "planta_estrutura.dxf"))

            self.append("")
            self.append("=== OTIMIZAÇÃO AUTOMÁTICA ===")
            for c in changes:
                self.append(c)
            advisor = ProjectAdvisor()
            scores = advisor.project_score(self.last_project)
            advisor.generate_advice(self.last_project)
            after_snapshot = store_snapshot(self.last_project, "depois_otimizacao")
            comparison_lines = build_comparison_text(before_snapshot, after_snapshot)
            self.append(f"Novo score ULS: {scores['seguranca_uls']:.2f}")
            self.append(f"Novo score ELS: {scores['servico_els']:.2f}")
            self.append(f"Novo score Fundações: {scores['fundacoes']:.2f}")
            self.append(f"PNG atualizado: {png_path}")
            self.append(f"DXF atualizado: {dxf_path}")
            messagebox.showinfo("Otimização", "Projeto otimizado e recalculado com sucesso.")
        except Exception as e:
            self.append("")
            self.append("=== ERRO OTIMIZAÇÃO ===")
            self.append(str(e))
            messagebox.showerror("Erro otimização", str(e))

    def export_report(self):
        if self.last_project is None:
            messagebox.showwarning("Relatório", "Corre primeiro o cálculo.")
            return
        try:
            output_dir = os.path.join(ROOT_DIR, "outputs")
            os.makedirs(output_dir, exist_ok=True)
            docx_path = os.path.join(output_dir, "relatorio_estrutural.docx")
            ReportExporter().export_docx(self.last_project, docx_path)
            self.append("")
            self.append(f"Relatório DOCX gerado em: {docx_path}")
            messagebox.showinfo("Relatório", f"Relatório gerado com sucesso.\n{docx_path}")
        except Exception as e:
            self.append("")
            self.append("=== ERRO RELATÓRIO ===")
            self.append(str(e))
            messagebox.showerror("Erro relatório", str(e))

def main():
    root = tk.Tk()
    app = StructuralAIGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
