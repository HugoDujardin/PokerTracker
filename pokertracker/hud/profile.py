"""Profils de HUD: panneaux, statistiques affichees, couleurs et conditions.

Un profil contient plusieurs panneaux. Pour chaque joueur, le premier
panneau dont la condition est satisfaite est affiche: c'est le principe du
HUD dynamique (un affichage different selon la position, la profondeur de
tapis ou le nombre de joueurs).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence

from ..core.stats import definitions as sd


@dataclass
class ColorRule:
    """Coloration conditionnelle d'une valeur de statistique."""
    op: str = ">"                     # '<', '>', 'between'
    value: float = 0.0
    value2: float = 0.0
    color: str = "#e0e0e0"

    def matches(self, v: float) -> bool:
        if self.op == "<":
            return v < self.value
        if self.op == ">":
            return v > self.value
        if self.op == "between":
            return self.value <= v <= self.value2
        return False


@dataclass
class StatCell:
    code: str
    label: str = ""
    decimals: int = 0
    min_sample: int = 0               # masque la stat en dessous de N observations
    colors: List[ColorRule] = field(default_factory=list)

    def definition(self) -> Optional[sd.StatDef]:
        return sd.get(self.code)

    def display(self, agg: dict) -> tuple[str, str]:
        """Retourne (texte, couleur)."""
        stat = self.definition()
        if stat is None:
            return "?", "#888888"
        if self.min_sample and stat.sample(agg) < self.min_sample:
            return "-", "#777777"
        text = stat.format(agg)
        value = stat.value(agg)
        color = "#e6e6e6"
        if value is not None:
            for rule in self.colors:
                if rule.matches(value):
                    color = rule.color
                    break
        return text, color

    def title(self) -> str:
        if self.label:
            return self.label
        stat = self.definition()
        return stat.label if stat else self.code


@dataclass
class PanelCondition:
    """Condition d'affichage d'un panneau (HUD dynamique)."""
    positions: List[str] = field(default_factory=list)     # position attendue du joueur
    min_players: int = 0
    max_players: int = 0
    min_hands: int = 0
    min_stack_bb: float = 0.0
    max_stack_bb: float = 0.0
    formats: List[str] = field(default_factory=list)       # cash / mtt / sng / spin

    def matches(self, ctx: "PlayerContext") -> bool:
        if self.positions and ctx.position not in self.positions:
            return False
        if self.min_players and ctx.nb_players < self.min_players:
            return False
        if self.max_players and ctx.nb_players > self.max_players:
            return False
        if self.min_hands and ctx.hands < self.min_hands:
            return False
        if self.min_stack_bb or self.max_stack_bb:
            if ctx.stack_bb <= 0:          # profondeur inconnue: condition ignoree
                return False
            if self.min_stack_bb and ctx.stack_bb < self.min_stack_bb:
                return False
            if self.max_stack_bb and ctx.stack_bb > self.max_stack_bb:
                return False
        if self.formats and ctx.table_format not in self.formats:
            return False
        return True


@dataclass
class PlayerContext:
    """Etat connu d'un joueur a la table, utilise par les conditions."""
    name: str = ""
    position: str = ""
    nb_players: int = 0
    stack_bb: float = 0.0
    hands: int = 0
    table_format: str = "cash"
    is_hero: bool = False


@dataclass
class HudPanel:
    name: str = "Principal"
    condition: PanelCondition = field(default_factory=PanelCondition)
    rows: List[List[StatCell]] = field(default_factory=list)
    #: 'all' = stats sur toutes les mains, 'position' = filtrees sur la
    #: position occupee par le joueur a cette main
    scope: str = "all"
    background: str = "#101317"
    border: str = "#3a4250"
    text_color: str = "#e6e6e6"

    def cells(self) -> List[StatCell]:
        return [c for row in self.rows for c in row]


@dataclass
class PopupSection:
    title: str
    stats: List[str] = field(default_factory=list)


@dataclass
class HudProfile:
    name: str = "Cash 6-max"
    panels: List[HudPanel] = field(default_factory=list)
    popups: List[PopupSection] = field(default_factory=list)
    font_family: str = "Segoe UI"
    font_size: int = 11
    opacity: float = 0.92
    show_player_name: bool = True
    show_hand_count: bool = True

    # ------------------------------------------------------------------
    def panel_for(self, ctx: PlayerContext) -> Optional[HudPanel]:
        for panel in self.panels:
            if panel.condition.matches(ctx):
                return panel
        return self.panels[0] if self.panels else None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, payload: str) -> "HudProfile":
        data = json.loads(payload)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HudProfile":
        panels = []
        for p in data.get("panels", []):
            rows = [[StatCell(**{**c, "colors": [ColorRule(**r) for r in c.get("colors", [])]})
                     for c in row] for row in p.get("rows", [])]
            panels.append(HudPanel(
                name=p.get("name", "Panneau"),
                condition=PanelCondition(**p.get("condition", {})),
                rows=rows,
                scope=p.get("scope", "all"),
                background=p.get("background", "#101317"),
                border=p.get("border", "#3a4250"),
                text_color=p.get("text_color", "#e6e6e6"),
            ))
        popups = [PopupSection(**s) for s in data.get("popups", [])]
        return cls(
            name=data.get("name", "Profil"),
            panels=panels,
            popups=popups,
            font_family=data.get("font_family", "Segoe UI"),
            font_size=int(data.get("font_size", 11)),
            opacity=float(data.get("opacity", 0.92)),
            show_player_name=bool(data.get("show_player_name", True)),
            show_hand_count=bool(data.get("show_hand_count", True)),
        )


