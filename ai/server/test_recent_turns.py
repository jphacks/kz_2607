"""
test_recent_turns.py — 直前の会話（recentTurns・history・サーバーの記憶）の確認用（モデルは呼ばない）

「1回目に名前を教える → 6回目と11回目に『覚えてる？』と聞く」を、バックエンドの代わりにここで会話を数えて試す。
判定モデル・性格LoRA は偽物、思い出の近さは文字の重なり（Ruri を読まない）。

    cd kz_2607/ai/server
    python test_recent_turns.py
    TEST_RURI=own python test_recent_turns.py      # 近さを Ruri で測る（本番と同じ。起動が遅い）
"""
import os
import unittest
from datetime import date

import talk_server
import talk_state
from memory import MemoryTalk
from mem_embed import Embedder
from common import PetProfile
from mem_select import parse_facts, recent_items, select_memories
from mem_check import check_reaction
from mem_text import FACTS_HEAD, RULES_FACTS, build_extra
from talk_models import M
from talk_server import TalkRequest, talk

NAME_TEXT = "ぼくの名前はゆうとだよ"
ASK_TEXT = "ぼくの名前、覚えてる？"
EMBED_MODE = os.environ.get("TEST_RURI", "lexical")


class FakeJudge:
    """「覚えてる」なら思い出、ほかは雑談。受け取った会話を取っておく。"""

    def __init__(self):
        self.seen = []

    def __call__(self, turns):
        self.seen.append(turns)
        action = "思い出" if "覚えてる" in turns[-1]["text"] else "雑談"
        return {"action": action, "route": action, "route_probs": {}, "unsafe_prob": 0.0,
                "emotion": "ふつう", "intensity": 0.0}


class FakeChat:
    def __init__(self, ready):
        self.ready = ready

    def reply(self, p, hist, user_text, **kw):
        return "そうなんだ", {"raw": "そうなんだ"}


class Backend:
    """バックエンドの代わり：会話に番号を付け、直近5往復を recentTurns にして送る。"""

    def __init__(self, pet_id):
        self.pet_id, self.turns, self.seq = pet_id, [], 0

    def send(self, text, send_recent=True, **extra):
        body = {"petId": self.pet_id, "text": text, "want_learn": False, "generation": 1, **extra}
        if send_recent:
            body["recentTurns"] = self.turns[-10:]
        r = call(**body)
        self.seq += 1
        self.turns += [{"speaker": "owner", "text": text, "seq": self.seq},
                       {"speaker": "pet", "text": r["reply_text"], "seq": self.seq}]
        return r


def call(**body):
    return talk(TalkRequest(**body), x_api_key=talk_server.API_KEY or None)


def chat_texts(n):
    return [f"今日は公園で{i}回目の散歩をしたよ" for i in range(2, n + 2)]


