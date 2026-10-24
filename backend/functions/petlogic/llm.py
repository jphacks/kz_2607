"""OpenAI への接続。文章を作らせる。"""
import json
import urllib.error
import urllib.request

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT_SEC = 90


class LlmError(Exception):
    pass


def openai_chat(system, user, api_key, model, url=OPENAI_URL, json_mode=False, timeout=TIMEOUT_SEC):
    """system と user の2つの文を渡して、返ってきた文章を返す。"""
    if not api_key or not model:
        raise LlmError("OPENAI_API_KEY か OPENAI_MODEL が設定されていません")
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key.strip()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise LlmError(f"OpenAI が {e.code} を返しました: {e.read()[:200]!r}")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as e:
        raise LlmError(f"OpenAI の呼び出しに失敗しました: {type(e).__name__}: {e}")
    if not isinstance(text, str) or not text.strip():
        raise LlmError("OpenAI の返事に、文章がありません")
    return text.strip()
