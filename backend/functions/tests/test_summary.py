import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakes import FakeDb, run_tx  # noqa: E402
from petlogic.exchange import report_exchange  # noqa: E402
from petlogic.llm import LlmError, openai_chat  # noqa: E402
from petlogic.register import register_device  # noqa: E402
from petlogic.summary import build_prompt, make_summarizer, read_summaries, summarize_handoff  # noqa: E402
from petlogic.talklog import record_turn  # noqa: E402

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def setup():
    db = FakeDb()
    a = register_device(db, "u1", "devA", NOW)["petId"]
    b = register_device(db, "u2", "devB", NOW)["petId"]
    db.docs[("pets", a)]["name"] = "モチ"
    record_turn(db, a, 1, "おはよう", "おはよう！", NOW, run_tx)
    record_turn(db, a, 1, "散歩した", "いいね", NOW, run_tx)
    r = report_exchange(db, "u1", {"myDeviceId": "devA", "peerDeviceId": "devB", "givenPetId": a,
                                   "gotPetId": b, "transactionId": "t1"}, NOW, run_tx=run_tx)
    return db, a, b, r["handoffId"]


def test_handoff_records_ended_generations():
    db, a, b, h = setup()
    handoff = db.docs[("handoffs", h)]
    assert handoff["summaryStatus"] == "pending" and handoff["endedGenerations"] == {a: 1, b: 1}


def test_summarizes_only_pets_with_conversations_and_marks_done():
    db, a, b, h = setup()
    calls = []

    def fake(name, turns):
        calls.append((name, len(turns)))
        return "朝のあいさつと散歩の話をした。"

    r = summarize_handoff(db, h, fake, NOW, run_tx)
    assert r == {"status": "done", "summarized": 1} and calls == [("モチ", 2)]
    assert read_summaries(db, a, [1])[0]["summary"].startswith("朝の")
    assert read_summaries(db, b, [1]) == []
    assert db.docs[("handoffs", h)]["summaryStatus"] == "done"


def test_second_run_is_skipped():
    db, a, b, h = setup()
    summarize_handoff(db, h, lambda n, t: "x", NOW, run_tx)
    assert summarize_handoff(db, h, lambda n, t: 1 / 0, NOW, run_tx) == {"status": "skipped"}
    assert summarize_handoff(db, "nothing", lambda n, t: "x", NOW, run_tx) == {"status": "not_found"}


def test_failure_marks_failed_but_does_not_raise():
    db, a, b, h = setup()

    def boom(name, turns):
        raise LlmError("down")

    r = summarize_handoff(db, h, boom, NOW, run_tx)
    assert r["status"] == "failed" and db.docs[("handoffs", h)]["summaryStatus"] == "failed"
    assert read_summaries(db, a, [1]) == []


def test_prompt_has_no_ids():
    text = build_prompt("モチ", [{"text": "おはよう", "reply": "やあ"}])
    assert "モチ" in text and "おはよう" in text and "u1" not in text


def test_summarizer_uses_chat_and_cuts_length():
    seen = {}

    def chat(system, user, key, model):
        seen.update(key=key, model=model)
        return "あ" * 999

    out = make_summarizer("K", "M", chat)("モチ", [{"text": "a", "reply": "b"}])
    assert len(out) == 300 and seen == {"key": "K", "model": "M"}


def test_openai_chat_requires_key_and_model():
    with pytest.raises(LlmError):
        openai_chat("s", "u", None, "m")
    with pytest.raises(LlmError):
        openai_chat("s", "u", "k", "")


def test_openai_chat_over_http():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"message": {"content": " まとめ "}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        assert openai_chat("sys", "usr", "KEY", "mdl", url=url) == "まとめ"
    finally:
        server.shutdown()
    assert seen["auth"] == "Bearer KEY" and seen["body"]["model"] == "mdl"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
