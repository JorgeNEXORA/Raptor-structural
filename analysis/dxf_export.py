class DXFExporter:
    def __init__(self):
        self.lines = []

    def _add(self, code, value):
        self.lines.append(str(code))
        self.lines.append(str(value))

    def _header(self):
        self._add(0, "SECTION")
        self._add(2, "HEADER")
        self._add(0, "ENDSEC")
        self._add(0, "SECTION")
        self._add(2, "TABLES")
        self._add(0, "ENDSEC")
        self._add(0, "SECTION")
        self._add(2, "ENTITIES")

    def _footer(self):
        self._add(0, "ENDSEC")
        self._add(0, "EOF")

    def add_line(self, x1, y1, x2, y2, layer="0"):
        self._add(0, "LINE")
        self._add(8, layer)
        self._add(10, x1)
        self._add(20, y1)
        self._add(30, 0.0)
        self._add(11, x2)
        self._add(21, y2)
        self._add(31, 0.0)

    def add_circle(self, x, y, r, layer="0"):
        self._add(0, "CIRCLE")
        self._add(8, layer)
        self._add(10, x)
        self._add(20, y)
        self._add(30, 0.0)
        self._add(40, r)

    def add_text(self, x, y, text, height=0.18, layer="0"):
        self._add(0, "TEXT")
        self._add(8, layer)
        self._add(10, x)
        self._add(20, y)
        self._add(30, 0.0)
        self._add(40, height)
        self._add(1, text)

    def add_rect(self, x, y, w, h, layer="0"):
        self.add_line(x, y, x + w, y, layer)
        self.add_line(x + w, y, x + w, y + h, layer)
        self.add_line(x + w, y + h, x, y + h, layer)
        self.add_line(x, y + h, x, y, layer)

    def export_project(self, project, output_path):
        self.lines = []
        self._header()

        # Vigas
        for beam in project.beams:
            c1 = next(c for c in project.columns if c.id == beam.start_node)
            c2 = next(c for c in project.columns if c.id == beam.end_node)
            self.add_line(c1.x, c1.y, c2.x, c2.y, layer="VIGAS")
            self.add_text((c1.x + c2.x) / 2.0, (c1.y + c2.y) / 2.0, beam.id, layer="TEXTOS")

        # Pilares
        for col in project.columns:
            self.add_circle(col.x, col.y, 0.10, layer="PILARES")
            self.add_text(col.x + 0.12, col.y + 0.12, col.id, layer="TEXTOS")

        # Sapatas
        for footing in project.footings:
            col = next(c for c in project.columns if c.id == footing.related_column_id)
            w = footing.width_a_cm / 100.0
            h = footing.width_b_cm / 100.0
            self.add_rect(col.x - w / 2.0, col.y - h / 2.0, w, h, layer="SAPATAS")
            self.add_text(col.x - 0.20, col.y - 0.35, footing.id, height=0.14, layer="TEXTOS")

        # Vigas de amarração
        for tie in getattr(project, "tie_beams", []):
            f1 = next(f for f in project.footings if f.id == tie.start_footing_id)
            f2 = next(f for f in project.footings if f.id == tie.end_footing_id)
            c1 = next(c for c in project.columns if c.id == f1.related_column_id)
            c2 = next(c for c in project.columns if c.id == f2.related_column_id)
            self.add_line(c1.x, c1.y, c2.x, c2.y, layer="AMARRACAO")
            self.add_text((c1.x + c2.x) / 2.0, (c1.y + c2.y) / 2.0 - 0.18, tie.id, height=0.14, layer="TEXTOS")

        self._footer()

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))

        return output_path
