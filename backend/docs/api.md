# バックエンドAPI(フロント・組み込み向け)

すべて、Firebaseの呼び出し可能関数(callable)。リージョンは `asia-northeast1`。
呼ぶ前に、Firebase Authenticationの**匿名ログイン**を済ませておくこと。

## registerDevice
端末を登録して、結びついたペットを返す。アプリを開いたときに、最初に1回呼ぶ。
2回目以降は、同じペットを返す(作り直さない)。

| 項目 | 内容 |
| --- | --- |
| 送る | `deviceId`: 端末を区別する文字列。英数字と `_ . : -` の1〜64文字 |
| 返る | `deviceId`、`petId`: ペットのID、`isNew`: 今回、新しく作ったか(`true` / `false`) |

エラー:
- `invalid-argument`: `deviceId` の形が違う
- `permission-denied`: その端末が、別のユーザーで登録済み
- `unauthenticated`: ログインしていない

## ping
動作確認用。`{ "ok": true }` を返す。
