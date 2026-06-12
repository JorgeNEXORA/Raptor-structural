"""
config/loads.py
───────────────
Biblioteca de cargas para construção portuguesa.
Valores baseados em EC1-1-1 (EN 1991-1-1) e prática corrente portuguesa.

Uso:
    from config.loads import LoadConfigurator
    cfg = LoadConfigurator()
    result = cfg.calc(floor_cfg, roof_cfg)
    # result.gk_piso, result.qk_piso, result.gk_cobertura, result.qk_cobertura
"""

from dataclasses import dataclass, field
from typing import List


# ── EC1-1-1 Table 6.1/6.2 — Imposed loads by category ───────────────────────
USE_CATEGORY = {
    # (qk kN/m², description)
    "habitacao":          (2.0,  "Habitação / quartos de hotel"),
    "escritorios":        (3.0,  "Escritórios"),
    "comercial":          (4.0,  "Área comercial / loja"),
    "industrial_leve":    (5.0,  "Industrial leve / armazém leve"),
    "industrial_pesado":  (7.5,  "Industrial pesado / armazém pesado"),
    "biblioteca":         (7.5,  "Biblioteca / arquivo"),
    "escola":             (3.0,  "Sala de aula / escola"),
    "auditorio":          (4.0,  "Auditório / sala de reuniões"),
    "garagem_ligeiros":   (2.5,  "Garagem — veículos ligeiros (≤30 kN)"),
    "garagem_pesados":    (5.0,  "Garagem — veículos pesados (>30 kN)"),
    "varanda":            (3.0,  "Varanda / terraço acessível"),
    "cobertura_manutencao": (1.0, "Cobertura — acesso manutenção"),
    "cobertura_acessivel":  (3.0, "Cobertura — acessível ao público"),
}

# ── Permanent loads: floor buildup ─────────────────────────────────────────
# Unidade: kN/m²

LAJE = {
    # type: (gk kN/m², description)
    "macica_16cm":     (4.0,  "Laje maciça h=16 cm"),
    "macica_18cm":     (4.5,  "Laje maciça h=18 cm"),
    "macica_20cm":     (5.0,  "Laje maciça h=20 cm"),
    "macica_22cm":     (5.5,  "Laje maciça h=22 cm"),
    "macica_25cm":     (6.25, "Laje maciça h=25 cm"),
    "aligeirada_20cm": (3.5,  "Laje aligeirada h=20 cm (abobadilha)"),
    "aligeirada_25cm": (4.0,  "Laje aligeirada h=25 cm (abobadilha)"),
    "aligeirada_30cm": (4.5,  "Laje aligeirada h=30 cm (EPS)"),
}

BETONILHA = {
    # espessura cm → gk kN/m²  (ρ = 1800 kg/m³ = 18 kN/m³)
    5:  0.90, 6: 1.08, 7: 1.26, 8: 1.44, 9: 1.62,
    10: 1.80, 12: 2.16, 15: 2.70, 20: 3.60, 23: 4.14,
}

ISOLAMENTO = {
    "xps_4cm":  (0.03, "XPS 4 cm"),
    "xps_6cm":  (0.04, "XPS 6 cm"),
    "xps_8cm":  (0.05, "XPS 8 cm"),
    "eps_6cm":  (0.02, "EPS 6 cm"),
    "eps_10cm": (0.03, "EPS 10 cm"),
    "lan_60mm": (0.02, "Lã mineral 60 mm"),
}

ACABAMENTO_PISO = {
    "ceramico":     (0.50, "Cerâmico + betume colagem"),
    "pedra_2cm":    (0.54, "Pedra natural 2 cm"),
    "pedra_3cm":    (0.81, "Pedra natural 3 cm"),
    "vinilico":     (0.05, "Revestimento vinílico"),
    "madeira_flut": (0.15, "Soalho flutuante"),
    "epoxy":        (0.10, "Epoxy (garagem/industrial)"),
    "sem_acabamento": (0.0, "Sem acabamento (estrutura à vista)"),
}

# ── Permanent loads: roof buildup ────────────────────────────────────────────
COBERTURA_TIPO = {
    "plana_invertida": "Cobertura plana invertida (XPS acima da impermeabilização)",
    "plana_tradicional": "Cobertura plana tradicional (XPS abaixo)",
    "inclinada_telha": "Cobertura inclinada — telha cerâmica",
    "inclinada_metalica": "Cobertura inclinada — chapa metálica",
    "verde": "Cobertura verde extensiva",
}

