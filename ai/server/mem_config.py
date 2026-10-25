"""
mem_config.py — 思い出の返事の設定（環境変数）。ほかのファイルは `import mem_config as C` で C.MEMORY_MIN_SIM のように読む
（check_memory.py の --min-sim などで、あとから値を変えられるようにするため）
"""
import os

MEMORY_MIN_SIM = float(os.environ.get("MEMORY_MIN_SIM", "0.83"))       # 10/24 の Ruri の値から（仮）
MEMORY_MIN_LIFT = float(os.environ.get("MEMORY_MIN_LIFT", "0.05"))     # 1位 − 全件の中央値 の下限
MEMORY_SECOND_GAP = float(os.environ.get("MEMORY_SECOND_GAP", "0.02"))  # 2件目は 1位 − この値 まで
MEMORY_LIFT_MIN_N = int(os.environ.get("MEMORY_LIFT_MIN_N", "5"))      # 中央値を使う思い出の件数
MEMORY_MIN_LEX = float(os.environ.get("MEMORY_MIN_LEX", "0.3"))
MEMORY_TEMP = float(os.environ.get("MEMORY_TEMP", "0.3"))
MEMORY_PROMPT = os.environ.get("MEMORY_PROMPT", "react")  # react（中身は決まった文・気持ちだけモデル）・rewrite・hint
MEMORY_BABY = os.environ.get("MEMORY_BABY", "template")   # template（赤ちゃんは決まった返事）・model
MEMORY_RURI = os.environ.get("MEMORY_RURI", "auto").lower()
RURI_MODEL = os.environ.get("RURI_MODEL", "cl-nagoya/ruri-v3-130m")
MEMORY_TOPK = 2
Q_PREFIX, D_PREFIX = "検索クエリ: ", "検索文書: "
