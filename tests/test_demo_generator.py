"""Le generateur de mains de demonstration doit produire un fichier lisible."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from generate_demo_hands import generate  # noqa: E402

from pokertracker.core.parsers import registry  # noqa: E402
from pokertracker.core.stats import definitions as sd  # noqa: E402


def test_mains_generees_relisibles(db):
    hands = list(registry.parse_text(generate(120, seed=3)))
    assert len(hands) == 120
    assert db.insert_hands(hands) == 120
    agg = db.aggregate_many(["Maniac_88", "Nitrogen"], room="PokerStars")
    # les styles simules doivent se distinguer nettement
    maniac = sd.get("vpip").value(agg["Maniac_88"])
    nit = sd.get("vpip").value(agg["Nitrogen"])
    assert maniac > nit + 20
    assert all(h.seats and h.board for h in hands)
