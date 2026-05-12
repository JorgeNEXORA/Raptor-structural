import os, sys
sys.path.insert(0, os.path.abspath("."))

from core.model import Project
from analysis.dxf_import import SimpleDXFImporter
from pipeline.auto_pipeline import AutoPipeline
from analysis.advisor import ProjectAdvisor
from analysis.optimizer import AutoOptimizer

dxf = os.path.join("inputs", "modelo_base.dxf")
imp = SimpleDXFImporter()
cols = imp.import_columns(dxf)
beams = imp.import_beams(dxf, cols)
slabs = imp.import_slabs(dxf)
p = Project("T", "L", 0.2, columns=cols, beams=beams, slabs=slabs)
AutoPipeline().run(p)

adv = ProjectAdvisor()
print("scores_before", adv.project_score(p))
print("advice_count_before", len(adv.generate_advice(p)))

changes = AutoOptimizer().optimize(p)
print("changes", changes[:5])

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
p.tie_beams = []
p.alerts = []
p.advice_messages = []

AutoPipeline().run(p)
print("scores_after", adv.project_score(p))
print("advice_count_after", len(adv.generate_advice(p)))
