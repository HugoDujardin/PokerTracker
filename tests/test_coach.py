"""Coach IA: fournisseurs, contextes et analyses pretes a l'emploi."""
import pytest

from conftest import DATA, load
from pokertracker.ai.analyses import (hand_analysis, last_hand_analysis,
                                      last_tournament_analysis, stats_analysis)
from pokertracker.ai.coach import (CoachConfig, CoachError, PokerCoach, build_hand_context,
                                   build_stats_context)
from pokertracker.ai.providers import (AnthropicProvider, GeminiProvider, ProviderConfig,
                                       ProviderError, get_provider)
from pokertracker.core.parsers.summaries import parse_summaries


# ----------------------------------------------------------------- Gemini
class FakeChunk:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, morceaux, erreur=None):
        self.morceaux = morceaux
        self.erreur = erreur
        self.kwargs = None

    def generate_content_stream(self, **kwargs):
        self.kwargs = kwargs
        if self.erreur:
            raise self.erreur
        return iter([FakeChunk(m) for m in self.morceaux])

    def list(self):
        class Model:
            def __init__(self, name):
                self.name = name
                self.supported_actions = ["generateContent"]
        return [Model("models/gemini-2.5-flash"), Model("models/gemini-2.5-pro"),
                Model("models/embedding-001")]


class FakeGeminiClient:
    def __init__(self, morceaux, erreur=None):
        self.models = FakeModels(morceaux, erreur)


def gemini_coach(morceaux, erreur=None, **config):
    provider = GeminiProvider(client=FakeGeminiClient(morceaux, erreur))
    return PokerCoach(CoachConfig(api_key="test", **config), provider=provider)


def test_gemini_est_le_fournisseur_par_defaut():
    coach = PokerCoach(CoachConfig())
    assert coach.provider().name == "gemini"
    assert coach.provider().free_tier is True
    assert coach.config.provider_impl().default_model.startswith("gemini")


def test_appel_gemini_en_streaming(ps_hands):
    coach = gemini_coach(["Analyse ", "du ", "coup."])
    recus = []
    texte = coach.ask("contexte", "question", on_chunk=recus.append)
    assert texte == "Analyse du coup."
    assert recus == ["Analyse ", "du ", "coup."]
    envoye = coach.provider()._client.models.kwargs
    assert envoye["model"] == "gemini-2.5-flash"
    assert "contexte" in envoye["contents"] and "question" in envoye["contents"]
    assert envoye["config"].system_instruction.startswith("Tu es un coach de poker")


def test_analyse_rapide_desactive_la_reflexion():
    coach = gemini_coach(["ok"], deep_analysis=False)
    coach.ask("contexte", "question")
    assert coach.provider()._client.models.kwargs["config"].thinking_config.thinking_budget == 0
    coach = gemini_coach(["ok"], deep_analysis=True)
    coach.ask("contexte", "question")
    assert coach.provider()._client.models.kwargs["config"].thinking_config.thinking_budget == -1


def test_interruption():
    coach = gemini_coach(["un ", "deux ", "trois"])
    assert coach.ask("contexte", "question", stop=lambda: True) == "un "


def test_message_de_quota_lisible():
    coach = gemini_coach([], erreur=RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"))
    with pytest.raises(CoachError) as exc:
        coach.ask("contexte", "question")
    assert "Quota atteint" in str(exc.value)


def test_reponse_vide_signalee():
    coach = gemini_coach([])
    with pytest.raises(CoachError):
        coach.ask("contexte", "question")


def test_liste_des_modeles_du_compte():
    coach = gemini_coach(["ok"])
    assert coach.models() == ["gemini-2.5-flash", "gemini-2.5-pro"]   # embeddings ecartes


def test_cle_absente(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ok, raison = PokerCoach(CoachConfig()).available()
    assert not ok and "cle d'API" in raison


def test_cle_depuis_l_environnement(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "cle-test")
    ok, raison = PokerCoach(CoachConfig()).available()
    assert ok and raison == ""


def test_fournisseur_anthropic_toujours_disponible(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-test")
    coach = PokerCoach(CoachConfig(provider="anthropic"))
    assert coach.provider().name == "anthropic"
    assert coach.available()[0]
    assert get_provider("inconnu").name == "gemini"      # repli sur le gratuit


# ---------------------------------------------------------------- contextes
def test_contexte_de_main(ps_hands):
    contexte = build_hand_context(ps_hands[1])
    assert "PREFLOP" in contexte and "FLOP [Qd 8h 3c]" in contexte
    assert "Hero [HEROS]: UTG" in contexte
    assert "relance a 6.00 (12.0bb)" in contexte
    assert "Equite preflop:" in contexte and "Equite flop:" in contexte


def test_contexte_de_statistiques(db, ps_hands):
    db.insert_hands(ps_hands)
    pid = db.player_id("Hero", "PokerStars")
    contexte = build_stats_context(db.aggregate([pid]),
                                   db.aggregate([pid], group_by="hp.position"), "Hero")
    assert "Statistiques de Hero sur 2 mains" in contexte
    assert "Par position" in contexte


# ----------------------------------------------------------------- analyses
def _tournament_db(db):
    db.insert_hands(load("pokerstars_mtt"))
    db.insert_tournaments(parse_summaries((DATA / "ps_summary.txt").read_text(encoding="utf-8")))
    return db.player_id("Hero", "PokerStars")


def test_analyse_du_dernier_tournoi(db):
    hero = _tournament_db(db)
    analyse = last_tournament_analysis(db, hero)
    assert analyse is not None
    assert "TOURNOI" in analyse.context
    assert "Place finale" in analyse.context
    assert "bilan de ce tournoi" in analyse.question
    assert analyse.subtitle


def test_analyse_de_tournoi_contient_les_coups_marquants(db):
    hero = _tournament_db(db)
    tournoi = [t for t in db.tournaments() if t["tournament_id"] == "3000000001"][0]
    from pokertracker.ai.analyses import tournament_analysis
    analyse = tournament_analysis(db, tournoi, hero)
    assert "Statistiques du heros sur ce tournoi" in analyse.context
    assert "Coups marquants" in analyse.context
    assert "Ac Qh" in analyse.context                # la main jouee est bien decrite
    assert not analyse.empty()


def test_analyse_du_dernier_coup(db, ps_hands):
    db.insert_hands(ps_hands)
    hero = db.player_id("Hero", "PokerStars")
    analyse = last_hand_analysis(db, hero)
    assert analyse is not None and "PREFLOP" in analyse.context
    assert "HEROS" in analyse.question


def test_analyse_avec_question_personnalisee(db, ps_hands):
    db.insert_hands(ps_hands)
    analyse = hand_analysis(db, ps_hands[1], "fallait-il payer la river ?")
    assert analyse.question == "fallait-il payer la river ?"


def test_analyse_de_statistiques(db, ps_hands):
    db.insert_hands(ps_hands)
    analyse = stats_analysis(db, db.player_id("Hero", "PokerStars"), "Hero")
    assert "Statistiques de Hero" in analyse.context
    assert "fuites" in analyse.question


def test_aucun_tournoi(db):
    assert last_tournament_analysis(db, None) is None
