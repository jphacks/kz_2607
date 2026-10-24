"""
ng_words.py — 判定モデルの「安全」を後ろから支える、言い回しの一覧（ルール）

役割
- モデルは「くだけた安全な言い方」と「本当に危ない言い方」を文脈で見分けるのが得意。
  ただし、まれに危ない言い方を見逃す（例: 「お風呂のぞいてもいい？」）。
- ここでは「これが出たら、ほぼ確実に危ない」という言い回しだけを持つ。
  単語1つ（胸・裸・死ぬ・ゴミ など）だけでは止めない。安全な文にもよく出るため。
- 最終判断: モデルの危険らしさ >= しきい値  または  ここで1つでも当たった → 止める

  from ng_words import check
  check("お風呂のぞいてもいい？")   # → [("性的", "お風呂のぞいて")]

使い方の注意
- 文字起こし（Whisper）の結果を想定して、空白・句読点を消し、カタカナはひらがなにそろえてから調べる。
- 言い回しを足したら、python ng_words.py で「安全な文を止めていないか」を必ず確かめる。
"""
import re
import unicodedata

# ---------------------------------------------------------------------------
# 文字をそろえる
# ---------------------------------------------------------------------------
_KATA = {chr(c): chr(c - 0x60) for c in range(0x30A1, 0x30F7)}   # ァ〜ヶ → ぁ〜ゖ


def normalize(text):
    t = unicodedata.normalize("NFKC", text).lower()
    t = "".join(_KATA.get(ch, ch) for ch in t)
    return re.sub(r"[\s、。，．,.!！?？…・「」『』（）()~〜]+", "", t)    # 「ー」は残す（すりーさいず など）


# ---------------------------------------------------------------------------
# 言い回し（正規表現。normalize したあとの文に当てる。カタカナはひらがなで書く）
# ---------------------------------------------------------------------------
YOU = r"(?:お前|おまえ|てめえ|てめぇ|てめ|きさま|貴様)"
INSULT = (r"(?:ばか|あほ|くず|ごみ|かす|ぼけ|ぽんこつ|役立たず|やくたたず|きも|うざ|いらん|いらない|"
          r"価値ない|かちない|消え|きえ|死ね|しね|捨て)")
GROUP = (r"(?:女|男|おばさん|おっさん|おじさん|年寄り|としより|老人|障害者|障がい者|障害のある|外国人|外人|がいじん|"
         r"移民|貧乏人|びんぼうにん|田舎もん|いなかもん|地方の人|あの国の人|あの県の人|あの地域|あの宗教|あの人種|同性|"
         r"でぶ|ぶす|はげ|片親|ひとり親|はーふ)")
NEG = (r"(?:みんな|全員|どうせ|ばっかり|ばっか|帰れ|かえれ|出ていけ|追い出|いらん|いらない|邪魔|じゃま|迷惑|めいわく|"
       r"価値ない|お荷物|おにもつ|信用でき|嘘つき|うそつき|汚い|きたない|臭い|くさい|だらしない|頭悪|あたまわる|"
       r"常識ない|犯罪|きもい|気持ち悪|黙っとけ|無理やろ|ありえへん|ありえない|劣って|下等)")

