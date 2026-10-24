"""
gold_sheet.py — 評価用データを「回答用紙（テキスト）」で付けるための変換

  python gold_sheet.py make  --src gold_template.jsonl --out gold_sheet.txt   # 用紙を作る
  python gold_sheet.py parse --src gold_sheet.txt      --out gold.jsonl       # 記入済みの用紙 → JSONL

parse は書き間違いを全部まとめて表示する（1つでもあれば gold.jsonl は書き出さない）。
"""
import argparse
import json
import re
import sys

ROUTE = {"1": "雑談", "2": "思い出", "3": "ペット自身", "4": "込み入った質問"}
# 気持ちは5つ。前の8種類で書いた「恐」「嫌」はそれぞれ「不安」「怒り」として読む（「信」「期」は外れる）
EMO = {"喜": "喜び", "怒": "怒り", "悲": "悲しみ", "不": "不安", "驚": "驚き", "恐": "不安", "嫌": "怒り"}
NATURE = {"理": "理屈", "感": "感覚", "質": "質問"}
REACTION = {"共": "共感", "ツ": "ツッコミ", "ボ": "ボケ", "褒": "褒める"}
SAFETY = {"暴": "暴言", "差": "差別", "性": "性的"}
NONE_WORDS = {"なし", "無し", "-", "ー", "0"}

HEADER = """# 評価用データ 回答用紙（50件）
#
# 判定するのは、各会話の「▶」の付いた最後の飼い主の発言です。上の行は文脈として読んでください。
# 書くのは「振り分け」だけで十分です。ほかの項目は、空欄なら評価に使わないだけです。
# 「安全」は空欄なら「安全」として扱います。危険なときだけ書いてください。
#
# 【振り分け】1=雑談  2=思い出  3=ペット自身  4=込み入った質問
#     迷うときは割合で  例) 1:0.6 2:0.4
# 【安全】  暴=暴言  差=差別  性=性的（複数なら続けて 例: 暴差）／空欄=安全
# 【気持ち】喜=喜び 怒=怒り 悲=悲しみ 不=不安 驚=驚き のどれか1つ／特に出ていなければ「なし」
#     迷うときは割合で  例) 喜:0.5 期:0.5
# 【強さ】  気持ちの強さ 0〜1（例: 0.6）
# 【性質】  理=理屈  感=感覚  質=質問（複数なら続けて 例: 理質）／当てはまらなければ「なし」
# 【話し方】敬語の度合い, 関西弁の度合い を 0〜1 で（例: 0, 0.8）
# 【反応】  直前のペットの発言への反応  共=共感 ツ=ツッコミ ボ=ボケ 褒=褒める／なければ「なし」
#
# 答えは「：」の右に書く。記号の代わりに「思い出」「暴言」のように言葉で書いてもよい。
# APIのラベルを見る前に付けてください。
"""

FIELDS = ["振り分け", "安全", "気持ち", "強さ", "性質", "話し方", "反応"]


def make(src, out):
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    with open(out, "w", encoding="utf-8") as f:
        f.write(HEADER)
        for r in rows:
            f.write(f"\n## {r['id']}\n")
            for i, t in enumerate(r["turns"]):
                who = "飼い主" if t["speaker"] == "owner" else "ペット"
                mark = "▶" if i == len(r["turns"]) - 1 else "  "
                f.write(f"{mark} {who}：{t['text']}\n")
            for k in FIELDS:
                f.write(f"{k}：\n")
    print(f"{len(rows)} 件の用紙を作りました → {out}")


# ---------------------------------------------------------------------------
def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFKC", s)                  # 全角の数字・記号を半角に
    return s.strip().replace("、", ",")


def _pick(token, table, what):
    token = token.strip()
    if token in table:
        return table[token]
    if token in table.values():
        return token
    raise ValueError(f"{what}「{token}」が分かりません（使える記号: {' '.join(table)}）")


def _single(value, table, what):
    """1つを選ぶ項目。'2' / '思い出' / '1:0.6 2:0.4' を受け付ける"""
    v = _norm(value)
    if ":" not in v:
        return _pick(v, table, what)
    probs = {}
    for part in re.split(r"[\s,]+", v):
        if not part:
            continue
        k, _, p = part.partition(":")
        probs[_pick(k, table, what)] = float(p)
    if abs(sum(probs.values()) - 1) > 0.05:
        raise ValueError(f"{what}の割合の合計が1になっていません: {v}")
    return probs