# ---------------------------------------------------------------------------
# Profils fournis par defaut
# ---------------------------------------------------------------------------

def _cell(code: str, low: float = 0, high: float = 100, min_sample: int = 0) -> StatCell:
    """Cellule avec coloration rouge/vert autour d'un intervalle 'standard'."""
    colors = [
        ColorRule("<", low, 0, "#5fb3ff"),      # tres bas -> bleu
        ColorRule(">", high, 0, "#ff6b6b"),     # tres haut -> rouge
    ]
    return StatCell(code=code, min_sample=min_sample, colors=colors)


def default_profile() -> HudProfile:
    """Profil generaliste 6-max: 2 lignes de stats + panneau short stack."""
    main = HudPanel(
        name="Principal",
        rows=[
            [StatCell("hands"), _cell("vpip", 18, 32), _cell("pfr", 12, 26), _cell("3bet", 4, 11)],
            [_cell("f3bet", 40, 70, 15), _cell("steal", 25, 55, 15), _cell("cbet_f", 45, 75, 12),
             _cell("wtsd", 22, 32, 20)],
        ],
    )
    short = HudPanel(
        name="Tapis court",
        condition=PanelCondition(max_stack_bb=25),
        rows=[
            [StatCell("hands"), _cell("vpip", 18, 32), _cell("pfr", 12, 26)],
            [_cell("3bet", 4, 11), _cell("fsteal", 55, 85, 10), _cell("af")],
        ],
        border="#a06a2c",
    )
    blinds = HudPanel(
        name="Defense des blindes",
        condition=PanelCondition(positions=["SB", "BB"]),
        rows=[
            [StatCell("hands"), _cell("vpip", 18, 32), _cell("pfr", 12, 26), _cell("3bet", 4, 11)],
            [_cell("fsteal", 55, 85, 10), _cell("resteal", 5, 16, 10), _cell("fcbet_f", 40, 65, 12),
             _cell("wwsf", 42, 52, 20)],
        ],
        scope="position",
        border="#2c6ea0",
    )
    popups = [
        PopupSection("Preflop", ["vpip", "pfr", "rfi", "limp", "cc", "3bet", "4bet", "cold4bet",
                                 "f3bet", "c3bet", "f4bet", "squeeze", "steal", "fsteal",
                                 "resteal", "callsteal", "iso"]),
        PopupSection("Flop", ["cbet_f", "fcbet_f", "rcbet_f", "donk_f", "probe_f", "fbet_f", "xr_f"]),
        PopupSection("Turn", ["cbet_t", "fcbet_t", "rcbet_t", "donk_t", "probe_t", "dcbet_t",
                              "fbet_t", "xr_t"]),
        PopupSection("River", ["cbet_r", "fcbet_r", "rcbet_r", "donk_r", "probe_r", "fbet_r", "xr_r"]),
        PopupSection("Global", ["hands", "af", "afq", "wwsf", "wtsd", "wsd", "sawflop", "bb100", "net"]),
    ]
    return HudProfile(name="Cash 6-max", panels=[short, blinds, main], popups=popups)


def heads_up_profile() -> HudProfile:
    p = default_profile()
    p.name = "Heads-up"
    p.panels = [HudPanel(
        name="HU",
        rows=[
            [StatCell("hands"), _cell("vpip", 40, 75), _cell("pfr", 30, 60)],
            [_cell("3bet", 8, 18), _cell("fsteal", 40, 70), _cell("cbet_f", 50, 80)],
            [_cell("fcbet_f", 40, 60), _cell("wtsd", 26, 38), _cell("af")],
        ],
    )]
    return p


def mtt_profile() -> HudProfile:
    p = default_profile()
    p.name = "Tournois"
    p.panels = [
        HudPanel(name="Court (<20bb)", condition=PanelCondition(max_stack_bb=20),
                 rows=[[StatCell("hands"), _cell("vpip", 18, 35), _cell("pfr", 14, 30)],
                       [_cell("steal", 30, 60, 10), _cell("fsteal", 50, 80, 10), _cell("3bet", 4, 12)]],
                 border="#a03c2c"),
        HudPanel(name="Profond", rows=[
            [StatCell("hands"), _cell("vpip", 18, 32), _cell("pfr", 12, 26), _cell("3bet", 4, 11)],
            [_cell("steal", 25, 55, 15), _cell("fsteal", 55, 85, 10), _cell("cbet_f", 45, 75, 12),
             _cell("wtsd", 22, 32, 20)]]),
    ]
    return p


BUILTIN_PROFILES = {p.name: p for p in (default_profile(), heads_up_profile(), mtt_profile())}
