"""Tests de l'import de fichiers et de la surveillance temps reel."""
import os
import shutil
import time

from conftest import DATA
from pokertracker.core.importer import Importer, HandHistoryWatcher, detect_hh_directories


def _stable(path):
    """Marque le fichier comme non modifie recemment."""
    old = time.time() - 60
    os.utime(path, (old, old))


def test_import_dossier(db, tmp_path):
    shutil.copy(DATA / "pokerstars_cash.txt", tmp_path)
    shutil.copy(DATA / "winamax_cash.txt", tmp_path)
    for f in tmp_path.iterdir():
        _stable(f)
    result = Importer(db).import_directory(tmp_path)
    assert result.files == 2 and result.hands == 3
    assert db.counts()["hands"] == 3


def test_import_incremental(db, tmp_path):
    target = tmp_path / "hh.txt"
    text = (DATA / "pokerstars_cash.txt").read_text(encoding="utf-8")
    first, second = text.split("\n\n", 1)
    target.write_text(first + "\n\n", encoding="utf-8")
    _stable(target)
    importer = Importer(db)
    assert importer.import_file(target).hands == 1
    assert importer.import_file(target).skipped == 1          # rien de neuf

    with target.open("a", encoding="utf-8") as fh:
        fh.write(second + "\n\n")
    _stable(target)
    assert importer.import_file(target).hands == 1
    assert db.counts()["hands"] == 2


def test_main_en_cours_ecriture(db, tmp_path):
    """Une main partiellement ecrite est importee au passage suivant."""
    target = tmp_path / "live.txt"
    text = (DATA / "pokerstars_cash.txt").read_text(encoding="utf-8")
    first, second = text.split("\n\n", 1)
    target.write_text(first + "\n\n", encoding="utf-8")
    _stable(target)
    importer = Importer(db)
    importer.import_file(target)

    partiel = second[: second.index("*** FLOP ***")]
    with target.open("a", encoding="utf-8") as fh:
        fh.write(partiel)
    assert importer.import_file(target).hands == 0            # main incomplete: ignoree

    with target.open("a", encoding="utf-8") as fh:
        fh.write(second[second.index("*** FLOP ***"):] + "\n\n")
    assert importer.import_file(target).hands == 1


def test_watcher_notifie_les_abonnes(db, tmp_path):
    shutil.copy(DATA / "pokerstars_cash.txt", tmp_path / "hh.txt")
    _stable(tmp_path / "hh.txt")
    watcher = HandHistoryWatcher(db, [str(tmp_path)], interval=0.1)
    recus = []
    watcher.subscribe(lambda hands: recus.extend(hands))
    assert watcher.scan_once() == 2
    assert len(recus) == 2
    assert watcher.scan_once() == 0


def test_watcher_thread(db, tmp_path):
    watcher = HandHistoryWatcher(db, [str(tmp_path)], interval=0.05)
    watcher.start()
    try:
        assert watcher.running
        shutil.copy(DATA / "ggpoker_cash.txt", tmp_path / "gg.txt")
        _stable(tmp_path / "gg.txt")
        for _ in range(40):
            if db.counts()["hands"]:
                break
            time.sleep(0.05)
        assert db.counts()["hands"] == 1
    finally:
        watcher.stop()
    assert not watcher.running


def test_fichier_non_reconnu(db, tmp_path):
    (tmp_path / "notes.txt").write_text("juste des notes personnelles", encoding="utf-8")
    result = Importer(db).import_directory(tmp_path)
    assert result.hands == 0 and result.skipped == 1


def test_detection_dossiers_ne_plante_pas():
    assert isinstance(detect_hh_directories(), dict)