class RecentTurnsTest(unittest.TestCase):
    def setUp(self):
        self.saved = (M.judge, M.chat, M.memory)
        M.judge = FakeJudge()
        M.chat = FakeChat(ready=True)                                  # 雑談
        M.memory = MemoryTalk(FakeChat(ready=False), Embedder(mode=EMBED_MODE))   # 思い出は決まった返事
        talk_state.history.clear()
        talk_state._last_gen.clear()

    def tearDown(self):
        M.judge, M.chat, M.memory = self.saved
        talk_state.history.clear()
        talk_state._last_gen.clear()

    # ---- 1回目に名前 → 6回目に聞く
    def test_sixth_turn_with_recent_turns(self):
        b = Backend("p6")
        b.send(NAME_TEXT)
        for t in chat_texts(4):
            b.send(t)
        r = b.send(ASK_TEXT)                                   # 6回目。recentTurns は 1〜5回目
        self.assertEqual(r["route"], "思い出")
        self.assertIn("ゆうと", r["reply_text"])
        self.assertNotIn("p6", talk_state.history)             # recentTurns が来たら、サーバーは覚えない

    def test_sixth_turn_server_history(self):
        b = Backend("p6s")
        b.send(NAME_TEXT, send_recent=False)
        for t in chat_texts(4):
            b.send(t, send_recent=False)
        r = b.send(ASK_TEXT, send_recent=False)                # 移行期間：サーバーの記憶（12発言）で答える
        self.assertIn("ゆうと", r["reply_text"])
        self.assertEqual(len(talk_state.history["p6s"]), 12)

    # ---- 1回目に名前 → 11回目に聞く（1〜5回目は要約されて memories にある。recentTurns は 6〜10回目）
    def eleventh(self, pet_id, memories, facts):
        b = Backend(pet_id)
        b.send(NAME_TEXT)
        for t in chat_texts(9):
            b.send(t)
        extra = {"memories": memories, "nameMap": {"{person_1}": "ゆうと"}, "summarizedSeq": 10}
        if facts is not None:
            extra["facts"] = facts
        r = b.send(ASK_TEXT, **extra)
        self.assertEqual([t["seq"] for t in b.turns[-12:-2]], [6, 6, 7, 7, 8, 8, 9, 9, 10, 10])   # 送った recentTurns
        return r

    def test_eleventh_turn_with_summary(self):
        # 要約プロンプト（backend/functions/petlogic/memory.py の SYSTEM_A）の決まり：主語を書かない・
        # 「〜と話してくれた」で終わる・人の名前は伏せ字。近さは 文字の重なり 0.25（下限 0.3）・Ruri 0.831（下限 0.83）。
        # facts があれば、近さによらず facts から答える
        memories = [{"id": "m1", "text": "名前は{person_1}だと話してくれた", "createdAt": "2026-10-25T12:00:00+09:00"}]
        r = self.eleventh("p11", memories, {"ownerName": "{person_1}", "likes": []})
        self.assertIn("ゆうと", r["reply_text"])
        self.assertEqual(r["memory"]["fact_picked"], ["ownerName"])

    def test_eleventh_turn_facts_only(self):
        """要約された思い出に名前が無くても、facts から答える。"""
        memories = [{"id": "m1", "text": "公園で散歩したと話してくれた", "createdAt": "2026-10-25T12:00:00+09:00"}]
        r = self.eleventh("p11f", memories, {"ownerName": "{person_1}", "likes": []})
        self.assertIn("ゆうと", r["reply_text"])
        self.assertEqual(r["memory"]["fact_picked"], ["ownerName"])

    def test_eleventh_turn_no_facts(self):
        """facts が無いとき（移行期間）は今までどおり：要約にも直近にも名前が無ければ「覚えてない」。"""
        memories = [{"id": "m1", "text": "公園で散歩したと話してくれた", "createdAt": "2026-10-25T12:00:00+09:00"}]
        r = self.eleventh("p11n", memories, None)
        self.assertEqual(r["generator"], "memory-dontknow")
        self.assertNotIn("fact_picked", r["memory"])

    # ---- 優先順位：recentTurns > history > サーバーの記憶
    def test_priority(self):
        talk_state.history["pp"] = [{"speaker": "owner", "text": "サーバーの記憶"}, {"speaker": "pet", "text": "うん"}]
        sent = [{"speaker": "owner", "text": "送られた history"}, {"speaker": "pet", "text": "うん"}]
        recent = [{"speaker": "owner", "text": "recentTurns", "seq": 1}, {"speaker": "pet", "text": "うん", "seq": 1}]

        call(petId="pp", text="こんにちは", want_learn=False, history=sent, recentTurns=recent)
        self.assertEqual(M.judge.seen[-1][0]["text"], "recentTurns")
        call(petId="pp", text="こんにちは", want_learn=False, history=sent)
        self.assertEqual(M.judge.seen[-1][0]["text"], "送られた history")
        call(petId="pp", text="こんにちは", want_learn=False)
        self.assertEqual(M.judge.seen[-1][0]["text"], "サーバーの記憶")
        self.assertEqual(len(talk_state.history["pp"]), 4)    # 何も送られないときだけ覚える

    def test_empty_recent_turns(self):
        """1回目（recentTurns が空）でも、サーバーの記憶は使わない。"""
        talk_state.history["pe"] = [{"speaker": "owner", "text": "前の記憶"}, {"speaker": "pet", "text": "うん"}]
        call(petId="pe", text="こんにちは", want_learn=False, recentTurns=[])
        self.assertEqual(M.judge.seen[-1], [{"speaker": "owner", "text": "こんにちは"}])


