"""
fix_route_labels.py — 振り分けの定義を決め直したので、評価用データの正解をそろえる

  python fix_route_labels.py --files route_dev.jsonl route_test.jsonl

決めた定義（2026-10-19）
- 相談（身近な小さな悩みも）・具体的な助言・文章作り → 込み入った質問
- ペットの今の気分や様子を軽くたずねる → 雑談
- ペットのデータを見ないと答えられないこと（種族・体・好み・お別れまでの日数・旅など）→ ペット自身

最後の飼い主の発言が下の表にある行だけ直す。直す前のファイルは .bak に残す。
"""
import argparse
import json
import shutil

FIX = {
    # 相談・助言・文章作り → 込み入った質問
    "親友が引っ越すねん 最後に何してあげたらいいかな": "込み入った質問",
    "誕生日プレゼント何あげたらいいと思う 友達に": "込み入った質問",
    "最近ずっと寝られへんねん どうしたらいい": "込み入った質問",
    "先生への感謝のメッセージ 文章にして": "込み入った質問",
    "部活の先輩と合わへんくて悩んでる": "込み入った質問",
    "おばあちゃんに手紙書きたい 一緒に考えて": "込み入った質問",
    "進路のことで親とケンカしてん どうしたらええと思う": "込み入った質問",
    "友達に謝りたいんやけど なんて言えばいいかな": "込み入った質問",
    "明日の発表の練習付き合って 構成考えてほしい": "込み入った質問",
    "うん クラスでちょっと浮いてる気がして どうしたらいい": "込み入った質問",
    "インスタの自己紹介文考えて": "込み入った質問",
    "受験勉強と部活 両立する方法ある？": "込み入った質問",
    "俳句作りたいんやけど手伝って": "込み入った質問",
    "ぶっちゃけ文系と理系どっちがいいと思う": "込み入った質問",
    # ペットの今の気分・様子を軽くたずねる → 雑談
    "今日の気分はどう？": "雑談",
    "最近楽しいことあった？": "雑談",
    "きみ眠い？": "雑談",
    "さみしくない？": "雑談",
    "元気？": "雑談",
    "今何考えてるん": "雑談",
    "どしたん 大丈夫？": "雑談",
    "え、どうしたん？今どんな気持ち？": "雑談",
    # 前に二人で話したことを持ち出している → 思い出
    "前の日曜に話したこと 母さんにも言ったで": "思い出",
    # ペットのデータが要る → ペット自身
    "何の動物なん？犬？": "ペット自身",
    "海好きなん？": "ペット自身",
    "きみの体の色って変わったりするん": "ペット自身",
    "あと何日でお別れなん": "ペット自身",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", required=True)
    a = ap.parse_args()
    for path in a.files:
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        changed = []
        for r in rows:
            new = FIX.get(r["turns"][-1]["text"])
            if new is not None and r["labels"].get("route") != new:
                changed.append((r["turns"][-1]["text"], r["labels"].get("route"), new))
                r["labels"]["route"] = new
        shutil.copy(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{path}: {len(rows)} 件中 {len(changed)} 件を直しました")
        for text, old, new in changed:
            print(f"  「{text}」 {old} → {new}")
        rest = [r for r in rows if r["labels"].get("route") == "ペット自身" and r["turns"][-1]["text"] not in FIX]
        if rest:
            print(f"  （確認用）ほかに「ペット自身」の行 {len(rest)} 件。今の気分を聞くだけの文が混ざっていないか見てください:")
            for r in rest:
                print(f"    「{r['turns'][-1]['text']}」")
        print()


if __name__ == "__main__":
    main()