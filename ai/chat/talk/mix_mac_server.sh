#!/usr/bin/env bash
# 6軸の性格LoRAを GGUF に変換し、llama-server に全部載せて起動する
#
# 使い方（Mac の judge_for_mac/chat で、uv の .venv を有効にして）:
#   1. Drive の chat/lora/axis_active 〜 axis_night の6フォルダを、このスクリプトと同じ場所の lora/ に置く
#        lora/axis_active/adapter_config.json, adapter_model.safetensors
#        lora/axis_affection/ ... lora/axis_night/ も同じ
#   2. bash mix_mac_server.sh
#   3. 起動したままにして、別のターミナルで python mix_check.py
#
# DPO 版を載せるとき:
#   lora_dpo/axis_active/ 〜 axis_night/ に DPO の LoRA を置いて
#   LORA_SET=dpo bash mix_mac_server.sh      （lora_gguf_dpo/ に変換して載せる）
#   2回目の DPO は lora_dpo2/ に置いて LORA_SET=dpo2
#
# 前提: 手順0で使った ~/llama.cpp（変換スクリプト）と base_config/（元モデルの設定）がある
set -euo pipefail

BASE_HF="LiquidAI/LFM2.5-1.2B-JP"
BASE_GGUF="LiquidAI/LFM2.5-1.2B-JP-GGUF"
WORK="$(cd "$(dirname "$0")" && pwd)"
AXES=(active affection talkative logic curious night)   # この順番が LoRA の id 0〜5 になる

# 元モデルの設定（手順0で取ってあれば何もしない）
if [ ! -f "$WORK/base_config/config.json" ]; then
  hf download "$BASE_HF" --include "*.json" --local-dir "$WORK/base_config" \
    || huggingface-cli download "$BASE_HF" --include "*.json" --local-dir "$WORK/base_config"
fi

# どの LoRA を載せるか（SFT 版：lora/ → lora_gguf/、DPO 版：lora_dpo/ → lora_gguf_dpo/）
# LORA_SET=dpo → lora_dpo/、LORA_SET=dpo2 → lora_dpo2/
SUFFIX=""
[ -n "${LORA_SET:-}" ] && SUFFIX="_$LORA_SET"
SRC_DIR="$WORK/lora$SUFFIX"
GGUF_DIR="$WORK/lora_gguf$SUFFIX"
echo "載せる LoRA: $SRC_DIR"

mkdir -p "$GGUF_DIR"
LORA_FILES=()
for ax in "${AXES[@]}"; do
  src="$SRC_DIR/axis_$ax"
  out="$GGUF_DIR/axis_$ax.gguf"
  if [ ! -f "$src/adapter_config.json" ]; then
    echo "※ $src/adapter_config.json がありません" >&2
    exit 1
  fi
  # LoRA が新しくなっていたら変換し直す
  if [ ! -f "$out" ] || [ "$src/adapter_model.safetensors" -nt "$out" ]; then
    echo "変換: axis_$ax"
    python ~/llama.cpp/convert_lora_to_gguf.py "$src" --base "$WORK/base_config" --outfile "$out" --outtype f16
  fi
  LORA_FILES+=("$out")
done
# 共通LoRA は使わないことにしたので載せない
echo "${#LORA_FILES[@]} 個の LoRA を変換しました: $GGUF_DIR/"
# 今の llama.cpp は、複数の LoRA をカンマでつないで1回で渡す（--lora を何回も書くと最後の1つしか使わない）
LORA_LIST="$(IFS=,; echo "${LORA_FILES[*]}")"

# 8081番が使われていたら止める（前に起動したこのサーバーなど）
lsof -ti :8081 | xargs kill 2>/dev/null || true
sleep 1

# 起動（LoRA は読み込むだけで強さ0から。強さは依頼ごとに指定する）
llama-server -hf "$BASE_GGUF" \
  --lora "$LORA_LIST" \
  --lora-init-without-apply \
  --parallel 2 \
  --host 127.0.0.1 --port 8081 -c 4096