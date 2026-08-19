"""Coach IA: construction du contexte et appel du modele (client simule)."""
import pytest

from conftest import load
from pokertracker.ai.coach import (CoachConfig, CoachError, PokerCoach, build_hand_context,
                                   build_stats_context, hand_question, stats_question)


class FakeStream:
    """Imite le gestionnaire de contexte renvoye par client.messages.stream."""

    def __init__(self, morceaux, stop_reason="end_turn"):
        self.morceaux = morceaux
        self.stop_reason = stop_reason
        self.captured = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(self.morceaux)

    def get_final_message(self):
        class Message:
            stop_reason = self.stop_reason
        return Message()


class FakeMessages:
    def __init__(self, morceaux, stop_reason="end_turn"):
        self.morceaux = morceaux
        self.stop_reason = stop_reason
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self.morceaux, self.stop_reason)


class FakeClient:
    def __init__(self, morceaux, stop_reason="end_turn"):
        self.messages = FakeMessages(morceaux, stop_reason)


def test_contexte_de_main(ps_hands):
    contexte = build_hand_context(ps_hands[1])
    assert "PREFLOP" in contexte and "FLOP [Qd 8h 3c]" in contexte
    assert "Hero [HEROS]: UTG" in contexte
    assert "relance a 6.00 (12.0bb)" in contexte      # montants aussi en grosses blindes
    assert "Equite preflop:" in contexte and "Equite flop:" in contexte
    assert "Pot final: 89.75" in contexte


def test_contexte_de_main_avec_stats(db, ps_hands):
    db.insert_hands(ps_hands)
    stats = db.aggregate_many(["Hero", "Villain2"], room="PokerStars")
    contexte = build_hand_context(ps_hands[1], stats)
    assert "Statistiques des joueurs presents" in contexte
    assert "VPIP" in contexte and "n=2" in contexte


def test_contexte_de_statistiques(db, ps_hands):
    db.insert_hands(ps_hands)
    pid = db.player_id("Hero", "PokerStars")
    contexte = build_stats_context(db.aggregate([pid]),
                                   db.aggregate([pid], group_by="hp.position"), "Hero")
    assert "Statistiques de Hero sur 2 mains" in contexte
    assert "Preflop —" in contexte and "Par position" in contexte
    assert "UTG" in contexte


def test_questions_par_defaut():
    assert "HEROS" in hand_question()
    assert hand_question("pourquoi ce call ?") == "pourquoi ce call ?"
    assert "fuites" in stats_question()


def test_appel_en_streaming(ps_hands):
    client = FakeClient(["Analyse ", "du ", "coup."])
    coach = PokerCoach(CoachConfig(api_key="test", effort="medium"), client=client)
    recus = []
    texte = coach.analyse_hand(ps_hands[1], on_chunk=recus.append)
    assert texte == "Analyse du coup."
    assert recus == ["Analyse ", "du ", "coup."]
    envoye = client.messages.kwargs
    assert envoye["model"] == "claude-opus-5"
    assert envoye["thinking"] == {"type": "adaptive"}
    assert envoye["output_config"] == {"effort": "medium"}
    assert "PREFLOP" in envoye["messages"][0]["content"]


def test_interruption(ps_hands):
    client = FakeClient(["un ", "deux ", "trois"])
    coach = PokerCoach(CoachConfig(api_key="test"), client=client)
    texte = coach.ask("contexte", "question", stop=lambda: True)
    assert texte == "un "                       # arret des le premier morceau


def test_refus_du_modele(ps_hands):
    client = FakeClient(["..."], stop_reason="refusal")
    coach = PokerCoach(CoachConfig(api_key="test"), client=client)
    with pytest.raises(CoachError):
        coach.ask("contexte", "question")


def test_cle_absente(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ok, raison = PokerCoach(CoachConfig()).available()
    assert not ok and "cle d'API" in raison


def test_cle_depuis_l_environnement(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    ok, raison = PokerCoach(CoachConfig()).available()
    assert ok and raison == ""
