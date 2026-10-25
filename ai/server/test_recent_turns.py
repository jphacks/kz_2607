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
        self.assertIn(RULES_FACTS.strip(), chat.extras[-1])
        journeys = [{"generation": 1, "summary": "{place_1}でよく散歩した", "timeOfDay": "夜"}]
        r, _, persona = mt.reply(p, hist, "前の飼い主さんとは何してた？", [], NAME_MAP, journeys, facts=FACTS)
        self.assertEqual(persona["memory"]["kind"], "past")
        self.assertNotIn("ゆうと", chat.extras[-1])
        self.assertIn("【覚えていること】（前の飼い主さんとの思い出）", chat.extras[-1])
        self.assertNotIn(FACTS_HEAD, chat.extras[-1])
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
        self.assertEqual((r, g), ("うん、覚えてるよ！きみの名前はゆうとだよね。", "memory-template"))   # 一言は付けない
        self.assertEqual(self.chat.extras, [])                                                     # モデルを呼ばない
        self.assertEqual(persona["memory"]["lines"][0], "飼い主さんの名前はゆうと")

    def test_likes(self):
        r, g, persona = self.ask("ぼくの好きなもの、覚えてる？")
        self.assertEqual((r, g), ("うん、覚えてるよ！きみはいちごとショートケーキとねこが好きなんだよね。", "memory-template"))
        self.assertEqual(self.chat.extras, [])
        self.assertEqual(persona["memory"]["fact_picked"], ["likes"])

    def test_baby(self):
        r, g, _ = self.ask(ASK_TEXT, stage=1)                       # モデルを呼ばない決まった文（赤ちゃん言葉に直したもの）
        self.assertEqual((r, g), ("きみのなまえはゆうとだよっ！", "memory-template"))
        r, g, _ = self.ask("すきなもの おぼえてる？", stage=1)
        self.assertEqual((r, g), ("きみはいちごとショートケーキとねこがすきだよっ！", "memory-template"))

    def test_react_only_for_memories(self):
        """一言（性格LoRA）は、今の飼い主との思い出・直近の会話のときだけ。事実・前の代の思い出には付けない。"""
        hist = RecentSelectTest.turns(["公園でブランコに乗ったよ"])
        r, g, _ = self.mt.reply(PetProfile(stage=3), hist, "公園でブランコに乗ったの覚えてる？", [], NAME_MAP, facts=FACTS)
        self.assertEqual(g, "memory-template+lora")
        self.assertTrue(r.endswith("楽しかったね！"), r)
        self.chat.extras.clear()
        past = [{"id": "p1", "text": "あの公園でボール遊びをした", "generation": 1, "createdAt": "2026-10-20T12:00:00+09:00"}]
        r, g, persona = self.mt.reply(PetProfile(stage=3, generation=2), [], "前の飼い主さんとボール遊びした？", [], NAME_MAP,
                                      [], past_memories=past)
        self.assertEqual((r, g), ("前の飼い主さんがね、あの公園でボール遊びをしたんだ。", "memory-template"))
        self.assertEqual(persona["memory"]["check"], "template（決まった文だけ）")
        self.assertEqual(self.chat.extras, [])

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


TODAY = date(2026, 10, 25)
NOON = "2026-10-25T12:00:00+09:00"
EXCHANGE_QUESTIONS = ["昨日なにしたっけ？", "この前なにしたっけ？", "今日なにしたっけ？", "前の飼い主さんとは何の話をした？"]


def exchanged(food_or_fire):
    """交換したばかりのペット（今は2代目）。前の代（1代目）の思い出と旅の記録だけある。"""
    past = [{"id": "p1", "text": food_or_fire, "generation": 1, "createdAt": NOON}]
    journeys = [{"generation": 1, "summary": "夏の話をよくした", "timeOfDay": "夜", "talkCount": 6}]
    return past, journeys


