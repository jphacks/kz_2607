"""
check_memory_data.py — check_memory.py で使う偽の材料（memories・nameMap・journeys・pastMemories）・質問・合っているかの見方
  質問や材料を足すときはこのファイルだけ直す
"""
from datetime import datetime, timedelta

from common import TZ


def build_data(today):
    def at(days, hour):
        d = datetime.combine(today - timedelta(days=days), datetime.min.time()).replace(hour=hour, tzinfo=TZ)
        return d.isoformat()
    memories = [
        {"id": "m1", "text": "{shop_1}でいちごのアイスを食べた", "createdAt": at(1, 19)},
        {"id": "m2", "text": "数学のテストが心配だと話してくれた", "createdAt": at(4, 21)},
        {"id": "m3", "text": "{person_1}と{place_1}でバドミントンをした", "createdAt": at(3, 16)},
        {"id": "m4", "text": "雨の日に一緒に映画を見た", "createdAt": at(5, 20)},
        {"id": "m5", "text": "{school_1}の文化祭の準備で忙しいと言っていた", "createdAt": at(10, 22)},
        {"id": "m6", "text": "カレーを作るのに失敗したと笑っていた", "createdAt": at(8, 19)},
        {"id": "m7", "text": "数学のテストが返ってきて、思ったよりよかったと喜んでいた", "createdAt": at(2, 18)},
        {"id": "m8", "text": "{person_2}の誕生日プレゼントを一緒に考えた", "createdAt": at(12, 20)},
        {"id": "m9", "text": "夜おそくまでゲームをしていた", "createdAt": at(6, 1)},
        {"id": "m10", "text": "{event_1}に行って花火を見た", "createdAt": at(20, 21)},
    ]
    name_map = {"{shop_1}": "ミスド", "{person_1}": "ゆうと", "{place_1}": "公園", "{school_1}": "北高",
                "{person_2}": "さくら", "{event_1}": "夏祭り"}
    journeys = [
        {"generation": 1, "summary": "{place_1}でよく散歩した", "timeOfDay": "夜", "speech": "関西弁",
         "learnedWords": ["めっちゃ"], "grewTrait": "talkative", "talkCount": 45},
        {"generation": 2, "summary": "{shop_1}のパンをよく分けてもらった", "timeOfDay": "朝", "speech": "標準",
         "learnedWords": ["おつかれ"], "grewTrait": "affection", "talkCount": 30},
    ]
    # 前の代の思い出（バックエンドでぼかし済み）。p3 は心配の話なので使われないはず
    past_memories = [
        {"id": "p1", "text": "あの公園でボール遊びをした", "generation": 2, "createdAt": at(15, 17)},
        {"id": "p2", "text": "あのお友だちと雪だるまを作った", "generation": 2, "createdAt": at(20, 15)},
        {"id": "p3", "text": "テストが心配だと話してくれた", "generation": 2, "createdAt": at(16, 21)},
        {"id": "p4", "text": "あのお店のパンを分けてもらった", "generation": 2, "createdAt": at(18, 8)},
        {"id": "p5", "text": "あのお祭りで金魚すくいをした", "generation": 1, "createdAt": at(40, 19)},
        {"id": "p6", "text": "あのお店のたこ焼きを食べた", "generation": 1, "createdAt": at(45, 20)},
    ]
    return memories, name_map, journeys, past_memories


# (質問, 材料 all のときに選ばれてほしいもの, 前の代なら先頭に来てほしい旅の記録の値)
#   current の id・"g1"/"g2"（旅の記録の代）・None（覚えてない）
QUESTIONS = [
    ("昨日なに食べたっけ？", ["m1"], None),
    ("テストの話覚えてる？", ["m2", "m7"], None),
    ("ゆうとと何したっけ？", ["m3"], None),
    ("この前一緒に見た映画覚えてる？", ["m4"], None),
    ("さくらのプレゼントのこと覚えてる？", ["m8"], None),
    ("夏祭りのこと覚えてる？", ["m10"], None),
    ("前の飼い主さんとは何してた？", ["g2"], None),                    # summary か前の代の思い出
    ("前はどこにいたの？", ["g2"], None),
    ("前の飼い主さんとボール遊びした？", ["g2"], "past:p1"),          # 前の代の思い出（pastMemories）から
    ("最初の飼い主さんと金魚すくいしたっけ？", ["g1"], "past:p5"),
    ("前の飼い主さんはテストの話してた？", ["g2"], "summary"),        # 心配の話（p3）は使わない
    ("最初の飼い主さんってどんな人だった？", ["g1"], "speech"),
    ("前の飼い主さんってどんな人だった？", ["g2"], "timeOfDay"),        # 2代目は話し方が「標準」なので時間帯で答える
    ("前の飼い主さんに何か教えてもらった？", ["g2"], "learnedWords"),
    ("最初の飼い主さんのところでどう変わった？", ["g1"], "grewTrait"),
    ("去年の夏のこと覚えてる？", None, None),
    ("ピアノの発表会のこと覚えてる？", None, None),
    ("お前はあのとき覚えてる？", None, None),                         # 「お前は」を前の飼い主と取り違えない
    ("きみの名前は覚えてる？", None, None),                           # 「名前は」も同じ
]
STAGES = {1: 0.0, 2: 0.5, 3: 1.0}


def material(name, memories, name_map, journeys, past_memories):
    if name == "all":
        return memories, name_map, journeys, past_memories, 3
    if name == "current":
        return memories, name_map, [], [], 1
    return [], {}, [], [], 1


def expected_ok(exp, mat, info, key=None):
    """選ばれたものが期待どおりか。前の代は、先頭の値（key）も見る。"""
    kind = info.get("kind")
    if mat == "none" or (mat == "current" and kind != "current"):
        exp = None
    if exp is None:
        return not info.get("lines")
    if kind == "current":
        return bool(info.get("picked")) and info["picked"][0] in exp
    return f"g{info.get('generation')}" in exp and key_ok(key, info)


def key_ok(key, info):
    """前の代で、先頭に来た値が期待どおりか。"past:p1" なら pastMemories のその思い出が選ばれたか。"""
    if key is None:
        return True
    first = (info.get("keys") or [None])[0]
    if key.startswith("past:"):
        return first == "pastMemory" and (info.get("picked") or [None])[0] == key
    return first == key