class RecentSelectTest(unittest.TestCase):
    """思い出の選び方（段階3）：直近の会話をすべて候補にする・要約済みを外す・直近を1件は残す。"""

    def setUp(self):
        self.emb = Embedder(mode="lexical")

    @staticmethod
    def turns(texts):
        out = []
        for i, t in enumerate(texts, 1):
            out += [{"speaker": "owner", "text": t, "seq": i}, {"speaker": "pet", "text": "そうなんだ", "seq": i}]
        return out

    def test_all_received_turns(self):
        hist = self.turns([NAME_TEXT] + chat_texts(9))           # 20発言。前の上限（8・12）より長い
        self.assertIn(NAME_TEXT.rstrip("よ"), [m["text"] for m in recent_items(hist, ASK_TEXT)][0])

    def test_summarized_seq(self):
        hist = self.turns([NAME_TEXT] + chat_texts(5))           # seq 1〜6
        self.assertEqual([m["seq"] for m in recent_items(hist, ASK_TEXT, summarized_seq=5)], [6])
        self.assertEqual(len(recent_items(hist, ASK_TEXT, summarized_seq=6)), 6)    # 全部外れるなら外さない
        self.assertEqual(len(recent_items(hist, ASK_TEXT)), 6)

    def test_keep_one_recent(self):
        name_map = {"{person_1}": "ゆうと"}
        items = [{"id": "m1", "masked": "{person_1}と公園に行った", "text": "ゆうとと公園に行った", "date": None},
                 {"id": "m2", "masked": "{person_1}とアイスを食べた", "text": "ゆうととアイスを食べた", "date": None}]
        recent = recent_items(self.turns(["ゆうとと公園でブランコに乗ったよ"]), "ゆうとと公園に行ったの覚えてる？")
        picked, _ = select_memories(self.emb, "ゆうとと公園に行ったの覚えてる？", items, name_map, date(2026, 10, 25), recent)
        self.assertEqual([m["id"] for m in picked], ["m1", "recent:0"])   # 要約2件そろっても直近を1件


class RecordChat(FakeChat):
    """性格LoRA の代わり。渡された system の追加分（extra）を取っておく。"""

    def __init__(self):
        super().__init__(ready=True)
        self.extras = []

    def reply(self, p, hist, user_text, extra="", **kw):
        self.extras.append(extra)
        return "楽しかったね！", {"raw": "楽しかったね！"}


FACTS = {"ownerName": "{person_1}", "likes": ["いちご", "{food_1}", "ねこ", "うみ"]}
NAME_MAP = {"{person_1}": "ゆうと", "{food_1}": "ショートケーキ"}


class FactsPromptTest(unittest.TestCase):
    """段階4：facts を受け取り、今の飼い主の話のときだけ【いつも覚えていること】に入れる。"""

    def test_parse_facts(self):
        f = parse_facts(FACTS, NAME_MAP)
        self.assertEqual([x["line"] for x in f], ["飼い主さんの名前はゆうと", "飼い主さんの好きなもの：いちご・ショートケーキ・ねこ"])
        self.assertEqual([x["key"] for x in parse_facts(FACTS, {})], ["likes"])   # 名前の伏せ字が戻せないなら使わない
        self.assertEqual(parse_facts(None, NAME_MAP), [])
        self.assertEqual(parse_facts({"ownerName": None, "likes": []}, NAME_MAP), [])

    def test_build_extra(self):
        p = PetProfile(stage=3)
        self.assertEqual(build_extra("current", ["散歩した"], p, None), build_extra("current", ["散歩した"], p))  # 今までどおり
        self.assertNotIn(FACTS_HEAD, build_extra("current", ["散歩した"], p))
        self.assertIn(FACTS_HEAD + "\n- 飼い主さんの名前はゆうと", build_extra("current", ["散歩した"], p, ["飼い主さんの名前はゆうと"]))
        self.assertNotIn("ゆうと", build_extra("past", ["散歩した"], p, ["飼い主さんの名前はゆうと"]))

    def test_reply_current_and_past(self):
        chat = RecordChat()
        mt = MemoryTalk(chat, Embedder(mode=EMBED_MODE))
        p = PetProfile(stage=3, generation=2)
        hist = RecentSelectTest.turns(["公園でブランコに乗ったよ"])
        mt.reply(p, hist, "公園でブランコに乗ったの覚えてる？", [], NAME_MAP, facts=FACTS)
        self.assertIn("- 飼い主さんの名前はゆうと", chat.extras[-1])
        journeys = [{"generation": 1, "summary": "{place_1}でよく散歩した", "timeOfDay": "夜"}]
        r, _, persona = mt.reply(p, hist, "前の飼い主さんとは何してた？", [], NAME_MAP, journeys, facts=FACTS)
        self.assertEqual(persona["memory"]["kind"], "past")
        self.assertNotIn("ゆうと", chat.extras[-1])
        self.assertNotIn("ゆうと", r)
        self.assertEqual(persona["memory"]["facts"], [])

    def test_talk_passes_facts(self):
        saved = (M.judge, M.memory)
        M.judge, M.memory = FakeJudge(), MemoryTalk(RecordChat(), Embedder(mode=EMBED_MODE))
        try:
            recent = RecentSelectTest.turns(["公園でブランコに乗ったよ"])
            r = call(petId="pf", text="公園でブランコに乗ったの覚えてる？", want_learn=False, recentTurns=recent,
                     facts=FACTS, nameMap=NAME_MAP)
            self.assertEqual(r["memory"]["facts"], ["ownerName", "likes"])
            r = call(petId="pf", text="公園でブランコに乗ったの覚えてる？", want_learn=False, recentTurns=recent)
            self.assertEqual(r["memory"]["facts"], [])                     # facts が無いとき（移行期間）
            self.assertNotIn(FACTS_HEAD, M.memory.chat.extras[-1])
        finally:
            M.judge, M.memory = saved
            talk_state.history.clear()