class ExchangeTest(unittest.TestCase):
    """段階B：交換のあと、時間を聞く質問・中身の言葉が無い質問で、前の代の思い出から新しい順に答える。"""

    def setUp(self):
        self.chat = RecordChat()
        self.mt = MemoryTalk(self.chat, Embedder(mode=EMBED_MODE))

    def ask(self, q, past, journeys, stage=3, memories=(), hist=()):
        self.chat.extras.clear()
        return self.mt.reply(PetProfile(stage=stage, generation=2), list(hist), q, list(memories), NAME_MAP, journeys,
                             today=TODAY, past_memories=past, facts=FACTS)

    def check_pet(self, text, word):
        past, journeys = exchanged(text)
        for q in EXCHANGE_QUESTIONS:
            r, g, persona = self.ask(q, past, journeys)
            m = persona["memory"]
            with self.subTest(q=q):
                self.assertIn(word, r)
                self.assertTrue(r.startswith("前の飼い主さんがね、") and r.endswith(word + "。"), r)   # 一言は付けない
                self.assertEqual((g, self.chat.extras), ("memory-template", []))
                self.assertNotIn("昨日", r)                                   # 思い出の日付は今日
                self.assertNotIn("ゆうと", r)                                 # 今の飼い主の名前
                self.assertEqual(m["picked"], ["past:p1"])
                self.assertEqual(m["facts"], [])

    def test_hiyashi_chuka(self):
        self.check_pet("冷やし中華を食べたと話してくれた", "冷やし中華を食べたって話してくれたんだ")

    def test_hanabi(self):
        self.check_pet("あのお祭りで花火を見たと言っていた", "花火を見たって言ってたんだ")

    def test_kinds(self):
        past, journeys = exchanged("冷やし中華を食べたと話してくれた")
        for q in EXCHANGE_QUESTIONS[:3]:
            self.assertEqual(self.ask(q, past, journeys)[2]["memory"].get("answer_kind"), "past")   # kind は current のまま
        self.assertEqual(self.ask(EXCHANGE_QUESTIONS[3], past, journeys)[2]["memory"]["kind"], "past")

    def test_talk_two_pets(self):
        """/talk から（交換直後の1回目：memories 空・recentTurns 無し）。2匹がそれぞれ前の代の話をする。"""
        saved = (M.judge, M.memory)
        M.judge, M.memory = FakeJudge(), MemoryTalk(RecordChat(), Embedder(mode=EMBED_MODE))
        try:
            for pet, text, word in [("petA", "冷やし中華を食べたと話してくれた", "冷やし中華"),
                                    ("petB", "あのお祭りで花火を見たと言っていた", "花火")]:
                past, journeys = exchanged(text)
                past[0]["createdAt"] = date.today().isoformat() + "T12:00:00+09:00"
                r = call(petId=pet, text="昨日なにしたっけ？", want_learn=False, generation=2, pastMemories=past,
                         journeys=journeys, nameMap=NAME_MAP, facts=FACTS)
                self.assertEqual(r["route"], "思い出")
                self.assertIn(word, r["reply_text"])
                self.assertNotIn("昨日", r["reply_text"])
                self.assertNotIn("ゆうと", r["reply_text"])
        finally:
            M.judge, M.memory = saved
            talk_state.history.clear()
            talk_state._last_gen.clear()

    def test_content_words(self):
        from mem_select import content_words
        for q in EXCHANGE_QUESTIONS + ["昨日なにしてたっけ", "前の飼い主さんと何話してた？", "今日何したか覚えてる？"]:
            self.assertEqual(content_words(q), [], q)
        self.assertTrue(content_words("この前の冷やし中華覚えてる？"))          # 中身の言葉がある（「中華覚」）
        self.assertEqual(content_words("前の飼い主さんとボール遊びした？"), ["ボール"])

    def test_where(self):
        """「前はどこにいたの？」は、前の代の思い出（できごと1件）ではなく旅の記録のまとめで答える。"""
        past, journeys = exchanged("冷やし中華を食べたと話してくれた")
        r, _, persona = self.ask("前はどこにいたの？", past, journeys)
        self.assertEqual(persona["memory"]["question"], "where")
        self.assertEqual(persona["memory"]["keys"][0], "summary")
        self.assertTrue(r.startswith("えっとね、前の飼い主さんとは夏の話をよくしたんだ。"), r)

    def test_relaxed_day_label(self):
        """今の代の思い出が今日だけのとき、「昨日」で聞かれても「今日」と言う（過去7日に緩める）。"""
        memories = [{"id": "m1", "text": "冷やし中華を食べた", "createdAt": NOON}]
        r, _, persona = self.ask("昨日なにしたっけ？", [], [], memories=memories)
        self.assertTrue(r.startswith("うん、覚えてるよ！今日冷やし中華を食べたよね。"), r)
        self.assertEqual(persona["memory"]["relaxed"], 7)
        r, _, _ = self.ask("去年なにしたっけ？", [], [], memories=memories)        # 去年・先週などは緩めない
        self.assertNotIn("冷やし中華", r)

    def test_content_question_uses_similarity(self):
        """中身の言葉がある質問は、新しい順ではなく近さで選ぶ（新しい花火より、古い冷やし中華）。"""
        memories = [{"id": "m1", "text": "あのお祭りで花火を見た", "createdAt": NOON},
                    {"id": "m2", "text": "冷やし中華を食べた", "createdAt": "2026-10-22T12:00:00+09:00"}]
        for q in ["冷やし中華覚えてる？", "この前の冷やし中華覚えてる？"]:
            r, _, persona = self.ask(q, [], [], memories=memories)
            with self.subTest(q=q):
                self.assertEqual(persona["memory"]["picked"][0], "m2")
                self.assertNotEqual(persona["memory"].get("method"), "newest")
        r, _, persona = self.ask("この前なにしたっけ？", [], [], memories=memories)   # 中身が無ければ新しい順
        self.assertEqual(persona["memory"]["picked"][0], "m1")

    def test_baby(self):
        """赤ちゃんの段階：モデルを呼ばない決まった文。生まれたときの口ぐせ（6種類）のどれでも、中身が切れない。"""
        from common import AXES
        # 口ぐせが文の終わりに付くので「〜したこと」で終える（「〜くれただよっ！」「〜くれたなの」にしない）
        cases = [("冷やし中華を食べたと話してくれた", "まえのかいぬしさんがひやしちゅうかをたべたってはなしてくれたこと"),
                 ("あのお祭りで花火を見たと言っていた", "まえのかいぬしさんがあのおまつりではなびをみたっていってたこと")]
        for text, body in cases:
            past, journeys = exchanged(text)
            for q in EXCHANGE_QUESTIONS:
                for trait in AXES:
                    p = PetProfile(stage=1, generation=2, birth_trait=trait)
                    r, g, _ = self.mt.reply(p, [], q, [], NAME_MAP, journeys, today=TODAY, past_memories=past, facts=FACTS)
                    with self.subTest(text=text, q=q, trait=trait):
                        self.assertEqual(g, "memory-template")
                        self.assertIn(body, r)
                        self.assertEqual(r, p.ending.replace("〜", body) + ("！" if p.ending.startswith("あのね") else ""))
        p = PetProfile(stage=1, generation=2, birth_trait="active")       # 口ぐせ「〜だよっ！」
        r = self.mt.reply(p, [], "昨日なにしたっけ？", [], NAME_MAP, [], today=TODAY,
                          past_memories=exchanged(cases[0][0])[0])[0]
        self.assertEqual(r, "まえのかいぬしさんがひやしちゅうかをたべたってはなしてくれたことだよっ！")

