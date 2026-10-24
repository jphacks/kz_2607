import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.talklog import MAX_CHARS, MAX_TURNS, read_turns, record_turn  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def test_records_in_order_and_per_generation():
    db = FakeDb()
    record_turn(db, "p1", 1, "おはよう", "おはよう！", NOW, run_tx)
    record_turn(db, "p1", 1, "元気？", "元気だよ", NOW, run_tx)
    record_turn(db, "p1", 2, "はじめまして", "やあ", NOW, run_tx)
    assert [t["text"] for t in read_turns(db, "p1", 1)] == ["おはよう", "元気？"]
    assert [t["text"] for t in read_turns(db, "p1", 2)] == ["はじめまして"]
    assert read_turns(db, "p1", 3) == []


def test_keeps_only_latest_and_cuts_long_text():
    db = FakeDb()
    for i in range(MAX_TURNS + 5):
        record_turn(db, "p1", 1, f"t{i}", "r", NOW, run_tx)
    turns = read_turns(db, "p1", 1)
    assert len(turns) == MAX_TURNS and turns[0]["text"] == "t5"
    record_turn(db, "p2", 1, "あ" * 999, "い" * 999, NOW, run_tx)
    assert len(read_turns(db, "p2", 1)[0]["text"]) == MAX_CHARS


def test_failure_does_not_raise():
    def bad(db, fn):
        raise RuntimeError("down")
    record_turn(FakeDb(), "p1", 1, "a", "b", NOW, bad)