class FactsAnswerTest(unittest.TestCase):
    """段階5：名前・好きなものを聞かれたら、近さによらず facts から答える。"""

    def setUp(self):
        self.chat = RecordChat()
        self.mt = MemoryTalk(self.chat, Embedder(mode=EMBED_MODE))

    def ask(self, text, stage=3, facts=FACTS, journeys=None):
        return self.mt.reply(PetProfile(stage=stage, generation=2), [], text, [], NAME_MAP, journeys, facts=facts)

    def test_name(self):
        r, g, persona = self.ask(ASK_TEXT)
        self.assertTrue(r.startswith("うん、覚えてるよ！きみの名前はゆうとだよね。"), r)
        self.assertEqual(g, "memory-template+lora")
        self.assertIn(RULES_FACTS.strip(), self.chat.extras[-1])
        self.assertIn("【覚えていること】（いまの飼い主さんとの思い出）\n- 飼い主さんの名前はゆうと", self.chat.extras[-1])

    def test_likes(self):
        r, _, persona = self.ask("ぼくの好きなもの、覚えてる？")
        self.assertTrue(r.startswith("うん、覚えてるよ！きみはいちごとショートケーキとねこが好きなんだよね。"), r)
        self.assertEqual(persona["memory"]["fact_picked"], ["likes"])

    def test_baby(self):
        r, g, _ = self.ask(ASK_TEXT, stage=1)                       # モデルを呼ばない決まった文（赤ちゃん言葉に直したもの）
        self.assertEqual((r, g), ("きみのなまえはゆうとだよっ！", "memory-template"))
        r, g, _ = self.ask("すきなもの おぼえてる？", stage=1)
        self.assertEqual((r, g), ("きみはいちごとショートケーキとねこがすきだよっ！", "memory-template"))

    def test_pet_own_name_not_picked(self):
        """「きみの名前」はペット自身のことなので、飼い主の名前で答えない。"""
        r, _, persona = self.ask("きみの名前、覚えてる？")
        self.assertNotIn("ゆうと", r)
        self.assertNotIn("fact_picked", persona["memory"])

    def test_past_owner_name(self):
        """前の代の話に、今の飼い主の名前が混ざらない。"""
        journeys = [{"generation": 1, "summary": "{place_1}でよく散歩した", "timeOfDay": "夜"}]
        r, _, persona = self.ask("前の飼い主さんの名前、覚えてる？", journeys=journeys)
        self.assertEqual(persona["memory"]["kind"], "past")
        self.assertNotIn("ゆうと", r)
        self.assertNotIn("ゆうと", self.chat.extras[-1] if self.chat.extras else "")
        self.assertNotIn("fact_picked", persona["memory"])

    def test_check_reaction_allows_fact_words(self):
        p = PetProfile(stage=3)
        lines = ["飼い主さんの名前はゆうと"]
        facts = ["飼い主さんの名前はゆうと", "飼い主さんの好きなもの：いちご・ショートケーキ・ねこ"]
        _, reasons = check_reaction("ショートケーキ、また一緒に食べたいね！", lines, [], p, facts=facts)
        self.assertEqual(reasons, [])
        _, reasons = check_reaction("ショートケーキ、また一緒に食べたいね！", lines, [], p)
        self.assertIn("思い出に無い言葉「ショートケーキ」", reasons)          # facts が無ければ今までどおり外す


if __name__ == "__main__":
    talk_server.log_talk = lambda *a, **k: None    # 1行ログは出さない
    unittest.main(verbosity=2)