class StageTest(unittest.TestCase):
    """段階：バックエンドの stage（baby・child・adult）を最優先。無ければ humanness、それも無ければ育った。"""

    def test_from_request(self):
        def stage(**kw):
            return PetProfile.from_request(TalkRequest(text="x", **kw)).stage
        self.assertEqual([stage(stage="baby"), stage(stage="child"), stage(stage="adult")], [1, 2, 3])
        self.assertEqual(stage(stage="baby", humanness=1.0), 1)            # stage が先
        self.assertEqual(stage(stage="?", humanness=0.0), 1)               # 知らない値なら humanness
        self.assertEqual(stage(humanness=0.5), 2)
        self.assertEqual(stage(), 3)

    def test_talk_baby(self):
        saved = (M.judge, M.memory)
        M.judge, M.memory = FakeJudge(), MemoryTalk(RecordChat(), Embedder(mode=EMBED_MODE))
        try:
            r = call(petId="ps", text=ASK_TEXT, want_learn=False, stage="baby", recentTurns=[], facts=FACTS, nameMap=NAME_MAP)
            self.assertEqual((r["persona"]["stage"], r["reply_text"]), (1, "きみのなまえはゆうとだよっ！"))   # 性格の軸なし → 口ぐせ「〜だよっ！」
        finally:
            M.judge, M.memory = saved
            talk_state.history.clear()