def _multi(value, table, what):
    """複数可の項目。'暴差' / '暴言,差別' / 'なし' を受け付ける"""
    v = _norm(value)
    if v in NONE_WORDS:
        return []
    out = []
    parts = [p for p in re.split(r"[\s,]+", v) if p]
    for p in parts:
        if p in table.values():
            out.append(p)
        else:                                       # 記号を続けて書いたもの（例: 理質、ツボ）
            out += [_pick(ch, table, what) for ch in p]
    return sorted(set(out))


def _unit(value, what):
    x = float(_norm(value))
    if not 0 <= x <= 1:
        raise ValueError(f"{what}は 0〜1 で書いてください: {value}")
    return x


def parse(src, out, template, style1=None, max_show=15):
    tmpl = {}
    if template:
        tmpl = {r["id"]: r for r in (json.loads(l) for l in open(template, encoding="utf-8") if l.strip())}

    blocks, cur = [], None
    for line in open(src, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("#") and not line.startswith("## "):
            continue
        if line.startswith("## "):
            cur = {"id": line[3:].strip(), "turns": [], "ans": {}}
            blocks.append(cur)
        elif cur is not None and line.strip():
            body = line.strip().lstrip("▶").strip()
            key, sep, val = body.partition("：")
            if not sep:
                key, sep, val = body.partition(":")
            if key in ("飼い主", "ペット"):
                cur["turns"].append({"speaker": "owner" if key == "飼い主" else "pet", "text": val.strip()})
            elif key in FIELDS:
                cur["ans"][key] = val.strip()

    def style(v):
        parts = [p for p in re.split(r"[\s,]+", _norm(v)) if p]
        if len(parts) == 2:
            return {"敬語": _unit(parts[0], "敬語"), "関西弁": _unit(parts[1], "関西弁")}
        if len(parts) == 1 and style1 in ("敬語", "関西弁"):     # 数を1つだけ書いた場合の読み方
            other = "関西弁" if style1 == "敬語" else "敬語"
            return {style1: _unit(parts[0], style1), other: 0.0}
        raise ValueError(f"話し方は「敬語, 関西弁」の2つの数で書いてください: {v}")

    # 必須（間違いがあれば止める）と任意（間違いがあればその項目だけ外す）
    required = [("振り分け", "route", lambda v: _single(v, ROUTE, "振り分け")),
                ("安全", "safety", lambda v: _multi(v, SAFETY, "安全"))]
    optional = [("気持ち", "emotion", lambda v: None if _norm(v) in NONE_WORDS else _single(v, EMO, "気持ち")),
                ("強さ", "intensity", lambda v: _unit(v, "強さ")),
                ("性質", "nature", lambda v: _multi(v, NATURE, "性質")),
                ("話し方", "style", style),
                ("反応", "reaction", lambda v: _multi(v, REACTION, "反応"))]

    rows, errors, warns, n_done = [], [], [], 0
    for b in blocks:
        a, labels = b["ans"], {}
        if not a.get("振り分け"):
            if any(a.get(k) for k, _, _ in required + optional):
                warns.append(f"  {b['id']}: 振り分けが空欄なので、この会話は使いません")
            continue
        try:
            labels["route"] = required[0][2](a["振り分け"])
            labels["safety"] = required[1][2](a["安全"]) if a.get("安全") else []
        except ValueError as e:
            errors.append(f"  {b['id']}: {e}")
            continue
        for key, name, fn in optional:
            if a.get(key):
                try:
                    v = fn(a[key])
                    if v is not None:
                        labels[name] = v
                except ValueError as e:
                    warns.append(f"  {b['id']}: {key}を外しました（{e}）")
        turns = tmpl[b["id"]]["turns"] if b["id"] in tmpl else b["turns"]   # 会話は元のデータを優先
        n_done += 1
        rows.append({"id": b["id"], "turns": turns, "labels": labels})

    if warns:
        print(f"注意 {len(warns)} 件（その項目だけ外して続けます）")
        print("\n".join(warns[:max_show]) + (f"\n  ...ほか {len(warns) - max_show} 件" if len(warns) > max_show else ""))
    if errors:
        print(f"\n振り分け・安全の書き間違いが {len(errors)} 件あります（gold.jsonl は書き出していません）")
        print("\n".join(errors))
        sys.exit(1)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            if r["labels"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{n_done} 件を書き出しました → {out}（未記入 {len(rows) - n_done} 件は除外）")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["make", "parse"])
    p.add_argument("--src", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--template", default=None, help="parse のとき、会話の元データ（gold_template.jsonl）")
    p.add_argument("--style1", choices=["敬語", "関西弁"], default=None,
                   help="話し方に数を1つだけ書いたとき、それを敬語・関西弁のどちらとして読むか（指定しなければ外す）")
    a = p.parse_args()
    make(a.src, a.out) if a.cmd == "make" else parse(a.src, a.out, a.template, a.style1)