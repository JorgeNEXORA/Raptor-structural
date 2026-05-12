import csv
from core.model import Column, Beam, BeamType, SlabPanel, SlabType


class CSVGeometryImporter:
    REQUIRED_FIELDS = ["id", "x", "y"]

    def load_columns(self, csv_path: str, width_cm: float = 25.0, depth_cm: float = 25.0, height_m: float = 3.0):
        columns = []
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [x.strip() for x in (reader.fieldnames or [])]
            for req in self.REQUIRED_FIELDS:
                if req not in fields:
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV.")

            for row in reader:
                col_id = str(row["id"]).strip()
                x = float(str(row["x"]).replace(",", "."))
                y = float(str(row["y"]).replace(",", "."))
                w = float(str(row.get("width_cm", width_cm)).replace(",", "."))
                d = float(str(row.get("depth_cm", depth_cm)).replace(",", "."))
                h = float(str(row.get("height_m", height_m)).replace(",", "."))
                columns.append(Column(col_id, x, y, w, d, h))
        return columns


class CSVBeamImporter:
    REQUIRED_FIELDS = ["id", "start_node", "end_node"]

    def load_beams(self, csv_path: str, columns: list[Column], width_cm: float = 25.0, height_cm: float = 75.0, effective_depth_cm: float = 72.0):
        col_map = {c.id: c for c in columns}
        beams = []
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [x.strip() for x in (reader.fieldnames or [])]
            for req in self.REQUIRED_FIELDS:
                if req not in fields:
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV das vigas.")

            for row in reader:
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
            fields = [x.strip() for x in (reader.fieldnames or [])]
            for req in self.REQUIRED_FIELDS:
                if req not in fields:
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV das lajes.")

            for row in reader:
                sid = str(row["id"]).strip()
                span = float(str(row["span_m"]).replace(",", "."))
                gk = float(str(row["gk_kn_m2"]).replace(",", "."))
                qk = float(str(row["qk_kn_m2"]).replace(",", "."))
                thk = float(str(row.get("thickness_cm", thickness_cm)).replace(",", "."))
                d = float(str(row.get("effective_depth_cm", effective_depth_cm)).replace(",", "."))
                slabs.append(SlabPanel(sid, span, thk, d, SlabType.ONE_WAY, gk, qk))
        return slabs


class CSVSlabLoadImporter:
    REQUIRED_FIELDS = ["id", "gk_kn_m2", "qk_kn_m2"]

    def load_slab_loads(self, csv_path: str):
        slab_loads = {}
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [x.strip() for x in (reader.fieldnames or [])]
            for req in self.REQUIRED_FIELDS:
                if req not in fields:
                    raise ValueError(f"Falta a coluna obrigatória '{req}' no CSV das lajes.")

            for row in reader:
                slab_id = str(row["id"]).strip()
                gk = float(str(row["gk_kn_m2"]).replace(",", "."))
                qk = float(str(row["qk_kn_m2"]).replace(",", "."))
                desc = str(row.get("description", "")).strip()
                slab_loads[slab_id] = {
                    "gk_kn_m2": gk,
                    "qk_kn_m2": qk,
                    "description": desc,
                }
        return slab_loads
