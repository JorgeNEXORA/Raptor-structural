import os
import matplotlib.pyplot as plt

class PlanVisualizer:
    def draw_project_plan(self, project, output_path: str) -> str:
        fig, ax = plt.subplots(figsize=(9, 6))

        # vigas principais
        for beam in project.beams:
            c1 = next(c for c in project.columns if c.id == beam.start_node)
            c2 = next(c for c in project.columns if c.id == beam.end_node)
            ax.plot([c1.x, c2.x], [c1.y, c2.y], linewidth=2)
            mx = (c1.x + c2.x) / 2.0
            my = (c1.y + c2.y) / 2.0
            ax.text(mx, my, beam.id, fontsize=8)

        # pilares
        for col in project.columns:
            ax.scatter([col.x], [col.y], s=80)
            ax.text(col.x + 0.08, col.y + 0.08, col.id, fontsize=9)

        # sapatas
        for footing in project.footings:
            col_id = footing.related_column_id
            col = next(c for c in project.columns if c.id == col_id)
            w = footing.width_a_cm / 100.0
            h = footing.width_b_cm / 100.0
            rect_x = col.x - w / 2.0
            rect_y = col.y - h / 2.0
            ax.add_patch(plt.Rectangle((rect_x, rect_y), w, h, fill=False, linewidth=1))
            ax.text(col.x - 0.2, col.y - 0.35, footing.id, fontsize=7)

        # vigas de amarração/equilíbrio
        for tie in getattr(project, "tie_beams", []):
            f1 = next(f for f in project.footings if f.id == tie.start_footing_id)
            f2 = next(f for f in project.footings if f.id == tie.end_footing_id)
            c1 = next(c for c in project.columns if c.id == f1.related_column_id)
            c2 = next(c for c in project.columns if c.id == f2.related_column_id)
            ax.plot([c1.x, c2.x], [c1.y, c2.y], linestyle="--", linewidth=1.5)
            ax.text((c1.x + c2.x) / 2.0, (c1.y + c2.y) / 2.0 - 0.18, tie.id, fontsize=7)

        # contorno aproximado das lajes/painéis
        xs = sorted({c.x for c in project.columns})
        ys = sorted({c.y for c in project.columns})
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                ax.add_patch(plt.Rectangle((xs[i], ys[j]), xs[i+1] - xs[i], ys[j+1] - ys[j], fill=False, linewidth=0.8))

        ax.set_title(project.name)
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.set_aspect("equal")
        ax.grid(True)

        plt.tight_layout()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fig.savefig(output_path, dpi=200)
        plt.close(fig)
        return output_path
