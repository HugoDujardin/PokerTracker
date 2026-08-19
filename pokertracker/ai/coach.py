"""Coach IA: analyse d'un coup precis ou des statistiques d'un joueur.

Le contexte envoye au modele est construit ici, en clair et sans donnees
superflues: description de la main (positions, tapis, actions street par
street, cote du pot, equite) ou tableau de statistiques avec la taille
d'echantillon de chacune.

L'appel passe par le SDK officiel Anthropic. La cle d'API n'est jamais
stockee en dur: elle vient de la variable d'environnement
ANTHROPIC_API_KEY ou des reglages de l'application.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from ..core.equity.equity import equity, pot_odds
from ..core.models import Action, ActionType, Hand, Street
from ..core.stats import definitions as sd

#: modele par defaut (le plus capable de la famille Claude 5)
DEFAULT_MODEL = "claude-opus-5"
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]

SYSTEM_PROMPT = """Tu es un coach de poker expert (No Limit Hold'em et Omaha), \
qui s'adresse a un joueur en francais.

Regles de reponse:
- Appuie-toi uniquement sur les donnees fournies; si une information manque, dis-le.
- Tiens compte de la taille d'echantillon: une statistique sur moins de 30 \
observations est indicative, sous 100 elle reste fragile.
- Sois concret et hierarchise: commence par ce qui coute le plus de jetons.
- Donne des recommandations actionnables (frequences, tailles de mise, ranges), \
pas des generalites.
- Reste concis: 200 a 400 mots, en listes courtes.
- Le poker comporte une part de variance: ne promets jamais un resultat."""

STAT_GROUPS = {
    "Preflop": ["hands", "vpip", "pfr", "rfi", "limp", "cc", "3bet", "4bet", "f3bet", "squeeze",
                "steal", "fsteal", "resteal"],
    "Postflop": ["cbet_f", "fcbet_f", "cbet_t", "fcbet_t", "donk_f", "probe_t", "xr_f", "af",
                 "afq", "wwsf"],
    "Abattage": ["wtsd", "wsd"],
    "Resultats": ["bb100", "ev_bb100", "net", "allin_ev_hands"],
}


class CoachError(RuntimeError):
    """Erreur d'appel a l'assistant (cle manquante, reseau, quota...)."""


@dataclass
class CoachConfig:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 16000
    temperature: Optional[float] = None      # non utilise par les modeles Claude 5

    def resolved_key(self) -> str:
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")


# ---------------------------------------------------------------------------
# Construction du contexte
# ---------------------------------------------------------------------------

def _format_action(action: Action, bb: Decimal) -> str:
    labels = {
        ActionType.FOLD: "se couche", ActionType.CHECK: "check", ActionType.CALL: "suit",
        ActionType.BET: "mise", ActionType.RAISE: "relance a", ActionType.POST_SB: "SB",
        ActionType.POST_BB: "BB", ActionType.POST_ANTE: "ante",
        ActionType.POST_STRADDLE: "straddle", ActionType.POST_DEAD: "blinde morte",
        ActionType.SHOW: "abat", ActionType.MUCK: "jette", ActionType.COLLECT: "encaisse",
        ActionType.UNCALLED: "recupere",
    }
    label = labels.get(action.type, action.type.value)
    amount = action.to_amount if action.type is ActionType.RAISE else action.amount
    if amount:
        in_bb = float(amount) / float(bb or 1)
        return f"{action.player} {label} {amount} ({in_bb:.1f}bb)"
    return f"{action.player} {label}"


def build_hand_context(hand: Hand, stats: Optional[Dict[str, dict]] = None,
                       with_equity: bool = True) -> str:
    """Decrit une main de facon compacte et lisible par le modele."""
    bb = hand.big_blind() or Decimal(1)
    lines: List[str] = [
        f"Room: {hand.room} | Format: {hand.table_format.value} | Jeu: {hand.game.value}",
        f"Blindes: {hand.sb}/{hand.bb} {hand.currency}"
        + (f" (ante {hand.ante})" if hand.ante else ""),
        f"Table: {hand.table_name} | {hand.nb_players} joueurs | date {hand.played_at:%d/%m/%Y %H:%M}",
        "",
        "Sieges (position, tapis en bb, cartes connues):",
    ]
    for seat in sorted(hand.seats, key=lambda s: s.seat_no):
        cards = " ".join(seat.cards) if seat.cards else "?"
        marker = " [HEROS]" if seat.is_hero else ""
        lines.append(f"  - {seat.player}{marker}: {seat.position}, "
                     f"{float(seat.stack) / float(bb):.0f}bb, cartes {cards}")

    lines.append("")
    for street in (Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER):
        actions = [a for a in hand.actions if a.street == street]
        if not actions:
            continue
        board = hand.board_of(street)
        titre = street.value.upper() + (f" [{' '.join(board)}]" if board else "")
        lines.append(titre)
        for action in actions:
            if action.type in (ActionType.COLLECT, ActionType.UNCALLED, ActionType.SHOW,
                               ActionType.MUCK):
                continue
            lines.append("  " + _format_action(action, bb))

    lines.append("")
    lines.append(f"Pot final: {hand.pot} {hand.currency} (rake {hand.rake})")
    for seat in hand.seats:
        if seat.net:
            lines.append(f"  Resultat {seat.player}: {float(seat.net):+.2f} "
                         f"({float(seat.net) / float(bb):+.1f}bb)")

    hero = next((s for s in hand.seats if s.is_hero), None)
    if with_equity and hero and len(hero.cards) == 2:
        adversaires = [s for s in hand.seats if s is not hero and len(s.cards) == 2]
        if adversaires:
            # equite a chaque etape: c'est la donnee qui manque le plus pour
            # juger une decision (elle change a chaque carte)
            for street in (Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER):
                if not hand.reached(street):
                    continue
                board = hand.board_of(street)
                result = equity([list(hero.cards)] + [list(s.cards) for s in adversaires],
                                board=board, iterations=2000, seed=1)
                parts = [f"{hero.player} {result.as_percent()[0]:.1f}%"]
                parts += [f"{s.player} {p:.1f}%"
                          for s, p in zip(adversaires, result.as_percent()[1:])]
                lines.append(f"Equite {street.value}: " + ", ".join(parts))

    if stats:
        lines.append("")
        lines.append("Statistiques des joueurs presents (valeur, echantillon):")
        for name, agg in stats.items():
            if not agg or not agg.get("hands"):
                continue
            resume = []
            for code in ("hands", "vpip", "pfr", "3bet", "f3bet", "cbet_f", "wtsd", "af"):
                stat = sd.get(code)
                if stat:
                    resume.append(f"{stat.label} {stat.format(agg)} (n={stat.sample(agg)})")
            lines.append(f"  - {name}: " + ", ".join(resume))
    return "\n".join(lines)


def build_stats_context(agg: dict, by_position: Optional[Dict[str, dict]] = None,
                        label: str = "Joueur") -> str:
    """Tableau de statistiques pret a analyser."""
    lines = [f"Statistiques de {label} sur {int(agg.get('hands', 0) or 0)} mains", ""]
    for titre, codes in STAT_GROUPS.items():
        entries = []
        for code in codes:
            stat = sd.get(code)
            if stat is None:
                continue
            value = stat.format(agg)
            if value == "-":
                continue
            entries.append(f"{stat.label}: {value} (n={stat.sample(agg)})")
        if entries:
            lines.append(f"{titre} — " + " | ".join(entries))
    if by_position:
        lines.append("")
        lines.append("Par position (VPIP / PFR / 3Bet / mains):")
        for position, values in by_position.items():
            if not values.get("hands"):
                continue
            lines.append(f"  - {position}: {sd.get('vpip').format(values)} / "
                         f"{sd.get('pfr').format(values)} / {sd.get('3bet').format(values)} / "
                         f"{int(values['hands'])} mains")
    return "\n".join(lines)


def hand_question(question: str = "") -> str:
    return question.strip() or (
        "Analyse ce coup du point de vue du HEROS: street par street, dis si la ligne est "
        "correcte, quelles alternatives etaient meilleures et pourquoi (equite, cote du pot, "
        "range adverse). Termine par la principale lecon a retenir.")


def stats_question(question: str = "") -> str:
    return question.strip() or (
        "Analyse ces statistiques: identifie les trois fuites les plus couteuses, explique "
        "pourquoi elles coutent des jetons, et propose pour chacune un ajustement concret. "
        "Signale les statistiques dont l'echantillon est trop faible pour conclure.")


# ---------------------------------------------------------------------------
# Appel du modele
# ---------------------------------------------------------------------------

class PokerCoach:
    """Client de l'assistant, base sur le SDK officiel Anthropic."""

    def __init__(self, config: Optional[CoachConfig] = None, client=None) -> None:
        self.config = config or CoachConfig()
        self._client = client            # injectable pour les tests

    # ------------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        """(pret, raison) — permet a l'interface d'expliquer ce qui manque."""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, ("Le module « anthropic » n'est pas installe. "
                           "Lancez: pip install anthropic")
        if not self.config.resolved_key():
            return False, ("Aucune cle d'API. Renseignez-la dans l'onglet Coach IA ou "
                           "definissez la variable d'environnement ANTHROPIC_API_KEY.")
        return True, ""

    def client(self):
        if self._client is not None:
            return self._client
        ok, reason = self.available()
        if not ok:
            raise CoachError(reason)
        import anthropic

        self._client = anthropic.Anthropic(api_key=self.config.resolved_key())
        return self._client

    # ------------------------------------------------------------------
    def ask(self, context: str, question: str,
            on_chunk: Optional[Callable[[str], None]] = None,
            stop: Optional[Callable[[], bool]] = None) -> str:
        """Envoie le contexte et la question, en streaming.

        `on_chunk` recoit le texte au fil de l'eau (affichage progressif),
        `stop` permet d'interrompre depuis l'interface.
        """
        client = self.client()
        prompt = f"{context}\n\n---\n\n{question}"
        pieces: List[str] = []
        try:
            with client.messages.stream(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                output_config={"effort": self.config.effort},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    pieces.append(text)
                    if on_chunk:
                        on_chunk(text)
                    if stop and stop():
                        break
                else:
                    final = stream.get_final_message()
                    if final.stop_reason == "refusal":
                        raise CoachError("Le modele a refuse de repondre a cette demande.")
        except CoachError:
            raise
        except Exception as exc:                      # erreurs reseau, quota, cle invalide
            raise CoachError(f"Appel a l'assistant impossible: {exc}") from exc
        return "".join(pieces)

    # ------------------------------------------------------------------
    def analyse_hand(self, hand: Hand, stats: Optional[Dict[str, dict]] = None,
                     question: str = "", **kwargs) -> str:
        return self.ask(build_hand_context(hand, stats), hand_question(question), **kwargs)

    def analyse_stats(self, agg: dict, by_position: Optional[Dict[str, dict]] = None,
                      label: str = "Joueur", question: str = "", **kwargs) -> str:
        return self.ask(build_stats_context(agg, by_position, label), stats_question(question),
                        **kwargs)
