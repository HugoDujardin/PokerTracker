"""Catalogue des statistiques affichables (HUD, popups, rapports).

Une statistique est definie par un numerateur et un denominateur exprimes
en compteurs (voir `counters.py`). `expr` accepte une somme de compteurs
separes par '+' pour construire des statistiques composites.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class StatDef:
    code: str                       # identifiant court (utilise par les profils HUD)
    label: str                      # libelle affiche
    num: str                        # compteur(s) du numerateur
    den: str                        # compteur(s) du denominateur
    category: str = "Preflop"
    fmt: str = "pct"                # pct | ratio | bb100 | int | money
    decimals: int = 0
    description: str = ""
    #: bornes indicatives (min, max) pour la coloration par defaut
    low: float = 0.0
    high: float = 100.0

    def value(self, agg: dict) -> Optional[float]:
        den = sum_expr(agg, self.den)
        num = sum_expr(agg, self.num)
        if self.fmt == "int":
            return num
        if den == 0:
            return None
        if self.fmt == "pct":
            return 100.0 * num / den
        if self.fmt == "bb100":
            return 100.0 * num / den
        if self.fmt == "ratio":
            return num / den
        if self.fmt == "money":
            return num
        return num / den

    def format(self, agg: dict) -> str:
        v = self.value(agg)
        if v is None:
            return "-"
        if self.fmt == "pct":
            return f"{v:.{self.decimals}f}"
        if self.fmt == "int":
            return f"{int(v)}"
        if self.fmt == "ratio":
            return f"{v:.2f}"
        if self.fmt == "bb100":
            return f"{v:+.1f}"
        if self.fmt == "money":
            return f"{v:+.2f}"
        return f"{v:.1f}"

    def sample(self, agg: dict) -> int:
        return int(sum_expr(agg, self.den))


def sum_expr(agg: dict, expr: str) -> float:
    """Somme algebrique de compteurs: 'a+b', 'bb_net-ev_bb'..."""
    total = 0.0
    sign = 1.0
    for token in re.split(r"([+-])", expr):
        token = token.strip()
        if not token:
            continue
        if token == "+":
            sign = 1.0
        elif token == "-":
            sign = -1.0
        else:
            total += sign * float(agg.get(token, 0) or 0)
            sign = 1.0
    return total


def _postflop_variants(base_code: str, base_label: str, num: str, den: str, category: str,
                       description: str) -> list[StatDef]:
    out = []
    for suffix, name in (("f", "Flop"), ("t", "Turn"), ("r", "River")):
        out.append(StatDef(
            code=f"{base_code}_{suffix}",
            label=f"{base_label} {name[0]}",
            num=num.format(s=suffix), den=den.format(s=suffix),
            category=category,
            description=f"{description} ({name.lower()})",
        ))
    return out


STATS: list[StatDef] = [
    # ------------------------------------------------------------- general
    StatDef("hands", "Mains", "hands", "hands", "General", "int",
            description="Nombre de mains observees pour ce joueur."),
    StatDef("bb100", "bb/100", "bb_net", "hands", "General", "bb100", 1,
            description="Gain moyen en grosses blindes pour 100 mains."),
    StatDef("net", "Gains", "amount_net", "hands", "General", "money",
            description="Gain net cumule dans la devise de la table."),
    StatDef("wr_hands", "% mains gagnees", "hands_won", "hands", "General",
            description="Pourcentage de mains remportees."),
    StatDef("ev_bb100", "bb/100 ajuste", "ev_bb", "hands", "General", "bb100", 1,
            description="Gain en bb/100 ajuste a l'equite: les all-in sont remplaces par "
                        "leur esperance mathematique."),
    StatDef("ev_net", "Gains ajustes", "ev_net", "hands", "General", "money",
            description="Gain net ajuste a l'equite des all-in."),
    StatDef("luck_bb", "Chance (bb)", "bb_net-ev_bb", "hands", "General", "money", 1,
            description="Ecart entre gains reels et gains ajustes a l'equite, en grosses "
                        "blindes: positif, les all-in ont ete favorables; negatif, defavorables."),
    StatDef("allin_ev_hands", "Mains all-in evaluees", "allin_ev_hands", "hands", "General",
            "int", description="Nombre de mains dont le resultat a ete ajuste a l'equite."),
    # ------------------------------------------------------------- preflop
    StatDef("vpip", "VPIP", "vpip", "vpip_opp", "Preflop",
            description="Voluntarily Put money In Pot: frequence d'entree volontaire dans le pot.",
            low=15, high=35),
    StatDef("pfr", "PFR", "pfr", "pfr_opp", "Preflop",
            description="Pre-Flop Raise: frequence de relance preflop.", low=10, high=28),
    StatDef("vpip_pfr", "VPIP/PFR gap", "vpip+pfr", "vpip_opp", "Preflop",
            description="Ecart passif/agressif preflop (indicatif)."),
    StatDef("rfi", "RFI", "rfi", "rfi_opp", "Preflop",
            description="Open raise quand le pot est encore non ouvert.", low=12, high=40),
    StatDef("limp", "Limp", "limp", "limp_opp", "Preflop",
            description="Suivre la grosse blinde sans relancer, pot non ouvert."),
    StatDef("limp_fold", "Limp/Fold", "limp_fold", "limp", "Preflop",
            description="Limper puis se coucher face a une relance."),
    StatDef("limp_call", "Limp/Call", "limp_call", "limp", "Preflop",
            description="Limper puis payer une relance."),
    StatDef("iso", "Iso raise", "iso_raise", "iso_opp", "Preflop",
            description="Relance d'isolement face a un ou plusieurs limpers."),
    StatDef("cc", "Cold call", "cold_call", "cold_call_opp", "Preflop",
            description="Payer une relance sans avoir encore investi volontairement."),
    StatDef("3bet", "3Bet", "three_bet", "three_bet_opp", "Preflop",
            description="Sur-relance face a une premiere relance.", low=4, high=12),
    StatDef("4bet", "4Bet", "four_bet", "four_bet_opp", "Preflop",
            description="Relance du relanceur initial face a un 3bet."),
    StatDef("cold4bet", "Cold 4Bet", "cold_4bet", "cold_4bet_opp", "Preflop",
            description="4bet sans avoir participe a l'action precedente."),
    StatDef("5bet", "5Bet", "five_bet", "five_bet_opp", "Preflop",
            description="Relance face a un 4bet."),
    StatDef("f3bet", "Fold to 3Bet", "fold_to_3bet", "fold_to_3bet_opp", "Preflop",
            description="Frequence d'abandon de l'open raise face a un 3bet.", low=40, high=70),
    StatDef("c3bet", "Call 3Bet", "call_3bet", "fold_to_3bet_opp", "Preflop",
            description="Frequence de call de l'open raiser face a un 3bet."),
    StatDef("f4bet", "Fold to 4Bet", "fold_to_4bet", "fold_to_4bet_opp", "Preflop",
            description="Frequence d'abandon du 3bet face a un 4bet."),
    StatDef("squeeze", "Squeeze", "squeeze", "squeeze_opp", "Preflop",
            description="3bet face a une relance suivie d'au moins un call."),
    StatDef("steal", "ATS", "steal", "steal_opp", "Preflop",
            description="Attempt To Steal: open raise depuis CO/BTN/SB pot non ouvert.",
            low=25, high=55),
    StatDef("fsteal", "Fold vs steal", "fold_to_steal", "fold_to_steal_opp", "Preflop",
            description="Frequence d'abandon des blindes face a une tentative de vol."),
    StatDef("resteal", "Resteal", "resteal", "resteal_opp", "Preflop",
            description="3bet des blindes face a une tentative de vol."),
    StatDef("callsteal", "Call vs steal", "call_vs_steal", "fold_to_steal_opp", "Preflop",
            description="Call des blindes face a une tentative de vol."),
    # ------------------------------------------------------------ postflop
    *_postflop_variants("cbet", "CBet", "cbet_{s}", "cbet_opp_{s}", "Postflop",
                        "Continuation bet de l'agresseur de la street precedente"),
    *_postflop_variants("fcbet", "Fold CB", "fold_to_cbet_{s}", "fold_to_cbet_opp_{s}", "Postflop",
                        "Abandon face au continuation bet"),
    *_postflop_variants("rcbet", "Raise CB", "raise_cbet_{s}", "fold_to_cbet_opp_{s}", "Postflop",
                        "Relance du continuation bet"),
    *_postflop_variants("donk", "Donk", "donk_{s}", "donk_opp_{s}", "Postflop",
                        "Mise dans l'agresseur avant qu'il ne parle"),
    *_postflop_variants("probe", "Probe", "probe_{s}", "probe_opp_{s}", "Postflop",
                        "Mise apres que l'agresseur a renonce a miser"),
    *_postflop_variants("dcbet", "Delayed CB", "dcbet_{s}", "dcbet_opp_{s}", "Postflop",
                        "Continuation bet retarde apres une street checkee"),
    *_postflop_variants("fbet", "Fold vs bet", "fold_to_bet_{s}", "fold_to_bet_opp_{s}", "Postflop",
                        "Abandon face a une mise"),
    *_postflop_variants("xr", "Check-raise", "checkraise_{s}", "checkraise_opp_{s}", "Postflop",
                        "Check-raise"),
    StatDef("af", "AF", "bet_f+raise_f+bet_t+raise_t+bet_r+raise_r",
            "call_f+call_t+call_r", "Postflop", "ratio",
            description="Aggression Factor: (mises + relances) / calls postflop."),
    StatDef("afq", "AFq", "bet_f+raise_f+bet_t+raise_t+bet_r+raise_r",
            "bet_f+raise_f+bet_t+raise_t+bet_r+raise_r+call_f+call_t+call_r+fold_f+fold_t+fold_r",
            "Postflop", description="Frequence d'agression postflop."),
    StatDef("wwsf", "WWSF", "wwsf", "wwsf_opp", "Postflop",
            description="Won When Saw Flop: pot gagne apres avoir vu le flop.", low=42, high=52),
    StatDef("wtsd", "WTSD", "wtsd", "wtsd_opp", "Showdown",
            description="Went To ShowDown apres avoir vu le flop.", low=22, high=32),
    StatDef("wsd", "W$SD", "wsd", "wsd_opp", "Showdown",
            description="Won money at ShowDown.", low=48, high=58),
    StatDef("sawflop", "Saw flop", "saw_flop", "hands", "Postflop",
            description="Frequence a laquelle le joueur voit le flop."),
]

STATS_BY_CODE = {s.code: s for s in STATS}
CATEGORIES = ["General", "Preflop", "Postflop", "Showdown"]


def get(code: str) -> Optional[StatDef]:
    return STATS_BY_CODE.get(code)


def by_category(category: str) -> list[StatDef]:
    return [s for s in STATS if s.category == category]


#: statistiques proposees par defaut dans un panneau HUD
DEFAULT_HUD_STATS = ["hands", "vpip", "pfr", "3bet", "f3bet", "steal", "af", "wtsd"]
