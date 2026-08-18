import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from pokertracker.core.db import Database
from pokertracker.core.parsers import registry

DATA = Path(__file__).parent / "data"


def load(name: str):
    return list(registry.parse_text((DATA / f"{name}.txt").read_text(encoding="utf-8")))


@pytest.fixture
def data_dir() -> Path:
    return DATA


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def ps_hands():
    return load("pokerstars_cash")