IMPERMEABILIZACAO = {
    "tela_1":     (0.05, "1 tela betuminosa"),
    "tela_2":     (0.10, "2 telas betuminosas"),
    "tela_3":     (0.15, "3 telas betuminosas"),
    "liquida":    (0.03, "Impermeabilização líquida"),
    "pvc":        (0.04, "Membrana PVC"),
}

ACABAMENTO_COB = {
    "godo_5cm":       (0.90, "Godo 5 cm (ρ≈18 kN/m³)"),
    "godo_10cm":      (1.80, "Godo 10 cm"),
    "lajeta_ceramic": (0.60, "Lajetas cerâmicas em suportes"),
    "lajeta_beton":   (0.80, "Lajetas betão 4 cm"),
    "telha_ceramica": (0.65, "Telha cerâmica"),
    "telha_beton":    (0.50, "Telha betão"),
    "chapa_simples":  (0.15, "Chapa metálica simples"),
    "zinco":          (0.07, "Zinco"),
    "sem_acabamento": (0.0,  "Sem acabamento protector"),
}

BETONILHA_PENDENTE = {
    "sem":    (0.0,  "Sem betonilha de pendente"),
    "5cm":    (0.90, "Betonilha de pendente média 5 cm"),
    "8cm":    (1.44, "Betonilha de pendente média 8 cm"),
    "12cm":   (2.16, "Betonilha de pendente média 12 cm"),
    "15cm":   (2.70, "Betonilha de pendente média 15 cm"),
}

EQUIPAMENTOS_COB = {
    "sem":         (0.0,  "Sem equipamentos"),
    "acs":         (0.25, "Painéis solares térmicos (AQS)"),
    "fotovoltaico":(0.15, "Painéis fotovoltaicos"),
    "acs_fv":      (0.40, "Painéis AQS + fotovoltaicos"),
    "ar_cond":     (0.50, "Unidades de ar condicionado"),
    "acs_ar":      (0.75, "Painéis AQS + ar condicionado"),
    "tudo":        (0.90, "AQS + FV + ar condicionado"),
}


# ── Result dataclass ─────────────────────────────────────────────────────────
@dataclass
class LoadResult:
    # Floor
    gk_piso: float = 0.0
    qk_piso: float = 0.0
    gk_piso_breakdown: List[str] = field(default_factory=list)

    # Roof
    gk_cobertura: float = 0.0
    qk_cobertura: float = 0.0
    gk_cob_breakdown: List[str] = field(default_factory=list)

    # Special zones
    gk_varanda: float = 0.0
    qk_varanda: float = 0.0
    gk_garagem: float = 0.0
    qk_garagem: float = 0.0