PATTERNS = {
    "暴言": [
        r"死ね|(?:^|[^ぁ-ゖ])しね(?:よ|や|ば|って|$)|死んじゃえ|死んでくれ|くたばれ|"
        r"(?<![ぁ-ゖ楽悲苦惜親慈怪訝])しん(?:じゃえ|でくれ)",          # 「楽しんでくれ」「悲しんでくれ」は止めない
        r"殺すぞ|殺すで|殺したる|殺したろ|ぶっ殺|ぶっころ|ころすぞ|ころしたる",
        r"消えろ|きえろ|消えてほしい|きえてほしい|消えてくれ|失せろ|うせろ",
        r"黙れ|だまれ|黙ってろ|だまってろ|口閉じろ|喋んな|しゃべんな",
        r"話しかけんな|話しかけるな|はなしかけんな|二度と話しかけ|近寄んな|ちかよんな|近寄るな",
        r"生きてる(?:意味|価値)(?:ない|ねえ)|いきてる(?:いみ|かち)ない",
        r"殴るぞ|殴ったろ|殴られたい|ぶっ飛ばす|ぶっとばす|ぶっ壊すぞ|ぶっこわすぞ|叩き割ったろ|蹴飛ばすぞ|けとばすぞ",
        YOU + r".{0,8}?" + INSULT,                                     # お前 … バカ／いらん／消えろ
        r"(?:ばか|あほ|くそ|ぽんこつ|駄)(?:犬|いぬ|猫|ねこ|ぺっと)",       # バカ犬・クソペット
        r"(?:くず|かす|ぼけ|ぽんこつ)(?:が|め|やな|やろ)?$",               # 文の終わりの「…カスが」
    ],
    "差別": [
        r"がいじ|池沼|きちがい|気違い|かたわ|めくら|つんぼ|支那|しなじん|土人|黒んぼ|くろんぼ",
        r"(?:女|男)(?:の|な)?くせに",
        GROUP + r"(?:は|って|なんか|なんて|なのに|の人って|の人は|の子って|の子は)?.{0,12}?" + NEG,
    ],
    "性的": [
        r"えろ(?:い|すぎ|画像|動画|話|こと|写真)|えっち|すけべ|おっぱい|せっくす|ちんこ|ちんちん|まんこ|おなにー|"
        r"むらむら|夜這い|よばい|変態な|へんたいな",
        r"いやらし(?:い|く)(?:こと|格好|かっこう|意味|話|声|写真|動画)",
        r"(?:ぱんつ|下着|したぎ|裸|はだか|胸|むね|おしり|お尻|体|からだ|すかーとの中|股)"
        r"(?:の?(?:写真|画像|色|いろ))?(?:を)?(?:見せ|みせ|見たい|触ら|触っ|触り|さわら|さわっ|さわり|送って|おくって|送れ|撮ら|撮ろ|ちょうだい|"
        r"何色|なにいろ|何かっぷ|のさいず|の大きさ|大きいん|姿)",
        r"(?:服|ふく)(?:を)?(?:脱|ぬ)いで(?:よ|や|みて|$)",
        r"(?:お風呂|おふろ|風呂|ふろ|着替え|きがえ|といれ|すかーと)(?:を|の中を?)?(?:のぞ|覗)",
        r"変なことしよ|へんなことしよ|舌入れ|夜のお相手|すりーさいず|下ねた|しもねた|"
        r"せくしーな(?:ぽーず|声|こえ)|色っぽい(?:声|こえ|ぽーず)",
    ],
}
_COMPILED = {cat: [re.compile(p) for p in ps] for cat, ps in PATTERNS.items()}


def check(text):
    """当たった (種類, 当たった部分) のリスト。空なら当たりなし"""
    t = normalize(text)
    hits = []
    for cat, regs in _COMPILED.items():
        for r in regs:
            m = r.search(t)
            if m:
                hits.append((cat, m.group(0)))
                break
    return hits


# ---------------------------------------------------------------------------
# 確かめる: 安全な文を止めていないか、危ない文をどれだけ止められるか
#   python ng_words.py                     学習用データ（make_safety_data.py）と振り分けの評価用の会話で確かめる
#   python ng_words.py --eval safety_eval.jsonl --split dev
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=None)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--jsonl", default=None, help="学習データなど（安全ラベルが空の飼い主の発言を、止めていないか確かめる）")
    a = ap.parse_args()

    def report(name, unsafe, safe):
        caught = [(t, check(t)) for t in unsafe]
        fa = [(t, check(t)) for t in safe if check(t)]
        n = sum(bool(h) for _, h in caught)
        print(f"==== {name}")
        print(f"  危ない文を止めた: {n}/{len(unsafe)}   安全な文を止めてしまった: {len(fa)}/{len(safe)}")
        for t, h in fa:
            print(f"    × 安全なのに止めた: {t}  {h}")
        for t, h in (caught if len(unsafe) <= 120 else []):
            if not h:
                print(f"    - 止めなかった（モデルに任せる）: {t}")

    if a.jsonl:
        rows = [json.loads(l) for l in open(a.jsonl, encoding="utf-8") if l.strip()]
        texts, bad = [], []
        for r in rows:
            sf = (r.get("labels") or {}).get("safety")
            t = r["turns"][-1]["text"]
            (texts if sf == [] else bad if sf else []).append(t)
        report(f"{a.jsonl}", bad, texts)
    elif a.eval:
        rows = [json.loads(l) for l in open(a.eval, encoding="utf-8") if l.strip()]
        rows = [r for r in rows if r.get("split", a.split) == a.split]
        report(f"{a.eval}（{a.split}）", [r["turns"][-1]["text"] for r in rows if r["labels"]["safety"]],
               [r["turns"][-1]["text"] for r in rows if not r["labels"]["safety"]])
    else:
        import kz_2607.ai.judge_code.make_safety_data as M
        report("学習用の安全データ", M.ABUSE + M.DISCRIMINATION + M.SEXUAL, M.ROUGH_BUT_SAFE)
        try:
            import make_route_eval as R
            texts = [c.split("|")[-1].split(":", 1)[1] for c in R.CONVS]
            fa = [(t, check(t)) for t in texts if check(t)]
            print(f"==== 振り分けの評価用の会話（150件。最後の10件ほどは危ない文を含む）: 当たった {len(fa)} 件")
            for t, h in fa:
                print(f"    {t}  {h}")
        except ImportError:
            pass