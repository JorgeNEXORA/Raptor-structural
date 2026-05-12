import math
from core.model import Column, Beam, BeamType, SlabPanel, SlabType

class SimpleDXFImporter:
    """
    DXF ASCII simplificado.
    Layers:
    - PILARES: CIRCLE
    - VIGAS: LINE
    - LAJES: LWPOLYLINE fechada
    - LAJE_TEXTOS: TEXT
    """

    def read_pairs(self, dxf_path: str):
        with open(dxf_path, "r", encoding="utf-8", errors="ignore") as f:
            raw = [line.rstrip("\n\r") for line in f]
        pairs = []
        i = 0
        while i + 1 < len(raw):
            pairs.append((raw[i].strip(), raw[i + 1].strip()))
            i += 2
        return pairs

    def parse_entities(self, dxf_path: str):
        pairs = self.read_pairs(dxf_path)
        entities = []
        in_entities = False
        current = None
        for code, value in pairs:
            if code == "2" and value == "ENTITIES":
                in_entities = True
                continue
            if in_entities and code == "0" and value == "ENDSEC":
                in_entities = False
                if current and current.get("type") not in ("SECTION", None):
                    entities.append(current)
                current = None
                continue
            if not in_entities:
                continue
            if code == "0":
                if current and current.get("type") not in ("SECTION", None):
                    entities.append(current)
                current = {"type": value}
                continue
            if current is not None:
                if code in current:
                    if not isinstance(current[code], list):
                        current[code] = [current[code]]
                    current[code].append(value)
                else:
                    current[code] = value
        if current and current.get("type") not in ("SECTION", None):
            entities.append(current)
        return entities

    def _as_list(self, value):
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _polygon_area(self, pts):
        if len(pts) < 3:
            return 0.0
        area = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            area += x1 * y2 - x2 * y1
        return abs(area) / 2.0

    def _principal_direction(self, pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        # direção de funcionamento simplificada: menor vão
        return "x" if dx <= dy else "y"

    def import_columns(self, dxf_path: str, width_cm: float = 25.0, depth_cm: float = 25.0, height_m: float = 3.0):
        entities = self.parse_entities(dxf_path)
        columns = []
        counter = 1
        for ent in entities:
            if ent.get("type") == "CIRCLE" and ent.get("8", "").upper() == "PILARES":
                x = float(str(ent.get("10", "0")).replace(",", "."))
                y = float(str(ent.get("20", "0")).replace(",", "."))
                columns.append(Column(f"P{counter}", x, y, width_cm, depth_cm, height_m))
                counter += 1
        return columns

    def find_nearest_column_id(self, x: float, y: float, columns: list[Column], tol: float = 0.35):
        best = None
        for c in columns:
            d = math.hypot(c.x - x, c.y - y)
            if best is None or d < best[0]:
                best = (d, c.id)
        if best and best[0] <= tol:
            return best[1]
        return None

    def import_beams(self, dxf_path: str, columns: list[Column], width_cm: float = 25.0, height_cm: float = 75.0, effective_depth_cm: float = 72.0):
        entities = self.parse_entities(dxf_path)
        beams = []
        counter = 1
        seen = set()
        for ent in entities:
            if ent.get("type") != "LINE" or ent.get("8", "").upper() != "VIGAS":
                continue
            x1 = float(str(ent.get("10", "0")).replace(",", "."))
            y1 = float(str(ent.get("20", "0")).replace(",", "."))
            x2 = float(str(ent.get("11", "0")).replace(",", "."))
            y2 = float(str(ent.get("21", "0")).replace(",", "."))
            n1 = self.find_nearest_column_id(x1, y1, columns)
            n2 = self.find_nearest_column_id(x2, y2, columns)
            if not n1 or not n2 or n1 == n2:
                continue
            key = tuple(sorted((n1, n2)))
            if key in seen:
                continue
            seen.add(key)
            beams.append(Beam(f"B{counter}", n1, n2, width_cm, height_cm, effective_depth_cm, math.hypot(x2 - x1, y2 - y1), BeamType.FRAME))
            counter += 1
        return beams

    def _slab_texts(self, entities):
        texts = []
        for ent in entities:
            if ent.get("type") == "TEXT" and ent.get("8", "").upper() == "LAJE_TEXTOS":
                try:
                    x = float(str(ent.get("10", "0")).replace(",", "."))
                    y = float(str(ent.get("20", "0")).replace(",", "."))
                    texts.append((x, y, str(ent.get("1", "")).strip()))
                except Exception:
                    pass
        return texts

    def import_slabs(self, dxf_path: str, thickness_cm: float = 27.0, effective_depth_cm: float = 24.0, gk_kn_m2: float = 6.15, qk_kn_m2: float = 2.0):
        entities = self.parse_entities(dxf_path)
        texts = self._slab_texts(entities)
        slabs = []
        counter = 1
        for ent in entities:
            if ent.get("type") != "LWPOLYLINE" or ent.get("8", "").upper() != "LAJES":
                continue
            xs = [float(str(v).replace(",", ".")) for v in self._as_list(ent.get("10"))]
            ys = [float(str(v).replace(",", ".")) for v in self._as_list(ent.get("20"))]
            if len(xs) < 3 or len(xs) != len(ys):
                continue
            pts = list(zip(xs, ys))
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span = min(max_x - min_x, max_y - min_y)
            if span <= 0:
                continue
            slab_id = f"SLAB{counter}"
            for tx, ty, label in texts:
                if min_x <= tx <= max_x and min_y <= ty <= max_y and label:
                    slab_id = label
                    break
            slabs.append(SlabPanel(
                slab_id, span, thickness_cm, effective_depth_cm, SlabType.ONE_WAY,
                gk_kn_m2, qk_kn_m2, direction=self._principal_direction(pts),
                polygon_points=pts, area_m2=self._polygon_area(pts)
            ))
            counter += 1
        return slabs
