import math
import re
import unicodedata
from core.model import Column, Beam, BeamType, SlabPanel, SlabType


def _norm_layer(name: str) -> str:
    """Normalise layer name: strip accents, lowercase, remove spaces."""
    nfkd = unicodedata.normalize('NFKD', name)
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower().replace(' ', '_')


# Recognised layer names (normalised) for each element type
_PILAR_LAYERS = {
    'pilares', 'pilar', 'columns', 'column',
    'es_pilar', 'es_pilares', 'estrutura_pilar',
    'pilares_rc', 'pilar_rc',
}
_BEAM_LAYERS = {
    'vigas', 'viga', 'beams', 'beam',
    'es_portico_l_piso', 'es_portticos_cobertura', 'es_porticos_cobertura',
    'es_viga_fundacao', 'es_vigas', 'es_viga',
    'es_portico', 'es_porticos',
}
_SLAB_LAYERS = {
    'lajes', 'laje', 'slabs', 'slab',
    'es_laje_macica', 'es_laje_vigota', 'es_lajes', 'es_laje',
    'es_vigotas_l_piso', 'es_vigotas',
}
_SLAB_TXT_LAYERS = {
    'laje_textos', 'laje_txt', 'es_laje_txt', 'es_laje_macica_txt',
}


class SimpleDXFImporter:
    """
    DXF importer que reconhece convenções portuguesas de desenho estrutural.

    Pilares detectados por (ordem de prioridade):
      1. TEXT/MTEXT com padrão  "P1 (25x25)"  ou  "P1 (Ø30)"  em qualquer layer
      2. LWPOLYLINE/SOLID nas layers PILARES / es_pilar → dims do bounding box
      3. CIRCLE nas layers PILARES / es_pilar → pilar circular

    Layers reconhecidas (case-insensitive, sem acentos):
      PILARES / es_pilar           — geometria do pilar
      VIGAS / es_portico_l_piso /
        es_portticos_cobertura /
        es_viga_fundacao           — vigas (LINE ou LWPOLYLINE)
      LAJES / es_laje_macica /
        es_vigotas_l_piso          — LWPOLYLINE fechada de laje
      LAJE_TEXTOS / es_laje_txt   — TEXT com ID da laje
    """

    def _is_layer(self, ent, layer_set: set) -> bool:
        return _norm_layer(str(ent.get("8", ""))) in layer_set

    # ── DXF raw read ──────────────────────────────────────────────────────────
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

    # ── Column label parser ───────────────────────────────────────────────────
    def _parse_col_label(self, text: str):
        """
        Returns (col_id, width_cm, depth_cm, diam_cm, shape) from a label string.

        Recognised patterns:
          "P1 (25x25)"  "P1(25x25)"   → rectangular 25×25
          "P1 (25X50)"                 → rectangular 25×50
          "P1 (Ø30)"   "P1 (d30)"     → circular Ø30
          "P1"                         → id only, no dims
          "(25x25)"                    → dims only, no id
        """
        text = text.strip()
        col_id = None
        width = None
        depth = None
        diam  = None
        shape = "rectangular"

        # Column ID: letter(s) + digits, e.g. P1, P12, PC1
        id_match = re.match(r'^([A-Za-z]{1,3}\d+)', text)
        if id_match:
            col_id = id_match.group(1).upper()

        # Circular: Ø30, d30, D30, ø30
        circ = re.search(r'[ØøDd][\s]?(\d+(?:[.,]\d+)?)', text)
        if circ:
            diam  = float(circ.group(1).replace(",", "."))
            shape = "circular"
        else:
            # Rectangular: 25x25, 25X50, 25*50, 25×50
            rect = re.search(r'(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)', text)
            if rect:
                width = float(rect.group(1).replace(",", "."))
                depth = float(rect.group(2).replace(",", "."))

        return col_id, width, depth, diam, shape

    def _unit_factor(self, val: float) -> float:
        """Heuristic unit factor: mm→m if >5000, cm→m if >500, else 1."""
        v = abs(val)
        if v > 5000:
            return 0.001   # mm → m
        if v > 500:
            return 0.01    # cm → m
        return 1.0

    # ── Strategy 1: TEXT / MTEXT labels ──────────────────────────────────────
    def _cols_from_text(self, entities, height_m):
        """Scan all text entities for column labels like 'P1 (25x25)'."""
        texts = []
        for ent in entities:
            if ent.get("type") not in ("TEXT", "MTEXT"):
                continue
            try:
                x   = float(str(ent.get("10", "0")).replace(",", "."))
                y   = float(str(ent.get("20", "0")).replace(",", "."))
                txt = str(ent.get("1",  "")).strip()
                # MTEXT uses group 1 too, but may contain formatting codes
                txt = re.sub(r'\\[A-Za-z][^;]*;|[{}]', '', txt)  # strip MTEXT codes
                if txt:
                    texts.append((x, y, txt))
            except Exception:
                pass

        # Group all texts that are "close" (within 3 drawing units)
        # to handle the case where ID and dims are separate TEXT entities
        merged = {}   # col_id -> {"x", "y", "w", "d", "diam", "shape"}

        for x, y, txt in texts:
            col_id, w, d, diam, shape = self._parse_col_label(txt)

            if col_id and (w or diam):
                # Full info in one entity
                merged[col_id] = {"x": x, "y": y, "w": w, "d": d, "diam": diam, "shape": shape}

            elif col_id:
                # ID only — look for a nearby dims text
                if col_id not in merged:
                    merged[col_id] = {"x": x, "y": y, "w": None, "d": None, "diam": None, "shape": "rectangular"}
                else:
                    # Update position if closer to origin (fallback)
                    pass

            elif w or diam:
                # Dims only — attach to nearest known column ID
                best_id   = None
                best_dist = 3.0   # tolerance: 3 drawing units
                for cid, cdata in merged.items():
                    dist = math.hypot(cdata["x"] - x, cdata["y"] - y)
                    if dist < best_dist:
                        best_dist = best_id and dist or dist
                        best_id   = cid
                if best_id and not merged[best_id]["w"] and not merged[best_id]["diam"]:
                    merged[best_id]["w"]     = w
                    merged[best_id]["d"]     = d
                    merged[best_id]["diam"]  = diam
                    merged[best_id]["shape"] = shape

        columns = []
        for col_id, data in sorted(merged.items()):
            x, y = data["x"], data["y"]
            uf = self._unit_factor(x)
            x *= uf;  y *= uf

            if data["diam"]:
                diam = data["diam"]
                # If diam looks like mm (>100 cm), convert
                if diam > 100:
                    diam /= 10.0
                columns.append(Column(col_id, x, y, diam, diam, height_m, shape="circular"))
            else:
                w = data["w"] or 25.0
                d = data["d"] or w
                if w > 200:   w /= 10.0;  d /= 10.0   # mm → cm
                columns.append(Column(col_id, x, y, w, d, height_m, shape="rectangular"))
        return columns

    # ── Strategy 2: LWPOLYLINE on PILARES layer ───────────────────────────────
    def _cols_from_polyline(self, entities, height_m):
        """Detect columns from small closed polylines on recognised column layers."""
        columns = []
        counter = 1
        for ent in entities:
            if ent.get("type") != "LWPOLYLINE":
                continue
            if not self._is_layer(ent, _PILAR_LAYERS):
                continue
            xs = [float(str(v).replace(",", ".")) for v in self._as_list(ent.get("10"))]
            ys = [float(str(v).replace(",", ".")) for v in self._as_list(ent.get("20"))]
            if len(xs) < 2:
                continue
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            uf = self._unit_factor(cx)
            dx = (max(xs) - min(xs)) * uf
            dy = (max(ys) - min(ys)) * uf
            w  = max(dx, 5.0)   # minimum 5 cm
            d  = max(dy, 5.0)
            columns.append(Column(f"P{counter}", cx * uf, cy * uf, w, d, height_m))
            counter += 1
        return columns

    # ── Strategy 3: CIRCLE on PILARES layer (legacy) ─────────────────────────
    def _cols_from_circle(self, entities, height_m):
        columns = []
        counter = 1
        for ent in entities:
            if ent.get("type") != "CIRCLE":
                continue
            if not self._is_layer(ent, _PILAR_LAYERS):
                continue
            x = float(str(ent.get("10", "0")).replace(",", "."))
            y = float(str(ent.get("20", "0")).replace(",", "."))
            r = float(str(ent.get("40", "12.5")).replace(",", "."))
            uf = self._unit_factor(x)
            diam = r * 2 * uf
            if diam > 200:
                diam /= 10.0   # mm → cm
            columns.append(Column(f"P{counter}", x * uf, y * uf, diam, diam, height_m, shape="circular"))
            counter += 1
        return columns

    # ── Public: import_columns ────────────────────────────────────────────────
    def _dedup_columns(self, cols: list, tol_m: float = 0.30) -> list:
        """Remove duplicate columns at (nearly) the same position.
        Keeps the one with largest section or first encountered.
        tol_m: distance threshold in metres — columns closer than this are merged.
        """
        kept = []
        for c in cols:
            duplicate = False
            for k in kept:
                if math.hypot(c.x - k.x, c.y - k.y) < tol_m:
                    # Keep the one with larger section
                    if c.width_cm * c.depth_cm > k.width_cm * k.depth_cm:
                        k.width_cm = c.width_cm
                        k.depth_cm = c.depth_cm
                    duplicate = True
                    break
            if not duplicate:
                kept.append(c)
        # Re-number to keep IDs sequential
        for i, k in enumerate(kept, 1):
            if re.match(r'^P\d+$', k.id):
                k.id = f"P{i}"
        return kept

    def import_columns(self, dxf_path: str,
                       width_cm: float = 25.0, depth_cm: float = 25.0,
                       height_m: float = 3.0):
        entities = self.parse_entities(dxf_path)

        # Try strategies in priority order
        cols = self._cols_from_text(entities, height_m)
        if cols:
            return self._dedup_columns(cols)

        cols = self._cols_from_polyline(entities, height_m)
        if cols:
            return self._dedup_columns(cols)

        cols = self._cols_from_circle(entities, height_m)
        if cols:
            return self._dedup_columns(cols)

        return []

    # ── Nearest column helper ─────────────────────────────────────────────────
    def find_nearest_column_id(self, x: float, y: float,
                                columns: list[Column], tol: float = 0.50):
        best = None
        for c in columns:
            dist = math.hypot(c.x - x, c.y - y)
            if best is None or dist < best[0]:
                best = (dist, c.id)
        if best and best[0] <= tol:
            return best[1]
        return None

    # ── Beams ─────────────────────────────────────────────────────────────────
    def import_beams(self, dxf_path: str, columns: list[Column],
                     width_cm: float = 25.0, height_cm: float = 55.0,
                     effective_depth_cm: float = 52.0):
        entities = self.parse_entities(dxf_path)
        beams    = []
        counter  = 1
        seen     = set()

        # Determine unit factor from column positions
        uf = 1.0
        if columns:
            uf = self._unit_factor(columns[0].x * 10) if columns[0].x < 10 else 1.0

        def _add_beam(x1, y1, x2, y2):
            nonlocal counter
            n1 = self.find_nearest_column_id(x1, y1, columns)
            n2 = self.find_nearest_column_id(x2, y2, columns)
            if not n1 or not n2 or n1 == n2:
                return
            key = tuple(sorted((n1, n2)))
            if key in seen:
                return
            seen.add(key)
            span = math.hypot(x2 - x1, y2 - y1)
            beams.append(Beam(f"B{counter}", n1, n2, width_cm, height_cm,
                              effective_depth_cm, span, BeamType.FRAME))
            counter += 1

        for ent in entities:
            etype = ent.get("type")
            if etype not in ("LINE", "LWPOLYLINE"):
                continue
            if not self._is_layer(ent, _BEAM_LAYERS):
                continue

            if etype == "LINE":
                x1 = float(str(ent.get("10", "0")).replace(",", ".")) * uf
                y1 = float(str(ent.get("20", "0")).replace(",", ".")) * uf
                x2 = float(str(ent.get("11", "0")).replace(",", ".")) * uf
                y2 = float(str(ent.get("21", "0")).replace(",", ".")) * uf
                _add_beam(x1, y1, x2, y2)

            else:  # LWPOLYLINE — iterate consecutive vertex pairs
                xs = [float(str(v).replace(",", ".")) * uf
                      for v in self._as_list(ent.get("10"))]
                ys = [float(str(v).replace(",", ".")) * uf
                      for v in self._as_list(ent.get("20"))]
                pts = list(zip(xs, ys))
                for k in range(len(pts) - 1):
                    _add_beam(pts[k][0], pts[k][1], pts[k+1][0], pts[k+1][1])

        return beams

    # ── Slabs ─────────────────────────────────────────────────────────────────
    def _slab_texts(self, entities):
        texts = []
        for ent in entities:
            if ent.get("type") not in ("TEXT", "MTEXT"):
                continue
            if not self._is_layer(ent, _SLAB_TXT_LAYERS):
                continue
            try:
                x   = float(str(ent.get("10", "0")).replace(",", "."))
                y   = float(str(ent.get("20", "0")).replace(",", "."))
                txt = str(ent.get("1", "")).strip()
                txt = re.sub(r'\\[A-Za-z][^;]*;|[{}]', '', txt)
                texts.append((x, y, txt))
            except Exception:
                pass
        return texts

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
        return "x" if (max(xs) - min(xs)) <= (max(ys) - min(ys)) else "y"

    def import_slabs(self, dxf_path: str, thickness_cm: float = 27.0,
                     effective_depth_cm: float = 24.0,
                     gk_kn_m2: float = 6.15, qk_kn_m2: float = 2.0):
        entities = self.parse_entities(dxf_path)
        texts    = self._slab_texts(entities)
        slabs    = []
        counter  = 1

        # Detect unit factor from all slab coordinates
        all_xs = []
        for ent in entities:
            if ent.get("type") == "LWPOLYLINE" and self._is_layer(ent, _SLAB_LAYERS):
                all_xs += [abs(float(str(v).replace(",", ".")))
                           for v in self._as_list(ent.get("10")) if v]
        raw_max = max(all_xs) if all_xs else 0
        # If coordinates look like mm (>5000 for a building up to 50m), divide by 1000
        # If looks like cm (>500), divide by 100; else assume metres
        if raw_max > 5000:
            uf = 0.001   # mm → m
        elif raw_max > 500:
            uf = 0.01    # cm → m
        else:
            uf = 1.0     # already m

        # Minimum slab area in m² to filter out hatch fragments and details
        MIN_AREA_M2 = 1.5
        # Maximum area — ignore whole-building outlines (> 500 m²)
        MAX_AREA_M2 = 500.0

        for ent in entities:
            if ent.get("type") != "LWPOLYLINE":
                continue
            if not self._is_layer(ent, _SLAB_LAYERS):
                continue
            xs_raw = [float(str(v).replace(",", ".")) for v in self._as_list(ent.get("10"))]
            ys_raw = [float(str(v).replace(",", ".")) for v in self._as_list(ent.get("20"))]
            if len(xs_raw) < 3 or len(xs_raw) != len(ys_raw):
                continue
            xs = [v * uf for v in xs_raw]
            ys = [v * uf for v in ys_raw]
            pts   = list(zip(xs, ys))
            area  = self._polygon_area(pts)
            if area < MIN_AREA_M2 or area > MAX_AREA_M2:
                continue   # skip tiny hatch fragments and whole-building outlines
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span  = min(max_x - min_x, max_y - min_y)
            if span <= 0.1:
                continue
            slab_id = f"SLAB{counter}"
            for tx, ty, label in texts:
                tx_m, ty_m = tx * uf, ty * uf
                if min_x <= tx_m <= max_x and min_y <= ty_m <= max_y and label:
                    slab_id = label
                    break
            slabs.append(SlabPanel(
                slab_id, span, thickness_cm, effective_depth_cm, SlabType.ONE_WAY,
                gk_kn_m2, qk_kn_m2,
                direction=self._principal_direction(pts),
                polygon_points=pts,
                area_m2=self._polygon_area(pts),
            ))
            counter += 1
        return slabs
