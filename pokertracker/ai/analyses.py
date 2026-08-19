"""Analyses pretes a l'emploi du coach.

Chaque fonction assemble un contexte et une question a partir de la base:
l'interface n'a plus qu'a proposer un bouton par analyse.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..core.db import Database, Filter
from ..core.models import Hand
from ..core.parsers import registry
from ..core.stats import definitions as sd
from .coach import build_hand_context, build_stats_context

FORMAT_LABELS = {"mtt": "MTT", "sng": "Sit & Go", "spin": "Spin / Expresso", "cash": "Cash game"}

#: statistiques resumees dans le bilan d'un tournoi
TOURNAMENT_STATS = ["hands", "vpip", "pfr", "3bet", "f3bet", "steal", "fsteal", "cbet_f",
                    "fcbet_f", "wtsd", "wsd", "af"]


@dataclass
class Analysis:
    """Un contexte pret a etre envoye au modele."""
    title: str
    context: str
    question: str
    subtitle: str = ""

    def empty(self) -> bool:
        return not self.context.strip()


def _hand_from_row(row) -> Optional[Hand]:
    hands = list(registry.parse_text(row["raw_text"] or ""))
    return hands[0] if hands else None


# ---------------------------------------------------------------- tournoi
def tournament_analysis(db: Database, tournament, player_id: Optional[int] = None,
                        question: str = "", max_hands: int = 6) -> Analysis:
    """Bilan complet d'un tournoi: resultat, statistiques et coups marquants."""
    room = tournament["room"]
    tid = tournament["tournament_id"]
    nom = tournament["name"] or tid
    place = tournament["finish_place"] or 0
    entrants = tournament["entrants"] or 0
    lignes: List[str] = [
        f"TOURNOI {nom} ({FORMAT_LABELS.get(tournament['fmt'], tournament['fmt'] or 'MTT')}) "
        f"sur {room}",
        f"Date: {(tournament['started_at'] or '').replace('T', ' ')}",
        f"Buy-in total: {tournament['cost']:.2f} {tournament['currency'] or ''} "
        f"(dont {tournament['fee']:.2f} de frais"
        + (f", {tournament['bounty_buyin']:.2f} de prime" if tournament["bounty_buyin"] else "")
        + ")",
        f"Participants: {entrants or 'inconnu'}",
        f"Place finale: {place or 'inconnue'}"
        + (f" ({100.0 * place / entrants:.0f}% du champ)" if place and entrants else ""),
        f"Gains: {tournament['won']:.2f} (dont primes {tournament['bounty_won']:.2f}) "
        f"| Profit: {tournament['profit']:+.2f}",
        "Dans les places payees: " + ("oui" if tournament["itm"] else "non")
        + (" — elimine sur la bulle (estimation)" if tournament["bubble"] else ""),
    ]

    if player_id:
        flt = Filter(tournament_ids=[tid], rooms=[room], money="all")
        agg = db.aggregate([player_id], flt)
        if agg.get("hands"):
            lignes.append("")
            lignes.append("Statistiques du heros sur ce tournoi:")
            resume = []
            for code in TOURNAMENT_STATS:
                stat = sd.get(code)
                if stat is None:
                    continue
                valeur = stat.format(agg)
                if valeur == "-":
                    continue
                resume.append(f"{stat.label} {valeur} (n={stat.sample(agg)})")
            lignes.append("  " + " | ".join(resume))

        rows = db.tournament_hands(room, tid, player_id)
        if rows:
            debut = rows[0]["stack_bb"] or 0
            lignes.append(f"  Tapis de depart connu: {debut:.0f}bb "
                          f"| mains jouees: {len(rows)}")
            marquantes = sorted(rows, key=lambda r: abs(r["net"] or 0), reverse=True)[:max_hands]
            derniere = rows[-1]
            if derniere["hand_id"] not in {r["hand_id"] for r in marquantes}:
                marquantes.append(derniere)
            lignes.append("")
            lignes.append("Coups marquants (du plus gros pot au plus petit, puis la derniere "
                          "main jouee):")
            for row in marquantes:
                hand = _hand_from_row(row)
                if hand is None:
                    continue
                lignes.append("")
                lignes.append(build_hand_context(hand, with_equity=False))
    lignes.append("")
    return Analysis(
        title=f"Tournoi {nom}",
        subtitle=f"{(tournament['started_at'] or '')[:10]} · place {place or '?'}"
                 f"/{entrants or '?'} · profit {tournament['profit']:+.2f}",
        context="\n".join(lignes),
        question=question.strip() or (
            "Fais le bilan de ce tournoi pour le heros: qualite du jeu preflop et postflop "
            "au vu des statistiques, analyse des coups marquants (etait-ce des spots corrects "
            "compte tenu des tapis et de la structure ?), et gestion de la fin de tournoi. "
            "Termine par les deux ajustements les plus rentables pour les prochains tournois."),
    )


def last_tournament_analysis(db: Database, player_id: Optional[int] = None,
                             question: str = "") -> Optional[Analysis]:
    tournament = db.last_tournament()
    if tournament is None:
        return None
    return tournament_analysis(db, tournament, player_id, question)


# ------------------------------------------------------------------- main
def hand_analysis(db: Database, hand: Hand, question: str = "") -> Analysis:
    stats = db.aggregate_many([s.player for s in hand.seats], room=hand.room)
    hero = next((s.player for s in hand.seats if s.is_hero), "")
    return Analysis(
        title="Analyse d'un coup",
        subtitle=f"{hand.room} · {hand.table_name} · {hand.played_at:%d/%m/%Y %H:%M}"
                 + (f" · {hero}" if hero else ""),
        context=build_hand_context(hand, stats),
        question=question.strip() or (
            "Analyse ce coup du point de vue du HEROS: street par street, dis si la ligne est "
            "correcte, quelles alternatives etaient meilleures et pourquoi (equite, cote du "
            "pot, range adverse, statistiques de l'adversaire). Termine par la lecon a retenir."),
    )


def last_hand_analysis(db: Database, player_id: int, question: str = "") -> Optional[Analysis]:
    rows = db.hands_of_player(player_id, limit=1)
    if not rows:
        return None
    row = db.hand_by_id(rows[0]["id"])
    hand = _hand_from_row(row) if row else None
    return hand_analysis(db, hand, question) if hand else None


# ------------------------------------------------------------ statistiques
def stats_analysis(db: Database, player_id: int, label: str = "", question: str = "",
                   flt: Optional[Filter] = None) -> Analysis:
    agg = db.aggregate([player_id], flt)
    positions = db.aggregate([player_id], flt, group_by="hp.position")
    return Analysis(
        title="Analyse des statistiques",
        subtitle=f"{label} · {int(agg.get('hands', 0) or 0)} mains",
        context=build_stats_context(agg, positions, label or "le joueur"),
        question=question.strip() or (
            "Analyse ces statistiques: identifie les trois fuites les plus couteuses, explique "
            "pourquoi elles coutent des jetons, et propose pour chacune un ajustement concret. "
            "Signale les statistiques dont l'echantillon est trop faible pour conclure."),
    )
