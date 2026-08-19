"""Tests des parsers d'historiques."""
from decimal import Decimal

import pytest

from conftest import load
from pokertracker.core.models import ActionType, GameType, TableFormat
from pokertracker.core.parsers import registry
from pokertracker.core.parsers.base import to_decimal


@pytest.mark.parametrize("name,room,count", [
    ("pokerstars_cash", "PokerStars", 2),
    ("winamax_cash", "Winamax", 1),
    ("ggpoker_cash", "GGPoker", 1),
    ("partypoker_cash", "PartyPoker", 1),
    ("pokerstars_mtt", "PokerStars", 1),
])
def test_detection_et_nombre_de_mains(name, room, count):
    hands = load(name)
    assert len(hands) == count
    assert all(h.room == room for h in hands)


def test_pokerstars_details(ps_hands):
    hand = ps_hands[0]
    assert hand.hand_id == "241234567890"
    assert hand.game is GameType.NLHE
    assert hand.table_format is TableFormat.CASH
    assert (hand.sb, hand.bb) == (Decimal("0.25"), Decimal("0.50"))
    assert hand.button_seat == 4
    assert hand.hero == "Hero"
    assert hand.board == ["7h", "2c", "Ts", "Qd", "3h"]
    assert hand.seat_of("Hero").cards == ("Ah", "Kd")
    assert hand.seat_of("Villain2").position == "CO"
    assert hand.seat_of("Hero").invested == Decimal("7.50")
    assert hand.seat_of("Villain2").net == Decimal("7.75")


def test_raise_converti_en_montant_paye(ps_hands):
    """'raises 4.50 to 6.00' ne doit compter que ce qui est reellement mise."""
    hand = ps_hands[1]
    raises = [a for a in hand.actions if a.type is ActionType.RAISE and a.player == "Hero"]
    assert raises[0].to_amount == Decimal("1.50")
    assert hand.seat_of("Hero").invested == Decimal("44.50")


def test_positions_six_max(ps_hands):
    positions = {s.player: s.position for s in ps_hands[0].seats}
    assert positions == {"Villain3": "BTN", "Villain4": "SB", "Villain5": "BB",
                         "Villain1": "UTG", "Hero": "MP", "Villain2": "CO"}


def test_tournoi_avec_antes():
    hand = load("pokerstars_mtt")[0]
    assert hand.table_format is TableFormat.MTT
    assert hand.tournament_id == "3000000001"
    assert hand.buyin == Decimal("11")   # 10 + 1 de frais
    antes = [a for a in hand.actions if a.type is ActionType.POST_ANTE]
    assert len(antes) == 5 and antes[0].amount == Decimal("100")
    assert hand.seat_of("Sitrus").invested == Decimal("16500")
    assert hand.seat_of("Sitrus").won == Decimal("26100")


def test_winamax_gains_depuis_le_resume():
    hand = load("winamax_cash")[0]
    assert hand.currency == "EUR"
    assert hand.seat_of("Hero").won == Decimal("1.20")   # 0.75 du pot + 0.45 non paye
    assert hand.seat_of("Hero").net == Decimal("0.45")


def test_partypoker_montants_totaux():
    hand = load("partypoker_cash")[0]
    assert hand.seat_of("Hero").invested == Decimal("3.50")
    assert hand.seat_of("Beta").invested == Decimal("1.50")


def test_montants_localises():
    assert to_decimal("1 234,56") == Decimal("1234.56")
    assert to_decimal("$1,234.56") == Decimal("1234.56")
    assert to_decimal("0,10€") == Decimal("0.10")
    assert to_decimal("") == Decimal(0)
    assert to_decimal(None) == Decimal(0)


def test_texte_inconnu_ignore():
    assert list(registry.parse_text("ceci n'est pas un historique")) == []


def test_main_incomplete_non_consommee(data_dir):
    """Une main encore en cours d'ecriture ne doit pas etre importee."""
    text = (data_dir / "pokerstars_cash.txt").read_text(encoding="utf-8")
    parser = registry.detect(text)
    tronque = text[: text.index("*** SUMMARY ***", text.index("241234567891"))]
    assert parser.complete_length(tronque) < len(tronque)
    assert parser.complete_length(text + "\n\n") >= len(text)


def test_date_localisee_et_non_date_d_import(data_dir):
    """Une date en francais doit etre lue, jamais remplacee par aujourd'hui."""
    from datetime import datetime
    text = (data_dir / "partypoker_cash.txt").read_text(encoding="utf-8")
    francais = text.replace("Monday, January 15, 20:31:05 CET 2024",
                            "lundi, janvier 15, 20:31:05 CET 2024")
    hands = list(registry.parse_text(francais))
    assert len(hands) == 1
    assert hands[0].played_at == datetime(2024, 1, 15, 20, 31, 5)


def test_date_illisible_rejetee(data_dir):
    """Plutot que de dater la main du jour de l'import, elle est refusee."""
    text = (data_dir / "partypoker_cash.txt").read_text(encoding="utf-8")
    casse = text.replace("Monday, January 15, 20:31:05 CET 2024", "date inconnue")
    assert list(registry.parse_text(casse)) == []


def test_formats_de_date():
    from datetime import datetime
    from pokertracker.core.parsers.dates import parse_datetime
    attendu = datetime(2024, 1, 15, 20, 31, 5)
    for texte in ("2024/01/15 20:31:05", "15/01/2024 20:31:05",
                  "Monday, January 15, 20:31:05 CET 2024",
                  "lundi, janvier 15, 20:31:05 CET 2024",
                  "lundi 15 janvier 2024 20:31:05",
                  "Montag, Januar 15, 20:31:05 CET 2024"):
        assert parse_datetime(texte) == attendu, texte
    assert parse_datetime("n'importe quoi") is None
