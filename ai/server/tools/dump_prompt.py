"""
tools/dump_prompt.py — 思い出の返事で 8081（性格LoRA）に送る messages（system 全文・最後の user）を、モデルを呼ばずに出す

8081 を起動しなくてよい。送る直前の requests.post を差しかえて、中身を取り出すだけ（返事の一言は「楽しかったね！」で固定）。
決まった文だけで答えるとき（名前・好きなもの・前の代の思い出・赤ちゃんの段階）はモデルを呼ばないので「（モデルを呼ばない）」と出る。

使い方:
    cd kz_2607/ai/server
    ../chat/.venv/bin/python tools/dump_prompt.py                        # 決まった3問（直近の会話・名前・前の代）
    ../chat/.venv/bin/python tools/dump_prompt.py "昨日なにしたっけ？"     # 質問を指定
    ../chat/.venv/bin/python tools/dump_prompt.py -o before.txt          # ファイルに書く（RULES を変える前後の diff に使う）
    diff -u before.txt after.txt

材料（下の FACTS・NAME_MAP・HIST・JOURNEYS・PAST）は、今の飼い主が2代目・前の代が1代目のペットのつもりの偽物。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # ai/server を読めるように

import chat_lora  # noqa: E402
from chat_lora import ChatLoRA  # noqa: E402
from common import PetProfile  # noqa: E402
from mem_embed import Embedder  # noqa: E402
from memory import MemoryTalk  # noqa: E402

FACTS = {"ownerName": "{person_1}", "likes": ["いちご", "{food_1}", "ねこ"]}
NAME_MAP = {"{person_1}": "ゆうと", "{food_1}": "ショートケーキ"}
HIST = [{"speaker": "owner", "text": "公園でブランコに乗ったよ", "seq": 11}, {"speaker": "pet", "text": "いいね", "seq": 12}]
JOURNEYS = [{"generation": 1, "summary": "夏の話をよくした", "timeOfDay": "夜", "talkCount": 6}]
PAST = [{"id": "p1", "text": "冷やし中華を食べたと話してくれた", "generation": 1, "createdAt": "2026-10-25T12:00:00+09:00"}]
QUESTIONS = ["公園でブランコに乗ったの覚えてる？", "ぼくの名前、覚えてる？", "前の飼い主さんってどんな人だった？"]

sent = []


class FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "楽しかったね！"}}]}


def fake_post(url, json=None, timeout=None):
    sent.append(json["messages"])
    return FakeResp()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="*", default=QUESTIONS)
    ap.add_argument("-o", "--out", help="書き出すファイル（無ければ画面に出す）")
    ap.add_argument("--stage", type=int, default=3, help="1 赤ちゃん・2 子ども・3 育った")
    args = ap.parse_args()

    chat_lora.requests.post = fake_post
    chat = ChatLoRA()
    chat.lora_ids = {"talkative": 0}          # 8081 に聞かずに「使える」ことにする
    mt = MemoryTalk(chat, Embedder(mode="lexical"))
    p = PetProfile(name="モチ", axes={"talkative": 0.6, "affection": 0.4, "active": 0.2}, stage=args.stage, hour=19,
                   generation=2)
    out = []
    for q in args.questions:
        sent.clear()
        r, g, persona = mt.reply(p, HIST, q, [], NAME_MAP, JOURNEYS, past_memories=PAST, facts=FACTS)
        out.append(f"===== {q}\n返事: {r}（{g}・{persona.get('memory', {}).get('check')}）")
        if sent:
            out.append(f"--- system\n{sent[0][0]['content']}\n--- 最後の user\n{sent[0][-1]['content']}\n")
        else:
            out.append("（モデルを呼ばない）\n")
    text = "\n".join(out)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
