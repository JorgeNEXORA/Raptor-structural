import csv
from core.model import Column, Beam, BeamType, SlabPanel, SlabType

_SLAB_TYPE_MAP = {
    "one_way": SlabType.ONE_WAY, "oneway": SlabType.ONE_WAY,
    "laje_simples": SlabType.ONE_WAY, "simples": SlabType.ONE_WAY,
    "two_way": SlabType.TWO_WAY, "twoway": SlabType.TWO_WAY,
    "duas_direcoes": SlabType.TWO_WAY, "cruzada": SlabType.TWO_WAY,
    "ribbed": SlabType.RIBBED, "aligeirada": SlabType.RIBBED,
    "vigota": SlabType.RIBBED, "lm": SlabType.RIBBED,
    "cantilever": SlabType.CANTILEVER, "consola": SlabType.CANTILEVER,
    "balanco": SlabType.CANTILEVER, "balanço": SlabType.CANTILEVER,
}

# Portuguese → English column name aliases (applied before parsing)
_COL_ALIASES = {
    # pilares
    "altura_m": "height_m", "altura": "height_m",
    "largura_cm": "width_cm", "largura": "width_cm",
    "profundidade_cm": "depth_cm", "profundidade": "depth_cm",
    "forma": "shape", "circular": "shape",
    "diametro_cm": "diameter_cm", "diâmetro_cm": "diameter_cm",
    "diametro": "diameter_cm", "diâmetro": "diameter_cm",
    # vigas
    "no_inicio": "start_node", "nó_inicio": "start_node",
    "no_fim": "end_node", "nó_fim": "end_node",
    "altura_cm": "height_cm",
    "altura_util_cm": "effective_depth_cm", "d_cm": "effective_depth_cm",
    # lajes
    "vao_m": "span_m", "vão_m": "span_m", "vao": "span_m",
    "espessura_cm": "thickness_cm", "espessura": "thickness_cm",
    "tipo": "type",
    "catalogo": "catalog_id", "catálogo": "catalog_id",
    # cargas lajes
    "descricao": "description", "descrição": "description",
}


def _normalize_row(row: dict) -> dict:
    """Replace Portuguese column names with their English equivalents."""
    return {_COL_ALIASES.get(k.strip().lower(), k.strip().lower()): v
            for k, v in row.items()}


class CSVGeometryImporter:
    REQUIRED_FIELDS = ["id", "x", "y"]

    def load_columns(self, csv_path: str, width_cm: float = 25.0, depth_cm: float = 25.0, height_m: float = 3.0):
        columns = []
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [_COL_ALIASES.get(x.strip().lower(), x.strip().lower()) for x in (reader.fieldnames or [])]
            for req in self.REQUIRED_FIELDS:
                if req not in fields:
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV.")

            for raw_row in reader:
                row = _normalize_row(raw_row)
                col_id = str(row["id"]).strip()
                x      = float(str(row["x"]).replace(",", "."))
                y      = float(str(row["y"]).replace(",", "."))
                h      = float(str(row.get("height_m", height_m)).replace(",", "."))

                raw_shape = str(row.get("shape", "rectangular")).strip().lower()
                diam_raw  = str(row.get("diameter_cm", "")).strip()

                if diam_raw:
                    diam = float(diam_raw.replace(",", "."))
                    columns.append(Column(col_id, x, y, diam, diam, h, shape="circular"))
                elif raw_shape in ("circular", "round", "circ", "circle", "redondo"):
                    diam = float(str(row.get("width_cm", width_cm)).replace(",", "."))
                    columns.append(Column(col_id, x, y, diam, diam, h, shape="circular"))
                else:
                    w = float(str(row.get("width_cm", width_cm)).replace(",", "."))
                    d = float(str(row.get("depth_cm", depth_cm)).replace(",", "."))
                    w = max(w, 25.0)
                    d = max(d, 25.0)
                    columns.append(Column(col_id, x, y, w, d, h, shape="rectangular"))
        return columns


