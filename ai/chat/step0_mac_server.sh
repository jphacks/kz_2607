#!/usr/bin/env bash
# Step 0-2: 確認用LoRA（tiny_lora）を GGUF に変換し、llama-server に載せて起動する
#
# 使い方:
#   1. Colab で作った tiny_lora フォルダを、このスクリプトと同じ場所に置く
#      （中に adapter_config.json と adapter_model.safetensors があること）
#   2. bash step0_mac_server.sh
#   3. 起動したままにして、別のターミナルで python step0_check_switch.py
#
# 前提（初回だけ）:
#   brew install llama.cpp
#   git clone --depth 1 https://github.com/ggml-org/llama.cpp ~/llama.cpp    # 変換スクリプトのため
#   pip install -r ~/llama.cpp/requirements/requirements-convert_lora_to_gguf.txt
#   pip install -U huggingface_hub requests
set -euo pipefail

BASE_HF="LiquidAI/LFM2.5-1.2B-JP"          # Colab で学習に使ったものと同じ元モデル
BASE_GGUF="LiquidAI/LFM2.5-1.2B-JP-GGUF"   # 判定モデルの測定で動いた公式 GGUF
WORK="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$WORK/tiny_lora/adapter_config.json" ]; then
  echo "tiny_lora/adapter_config.json が見つかりません。tiny_lora フォルダをこの場所に置いてください: $WORK" >&2
  exit 1
fi

# 1) 元モデルの設定ファイルだけ取る（LoRA の変換に設定が要る。重み本体はダウンロードしない）
if [ ! -f "$WORK/base_config/config.json" ]; then
  hf download "$BASE_HF" --include "*.json" --local-dir "$WORK/base_config" \
    || huggingface-cli download "$BASE_HF" --include "*.json" --local-dir "$WORK/base_config"
fi

# 2) LoRA を GGUF に
python ~/llama.cpp/convert_lora_to_gguf.py "$WORK/tiny_lora" \
  --base "$WORK/base_config" \
  --outfile "$WORK/tiny_lora.gguf" --outtype f16

echo "変換できました: $WORK/tiny_lora.gguf"

# 3) サーバー起動（LoRAは読み込むだけで、強さ0から始める。強さは依頼ごとに指定する）
#    --parallel 2: 同時に2つの依頼を受けられるようにする（混ざらないかの確認用）
llama-server -hf "$BASE_GGUF" \
  --lora "$WORK/tiny_lora.gguf" \
  --lora-init-without-apply \
  --parallel 2 \
  --host 127.0.0.1 --port 8080 -c 4096
