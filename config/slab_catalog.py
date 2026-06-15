"""
config/slab_catalog.py
──────────────────────
Catálogo de lajes aligeiradas: Pavineiva (JSON), Presdouro (XML), PAVINORTE (hardcoded).
Expõe:
  - CATALOG: dict  nome → SlabCatalogEntry
  - select_slab(): escolhe a laje mínima adequada para MEd e VEd dados
  - load_catalog(): lê o XML Presdouro de um caminho arbitrário
"""

import xml.etree.ElementTree as ET
import json
import os
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class SlabCatalogEntry:
    nome: str
    altura_cm: float       # espessura total (cm)
    alturaab_cm: float     # espessura da capa de compressão (cm)
    pesom2: float          # peso próprio (kN/m²)
    mrd_knm_m: float       # resistência à flexão (kNm/m)
    vrd_kn_m: float        # resistência ao corte (kN/m)
    ei_kn_m2_m: float      # rigidez EI (kN·m²/m)
    vigota: str = ""       # referência da vigota
    bloco: str = ""        # referência do bloco


def _parse_float(text: str, default: float = 0.0) -> float:
    try:
        return float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default


def load_catalog(xml_path: str) -> dict:
    """Parse Presdouro XML and return dict name→SlabCatalogEntry."""
    catalog = {}
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for pav in root.findall("PAVIMENTO"):
            nome = (pav.findtext("NOME") or "").strip()
            if not nome:
                continue
            altura   = _parse_float(pav.findtext("ALTURA"),   0.0) / 10.0   # mm→cm
            alturaab = _parse_float(pav.findtext("ALTURAAB"), 0.0) / 10.0
            pesom2   = _parse_float(pav.findtext("PESOM2"),   0.0)
            mrd      = _parse_float(pav.findtext("MRD"),      0.0)
            vrd      = _parse_float(pav.findtext("VRD"),      0.0)
            ei       = _parse_float(pav.findtext("EI"),       0.0)
            vigota   = (pav.findtext("VIGOTAN") or "").strip()
            bloco    = (pav.findtext("TIJOLEIRAN") or "").strip()
            catalog[nome] = SlabCatalogEntry(
                nome=nome, altura_cm=altura, alturaab_cm=alturaab,
                pesom2=pesom2, mrd_knm_m=mrd, vrd_kn_m=vrd,
                ei_kn_m2_m=ei, vigota=vigota, bloco=bloco,
            )
    except Exception:
        pass
    return catalog


def _default_xml_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(
        root,
        "Presdouro_Aligeiradas_2015",
        "Presdouro Aligeiradas 2015",
        "lajes_list_xml.xml",
    )


# ── PAVINORTE catalog (hardcoded from manufacturer technical tables) ──────────
# Format: V{class}-C 40x24-{total_height}  (vigota 40cm spacing, 24cm block, +5cm capping)
# pesom2 = self-weight kN/m², MRd kNm/m, VRd kN/m, EI kN·m²/m
_PAVINORTE: dict = {e.nome: e for e in [
    SlabCatalogEntry("V3-C 40x24-25", 25.0, 5.0, 3.65, 16.5, 37.0, 1800.0, "V3-C", "40x24"),
    SlabCatalogEntry("V3-C 40x24-30", 30.0, 5.0, 4.00, 23.0, 42.0, 2800.0, "V3-C", "40x24"),
    SlabCatalogEntry("V5-C 40x24-25", 25.0, 5.0, 4.05, 20.0, 43.0, 2100.0, "V5-C", "40x24"),
    SlabCatalogEntry("V5-C 40x24-30", 30.0, 5.0, 4.40, 28.5, 50.0, 3200.0, "V5-C", "40x24"),
    SlabCatalogEntry("2V5-C 40x24-30", 30.0, 5.0, 5.20, 52.0, 80.0, 5800.0, "2V5-C", "40x24"),
    SlabCatalogEntry("2V6-C 40x24-30", 30.0, 5.0, 5.65, 65.0, 95.0, 7200.0, "2V6-C", "40x24"),
    SlabCatalogEntry("V3-C 40x24-20", 20.0, 5.0, 3.30, 12.0, 32.0, 1300.0, "V3-C", "40x24"),
    SlabCatalogEntry("V5-C 40x24-20", 20.0, 5.0, 3.70, 15.0, 38.0, 1550.0, "V5-C", "40x24"),
]}


