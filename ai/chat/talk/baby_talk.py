"""
赤ちゃんの返事を「子どもの返事」から作る（eval_generate.py・talk_server.py で共通）

1.2B のモデルに「ひらがなだけ」で考えさせると、ありもしない言葉ができやすい。
そこで、ふだんどおり子どもの段階で返事を作らせてから、次のように赤ちゃん言葉に直す。
  1. 最初の一文だけ残す（長ければ最初の「、」まで）
  2. 一人称（ぼく・わたし など）を取る
  3. 漢字をひらがなに直す（pykakasi。Mac で `pip3 install pykakasi`）
  4. 文の終わりの「だよ・ね」などを取って、生まれたときの口ぐせを付ける
"""
import re

FIRST_PERSON = re.compile(r"(ぼく|ボク|僕|わたし|ワタシ|私|おれ|オレ|俺|あたし|アタシ)(は|も|が|の|ね)?")
KANJI = re.compile(r"[一-龯々]")
SENT_END = re.compile(r"(.+?[。！？!?…]+)")
# pykakasi が読み違える言葉は先に直す（「今日は」→「こんにちは」になる など）
READINGS = {"今日": "きょう", "明日": "あした", "昨日": "きのう", "一緒": "いっしょ", "大人": "おとな",
            "今朝": "けさ", "今夜": "こんや", "上手": "じょうず", "下手": "へた", "一人": "ひとり", "二人": "ふたり"}
TAIL = re.compile(r"(んだよね|んだよ|んだね|んだ|のだ|だよね|だよ|だね|だな|です|よね|だ|よ|ね|な|さ)?[。！？!?…〜ー、\s]*$")
BODY_MAX = 14

_kks = None


def to_hiragana(text):
    global _kks
    for k, v in READINGS.items():
        text = text.replace(k, v)
    if not KANJI.search(text):
        return text
    if _kks is None:
        import pykakasi
        _kks = pykakasi.kakasi()
    out = []
    for seg in _kks.convert(text):
        out.append(seg["hira"] if KANJI.search(seg["orig"]) else seg["orig"])
    return "".join(out)


def first_sentence(text):
    text = text.strip().split("\n")[0]
    sents = SENT_END.findall(text) or [text]
    s = sents[0]
    # 「いいな！」のように短すぎて中身がないときは、次の文もつなげる（長くなりすぎないとき）
    if len(s) < 6 and len(sents) > 1 and len(s) + len(sents[1]) <= BODY_MAX + 6:
        s = s + sents[1]
    # 長すぎるときは最初の「、」まで（3文字以上残るとき）
    if len(s) > BODY_MAX + 4 and "、" in s:
        head = s.split("、")[0]
        if len(head) >= 3:
            s = head
    return s


def to_baby(text, ending):
    """ending は「〜だよっ！」「あのね、〜」のような口ぐせ（〜の位置に中身が入る）"""
    s = first_sentence(text)
    s = FIRST_PERSON.sub("", s)
    s = re.sub(r"^(あのね|あのさ)[、,]?", "", s)  # 口ぐせを二重にしない
    s = to_hiragana(s)
    core = ending.replace("〜", "").strip("、！？…っ ")
    body = TAIL.sub("", s).strip("、 ")
    if len(body) <= 3:  # 「いいな」→「いい」のように削りすぎるときは、文の終わりを残す
        body = re.sub(r"[。！？!?…〜ー、\s]+$", "", s)
    if core and body.endswith(core):
        body = body[: -len(core)]
    if not body:
        body = s.strip("。！？!?… ")
    if ending.startswith("〜"):
        return ending.replace("〜", body)
    # 「あのね、〜」のように前に付く口ぐせ
    return ending.replace("〜", body) + ("！" if not re.search(r"[！？!?…]$", body) else "")


if __name__ == "__main__":
    tests = [("いいな！あのね、今日はおはよう、ぼくもがんばりたいなって思ったんだ。", "あのね、〜"),
             ("うれしいね！あしたもきみがにっこり笑ってくれるといいな。ぼく、ふぁ…", "〜ふぁ…"),
             ("今日は雨で残念だったね。でも明日は晴れるといいな！", "〜なの"),
             ("ぼくもいっしょに行きたいな、楽しそう！", "〜だよっ！"),
             ("テスト、すごく頑張ったんだね！えらい！", "あのね、〜"),
             ("夜ってなんだか元気が出るよね。", "〜ふぁ…"),
             ("おいしいものを食べたの？いいなあ。", "〜かな？"),
             ("それは傘を持っていくのがいいのだ。", "〜なのだ")]
    for t, e in tests:
        print(f"{t}  →  {to_baby(t, e)}")