class CSVBeamImporter:
    REQUIRED_FIELDS = ["id", "start_node", "end_node"]

    def load_beams(self, csv_path: str, columns: list[Column], width_cm: float = 25.0, height_cm: float = 75.0, effective_depth_cm: float = 72.0):
        col_map = {c.id: c for c in columns}
        beams = []
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [_COL_ALIASES.get(x.strip().lower(), x.strip().lower()) for x in (reader.fieldnames or [])]
            for req in self.REQUIRED_FIELDS:
                if req not in fields:
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV das vigas.")

            for raw_row in reader:
                row = _normalize_row(raw_row)
                bid = str(row["id"]).strip()
                n1 = str(row["start_node"]).strip()
                n2 = str(row["end_node"]).strip()
                if n1 not in col_map or n2 not in col_map:
                    raise ValueError(f"Viga {bid}: nó '{n1}' ou '{n2}' não existe nos pilares.")
                c1, c2 = col_map[n1], col_map[n2]
                span = ((c1.x-c2.x)**2 + (c1.y-c2.y)**2) ** 0.5
                bw = float(str(row.get("width_cm", width_cm)).replace(",", "."))
                h = float(str(row.get("height_cm", height_cm)).replace(",", "."))
                d = float(str(row.get("effective_depth_cm", effective_depth_cm)).replace(",", "."))
                beams.append(Beam(bid, n1, n2, bw, h, d, span, BeamType.FRAME))
        return beams


class CSVSlabImporter:
    REQUIRED_FIELDS = ["id", "span_m", "gk_kn_m2", "qk_kn_m2"]

    def load_slabs(self, csv_path: str, thickness_cm: float = 27.0, effective_depth_cm: float = 24.0):
        slabs = []
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [_COL_ALIASES.get(x.strip().lower(), x.strip().lower()) for x in (reader.fieldnames or [])]
            # accept vao_m as alias for span_m in required check
            req_aliases = {"span_m": ["span_m", "vao_m", "vão_m"]}
            for req in self.REQUIRED_FIELDS:
                alts = req_aliases.get(req, [req])
                if not any(a in fields for a in alts):
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV das lajes.")

            for raw_row in reader:
                row = _normalize_row(raw_row)
                sid  = str(row["id"]).strip()
                span = float(str(row["span_m"]).replace(",", "."))
                gk   = float(str(row["gk_kn_m2"]).replace(",", "."))
                qk   = float(str(row["qk_kn_m2"]).replace(",", "."))
                thk  = float(str(row.get("thickness_cm", thickness_cm)).replace(",", "."))
                d    = float(str(row.get("effective_depth_cm", effective_depth_cm)).replace(",", "."))
                raw_type   = str(row.get("type", "one_way")).strip().lower()
                slab_type  = _SLAB_TYPE_MAP.get(raw_type, SlabType.ONE_WAY)
                catalog_id = str(row.get("catalog_id", "")).strip() or None
                raw_level  = str(row.get("level", row.get("nivel", "piso"))).strip().lower()
                level = "cobertura" if raw_level in ("cobertura", "cob", "roof") else "piso"
                s = SlabPanel(sid, span, thk, d, slab_type, gk, qk)
                s.catalog_id = catalog_id
                s.level = level
                slabs.append(s)
        return slabs


class CSVSlabLoadImporter:
    REQUIRED_FIELDS = ["id", "gk_kn_m2", "qk_kn_m2"]

    def load_slab_loads(self, csv_path: str):
        slab_loads = {}
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [_COL_ALIASES.get(x.strip().lower(), x.strip().lower()) for x in (reader.fieldnames or [])]
            for req in self.REQUIRED_FIELDS:
                if req not in fields:
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV de cargas das lajes.")

            for raw_row in reader:
                row = _normalize_row(raw_row)
                slab_id = str(row["id"]).strip()
                gk = float(str(row["gk_kn_m2"]).replace(",", "."))
                qk = float(str(row["qk_kn_m2"]).replace(",", "."))
                desc = str(row.get("description", row.get("descricao", ""))).strip()
                slab_loads[slab_id] = {
                    "gk_kn_m2": gk,
                    "qk_kn_m2": qk,
                    "description": desc,
                }
        return slab_loads