class RouteTest(unittest.TestCase):
    """振り分けの上書き：飼い主自身のこと → 思い出、ペット自身のこと → ペット自身。"""

    @staticmethod
    def route(text, action):
        from talk_route import adjust_action
        j = {"action": action}
        adjust_action(j, text)
        return j["action"]

    def test_owner(self):
        for text in ["ぼくの名前、覚えてる？", "俺の名前わかる？", "ぼくの好きなもの、覚えてる？", "わたしの名前知ってる？",
                     "おれの好物なんだっけ"]:
            for action in ["ペット自身", "雑談", "思い出", "込み入った質問"]:
                with self.subTest(text=text, action=action):
                    self.assertEqual(self.route(text, action), "思い出")
        self.assertEqual(self.route("ぼくの名前、覚えてる？", "安全な返事"), "安全な返事")    # 危ない発言は変えない
        self.assertEqual(self.route("ぼくの名前はゆうとだよ", "雑談"), "雑談")                 # 聞いていない

    def test_pet(self):
        for text in ["きみの名前、覚えてる？", "お前の名前覚えてる？", "あなたの好きなもの覚えてる？"]:
            for action in ["思い出", "雑談", "ペット自身", "思い出（検索して無ければ雑談）"]:
                with self.subTest(text=text, action=action):
                    self.assertEqual(self.route(text, action), "ペット自身")

    def test_unspecified_unchanged(self):
        """誰のことか書いていない「名前覚えてる？」は今までどおり（案2はまだ入れない）。"""
        self.assertEqual(self.route("名前覚えてる？", "ペット自身"), "ペット自身")
        self.assertEqual(self.route("名前覚えてる？", "雑談"), "思い出")


class FactQuestionTest(unittest.TestCase):
    """facts が無いとき（要約がまだ届いていない6回目）、名前・好きなものは直近の会話の飼い主の発言から答える。"""

    def setUp(self):
        self.chat = RecordChat()
        self.mt = MemoryTalk(self.chat, Embedder(mode=EMBED_MODE))
        self.hist = RecentSelectTest.turns([NAME_TEXT, "いちごのアイスが好きなんだ", "今日は公園で散歩したよ",
                                            "学校で数学のテストがあった", "夜ごはんはカレーだった"])

    def ask(self, text, facts=None):
        return self.mt.reply(PetProfile(stage=3), self.hist, text, [], NAME_MAP, facts=facts)

    def test_likes_from_recent(self):
        r, g, persona = self.ask("ぼくの好きなもの、覚えてる？")
        self.assertTrue(r.startswith("うん、覚えてるよ！さっき「いちごのアイスが好きなんだ」って話してくれたよね。"), r)
        self.assertEqual(persona["memory"]["recent_fact"], "likes")

    def test_name_from_recent(self):
        r, _, persona = self.ask("俺の名前わかる？")
        self.assertIn("ゆうと", r)
        self.assertEqual(persona["memory"]["recent_fact"], "ownerName")

    def test_facts_first(self):
        r, _, persona = self.ask("ぼくの好きなもの、覚えてる？", facts=FACTS)      # facts があれば facts で答える
        self.assertEqual(persona["memory"]["fact_picked"], ["likes"])
        self.assertNotIn("recent_fact", persona["memory"])

    def test_other_like_question(self):
        """「公園好きだったっけ？」は好きなものを聞いていないので、直近の「好き」で答えない。"""
        _, _, persona = self.ask("公園好きだったっけ？")
        self.assertNotIn("recent_fact", persona["memory"])

    def test_pet_ask_in_memory(self):
        """思い出の経路に「きみの名前覚えてる？」が来ても、飼い主の名前・facts を使わない。"""
        r, _, persona = self.ask("きみの名前、覚えてる？", facts=FACTS)
        self.assertNotIn("ゆうと", r)
        self.assertEqual(persona["memory"]["facts"], [])
        self.assertTrue(all("ゆうと" not in e for e in self.chat.extras))

    def test_sixth_turn_talk(self):
        """/talk から：1回目に名前、2回目に好きなもの → 6回目に「ぼくの好きなもの、覚えてる？」（facts・要約なし）。"""
        saved = (M.judge, M.chat, M.memory)
        M.judge, M.chat, M.memory = FakeJudge(), FakeChat(ready=True), MemoryTalk(RecordChat(), Embedder(mode=EMBED_MODE))
        try:
            b = Backend("p6l")
            for t in [NAME_TEXT, "いちごのアイスが好きなんだ"] + chat_texts(3):
                b.send(t)
            r = b.send("ぼくの好きなもの、覚えてる？")
            self.assertEqual(r["route"], "思い出")
            self.assertIn("いちごのアイス", r["reply_text"])
        finally:
            M.judge, M.chat, M.memory = saved
            talk_state.history.clear()


if __name__ == "__main__":
    talk_server.log_talk = lambda *a, **k: None    # 1行ログは出さない
    unittest.main(verbosity=2)
