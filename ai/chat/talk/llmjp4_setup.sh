#!/usr/bin/env bash
# LLM-jp-4 8B instruct を Mac で動かす準備（GGUF に変換して 4bit に縮める）→ LoRA なしで 8081 番に起動
#
# 使い方（Mac の judge_for_mac/chat/talk で、(chat) の環境を有効にして）:
#   bash llmjp4_setup.sh   # 初回：元のモデル（約17GB）と 4bit の GGUF（約5GB）をダウンロード → 起動
#                          # 2回目以降：そのまま起動
#
# GGUF は配布されている変換済みの版（mosh-hf）を使う（llama.cpp がまだ LLM-jp-4 のトークナイザーを知らないため）。
# 会話の形式（chat template）は元のモデルから取り出して --chat-template-file で渡す
set -euo pipefail

WORK="$(cd "$(dirname "$0")" && pwd)"
HF_ID="llm-jp/llm-jp-4-8b-instruct"
DIR="$WORK/llmjp4"
Q4="$DIR/llmjp4-8b-instruct-Q4_K_M.gguf"
GGUF_REPO="mosh-hf/llm-jp-4-8b-instruct-GGUF"
GGUF_FILE="llm-jp-4-8b-instruct-Q4_K_M.gguf"
mkdir -p "$DIR"

# 元のモデル（トークナイザー・設定・会話の形式）。LoRA の学習と、会話の形式を取り出すのに使う
if [ ! -f "$DIR/hf/config.json" ]; then
  echo "ダウンロード: ${HF_ID}（約17GB）"
  hf download "$HF_ID" --local-dir "$DIR/hf" \
    || huggingface-cli download "$HF_ID" --local-dir "$DIR/hf"
fi

# GGUF（4bit）：llama.cpp がまだ LLM-jp-4 のトークナイザーを知らず自分では変換できないので、
#               配布されている変換済みの版を使う
if [ ! -f "$Q4" ]; then
  echo "ダウンロード: ${GGUF_REPO} の Q4_K_M（約5GB）"
  hf download "$GGUF_REPO" "$GGUF_FILE" --local-dir "$DIR" \
    || huggingface-cli download "$GGUF_REPO" "$GGUF_FILE" --local-dir "$DIR"
  mv "$DIR/$GGUF_FILE" "$Q4"
fi

# 会話の形式（chat template）を元のモデルから取り出す（配布版の GGUF には入っていないことがあるため）
TEMPLATE="$DIR/chat_template.jinja"
if [ ! -f "$TEMPLATE" ]; then
  if [ -f "$DIR/hf/chat_template.jinja" ]; then
    cp "$DIR/hf/chat_template.jinja" "$TEMPLATE"
  else
    python3 -c "import json,sys;t=json.load(open(sys.argv[1])).get('chat_template');t=t if isinstance(t,str) else t[0]['template'];open(sys.argv[2],'w').write(t)" \
      "$DIR/hf/tokenizer_config.json" "$TEMPLATE"
  fi
fi
echo "会話の形式: ${TEMPLATE}（$(wc -l < "$TEMPLATE") 行）"

# LoRA の GGUF 変換で使う設定（元のモデルの json だけ）
mkdir -p "$DIR/base_config"
cp "$DIR"/hf/*.json "$DIR/base_config/" 2>/dev/null || true

# 8081番が使われていたら止める（1.2B のサーバーなど）
lsof -ti :8081 | xargs kill 2>/dev/null || true
sleep 1

# 起動（LoRA なし）。--jinja でモデルに入っている会話の形式をそのまま使う
llama-server -m "$Q4" --jinja --chat-template-file "$TEMPLATE" \
  --parallel 2 \
  --host 127.0.0.1 --port 8081 -c 4096