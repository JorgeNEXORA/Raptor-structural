"""
config/slab_catalog.py
──────────────────────
Catálogo de lajes aligeiradas Presdouro.
Lê o XML do fabricante e expõe:
  - CATALOG: dict  nome → SlabCatalogEntry
  - select_slab(): escolhe a laje mínima adequada para MEd e VEd dados
  - load_catalog(): lê o XML de um caminho arbitrário
"""

import xml.etree.ElementTree as ET
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


# ── Module-level catalog (loaded once on import) ─────────────────────────────
_XML_PATH = _default_xml_path()
CATALOG: dict = load_catalog(_XML_PATH) if os.path.exists(_XML_PATH) else {}


# ── Selector ──────────────────────────────────────────────────────────────────
def select_slab(
    med_knm_m: float,
    ved_kn_m: float,
    max_height_cm: float = 30.0,
    safety: float = 1.0,
    prefer_block: Optional[str] = None,
) -> Optional[SlabCatalogEntry]:
    """
    Return the lightest catalog entry that satisfies:
        MRd ≥ med_knm_m × safety
        VRd ≥ ved_kn_m × safety
        altura_cm ≤ max_height_cm

    Optionally filter by block type substring (e.g. "BL40x20").
    Returns None if no entry satisfies the constraints.
    """
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
    # Choose minimum weight (pesom2), break ties by minimum height
    return min(candidates, key=lambda e: (e.pesom2, e.altura_cm))


def catalog_names() -> List[str]:
    """Sorted list of all catalog entry names."""
    return sorted(CATALOG.keys())


def entries_by_height(height_cm: float, tol: float = 0.5) -> List[SlabCatalogEntry]:
    """Return all entries with total height within ±tol cm."""
    return [e for e in CATALOG.values() if abs(e.altura_cm - height_cm) <= tol]