# ── Pavineiva catalog (from BDPavineiva.mdb exported to JSON) ─────────────────
def _load_pavineiva_json(json_path: str) -> dict:
    catalog = {}
    try:
        with open(json_path, encoding="utf-8-sig") as f:
            data = json.load(f)
        for item in data:
            nome = (item.get("nome") or "").strip()
            if not nome:
                continue
            def pf(k):
                v = item.get(k)
                try:
                    return float(str(v).replace(",", ".")) if v is not None else 0.0
                except (TypeError, ValueError):
                    return 0.0
            catalog[nome] = SlabCatalogEntry(
                nome=nome,
                altura_cm=pf("altura_cm"),
                alturaab_cm=pf("alturaab_cm"),
                pesom2=pf("pesom2"),
                mrd_knm_m=pf("mrd_knm_m"),
                vrd_kn_m=pf("vrd_kn_m"),
                ei_kn_m2_m=pf("ei_kn_m2_m"),
                vigota=(item.get("vigota") or "").strip(),
                bloco=(item.get("bloco") or "").strip(),
            )
    except Exception:
        pass
    return catalog


def _pavineiva_json_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "pavineiva_catalog.json")


# ── Module-level catalog (loaded once on import) ─────────────────────────────
_XML_PATH = _default_xml_path()
_presdouro: dict = load_catalog(_XML_PATH) if os.path.exists(_XML_PATH) else {}
_pavineiva: dict = _load_pavineiva_json(_pavineiva_json_path())
# Pavineiva first (most complete), then Presdouro, then PAVINORTE as fallback
CATALOG: dict = {**_PAVINORTE, **_presdouro, **_pavineiva}


# ── Selector ──────────────────────────────────────────────────────────────────
def select_slab(
    med_knm_m: float,
    ved_kn_m: float,
    max_height_cm: float = 30.0,
    safety: float = 1.0,
    prefer_block: Optional[str] = None,
) -> Optional[SlabCatalogEntry]:
    """Return the lightest catalog entry that satisfies MRd ≥ MEd and VRd ≥ VEd."""
    candidates: List[SlabCatalogEntry] = []
    for entry in CATALOG.values():
        if entry.altura_cm > max_height_cm:
            continue
        if prefer_block and prefer_block not in entry.nome:
            continue
        if entry.mrd_knm_m >= med_knm_m * safety and entry.vrd_kn_m >= ved_kn_m * safety:
            candidates.append(entry)
    if not candidates:
        return None
    return min(candidates, key=lambda e: (e.pesom2, e.altura_cm))


def auto_select_slab(
    span_m: float,
    rev_kn_m2: float,
    div_kn_m2: float,
    qk_kn_m2: float,
    gamma_g: float = 1.35,
    gamma_q: float = 1.50,
    max_height_cm: float = 50.0,
    prefer_vigota: Optional[str] = None,
) -> Optional[SlabCatalogEntry]:
    """
    Seleção automática ao estilo Pavineiva:
      Para cada laje do catálogo (da mais leve para a mais pesada):
        gk = PP_laje + rev + div
        qd = γG·gk + γQ·qk
        MEd = qd·L²/8,  VEd = qd·L/2
        → aceita a primeira laje onde MRd ≥ MEd e VRd ≥ VEd
    O PP muda com cada tipo de laje, por isso é iterativo.
    """
    # Sort by pesom2 ascending, then altura_cm ascending (lightest first)
    sorted_entries = sorted(
        [e for e in CATALOG.values()
         if e.pesom2 > 0 and e.mrd_knm_m > 0 and e.vrd_kn_m > 0
         and e.altura_cm <= max_height_cm
         and (not prefer_vigota or prefer_vigota in e.vigota)],
        key=lambda e: (e.pesom2, e.altura_cm),
    )
    for entry in sorted_entries:
        gk = entry.pesom2 + rev_kn_m2 + div_kn_m2
        qd = gamma_g * gk + gamma_q * qk_kn_m2
        med = qd * span_m ** 2 / 8.0
        ved = qd * span_m / 2.0
        if entry.mrd_knm_m >= med and entry.vrd_kn_m >= ved:
            return entry
    return None


def catalog_names() -> List[str]:
    """Sorted list of all catalog entry names."""
    return sorted(CATALOG.keys())


def entries_by_height(height_cm: float, tol: float = 0.5) -> List[SlabCatalogEntry]:
    """Return all entries with total height within ±tol cm."""
    return [e for e in CATALOG.values() if abs(e.altura_cm - height_cm) <= tol]