# ── Configurator ─────────────────────────────────────────────────────────────
class LoadConfigurator:
    """
    Build gk / qk for floor and roof from user selections.
    All values in kN/m².
    """

    def calc_floor(
        self,
        laje_key: str           = "macica_20cm",
        betonilha1_cm: int      = 12,
        isolamento_key: str     = "xps_6cm",
        betonilha2_cm: int      = 5,
        acabamento_key: str     = "ceramico",
        uso_key: str            = "habitacao",
        paredes_divisorias: bool = True,
    ) -> tuple[float, float, list]:
        """Returns (gk, qk, breakdown_lines)."""
        breakdown = []

        laje_gk, laje_desc = LAJE.get(laje_key, (5.0, laje_key))
        breakdown.append(f"Laje: {laje_desc} → {laje_gk:.2f} kN/m²")

        bet1 = BETONILHA.get(betonilha1_cm, betonilha1_cm * 0.18)
        breakdown.append(f"1ª Betonilha {betonilha1_cm}cm → {bet1:.2f} kN/m²")

        iso_gk, iso_desc = ISOLAMENTO.get(isolamento_key, (0.04, isolamento_key))
        breakdown.append(f"Isolamento: {iso_desc} → {iso_gk:.2f} kN/m²")

        bet2 = BETONILHA.get(betonilha2_cm, betonilha2_cm * 0.18)
        breakdown.append(f"2ª Betonilha {betonilha2_cm}cm → {bet2:.2f} kN/m²")

        acab_gk, acab_desc = ACABAMENTO_PISO.get(acabamento_key, (0.5, acabamento_key))
        breakdown.append(f"Acabamento: {acab_desc} → {acab_gk:.2f} kN/m²")

        paredes_gk = 1.0 if paredes_divisorias else 0.0
        if paredes_divisorias:
            breakdown.append(f"Paredes divisórias (EC1 §6.3.1.2) → 1.00 kN/m²")

        gk = laje_gk + bet1 + iso_gk + bet2 + acab_gk + paredes_gk

        qk, uso_desc = USE_CATEGORY.get(uso_key, (2.0, uso_key))
        breakdown.append(f"Uso: {uso_desc} → qk = {qk:.2f} kN/m²")
        breakdown.append(f"─── gk total piso = {gk:.2f} kN/m²")

        return round(gk, 2), round(qk, 2), breakdown

    def calc_roof(
        self,
        laje_key: str             = "macica_20cm",
        impermeab_key: str        = "tela_2",
        isolamento_key: str       = "xps_8cm",
        betonilha_pendente_key: str = "8cm",
        acabamento_key: str       = "godo_5cm",
        equipamentos_key: str     = "sem",
        uso_key: str              = "cobertura_manutencao",
    ) -> tuple[float, float, list]:
        """Returns (gk, qk, breakdown_lines)."""
        breakdown = []

        laje_gk, laje_desc = LAJE.get(laje_key, (5.0, laje_key))
        breakdown.append(f"Laje cobertura: {laje_desc} → {laje_gk:.2f} kN/m²")

        imp_gk, imp_desc = IMPERMEABILIZACAO.get(impermeab_key, (0.10, impermeab_key))
        breakdown.append(f"Impermeabilização: {imp_desc} → {imp_gk:.2f} kN/m²")

        iso_gk, iso_desc = ISOLAMENTO.get(isolamento_key, (0.05, isolamento_key))
        breakdown.append(f"Isolamento: {iso_desc} → {iso_gk:.2f} kN/m²")

        pend_gk, pend_desc = BETONILHA_PENDENTE.get(betonilha_pendente_key, (0.0, ""))
        if pend_gk > 0:
            breakdown.append(f"Betonilha de pendente: {pend_desc} → {pend_gk:.2f} kN/m²")

        acab_gk, acab_desc = ACABAMENTO_COB.get(acabamento_key, (0.0, acabamento_key))
        breakdown.append(f"Acabamento/protecção: {acab_desc} → {acab_gk:.2f} kN/m²")

        equip_gk, equip_desc = EQUIPAMENTOS_COB.get(equipamentos_key, (0.0, ""))
        if equip_gk > 0:
            breakdown.append(f"Equipamentos: {equip_desc} → {equip_gk:.2f} kN/m²")

        gk = laje_gk + imp_gk + iso_gk + pend_gk + acab_gk + equip_gk

        qk, uso_desc = USE_CATEGORY.get(uso_key, (1.0, uso_key))
        breakdown.append(f"Uso: {uso_desc} → qk = {qk:.2f} kN/m²")
        breakdown.append(f"─── gk total cobertura = {gk:.2f} kN/m²")

        return round(gk, 2), round(qk, 2), breakdown

    def calc_varanda(
        self,
        laje_key: str     = "macica_16cm",
        betonilha_cm: int = 21,
        acabamento_key: str = "ceramico",
    ) -> tuple[float, float]:
        laje_gk, _ = LAJE.get(laje_key, (4.0, ""))
        bet_gk = BETONILHA.get(betonilha_cm, betonilha_cm * 0.18)
        acab_gk, _ = ACABAMENTO_PISO.get(acabamento_key, (0.5, ""))
        gk = laje_gk + bet_gk + acab_gk
        qk, _ = USE_CATEGORY["varanda"]
        return round(gk, 2), round(qk, 2)

    def calc_garagem(
        self,
        laje_key: str     = "macica_22cm",
        betonilha_cm: int = 23,
        veiculos: str     = "garagem_ligeiros",
    ) -> tuple[float, float]:
        laje_gk, _ = LAJE.get(laje_key, (5.5, ""))
        bet_gk = BETONILHA.get(betonilha_cm, betonilha_cm * 0.18)
        gk = laje_gk + bet_gk
        qk, _ = USE_CATEGORY.get(veiculos, (2.5, ""))
        return round(gk, 2), round(qk, 2)
