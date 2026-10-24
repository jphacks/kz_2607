# バックエンド(Firebase Cloud Functions / Python)

**このディレクトリは、開発期間中(2026-10-24〜25)に、空の状態から新規に作成した。**
開発期間前に作ったコードは、含まれていない。

## 作業ログ
| 日付 | 内容 |
| --- | --- |
| 2026-10-24 | 土台を作成(Firebase設定、Firestoreルール、動作確認用の関数 `ping`) |
| 2026-10-24 | 新しいFirebaseプロジェクト `pet-handoff-hack` を作成(Blaze、Firestore 東京、匿名ログイン) |
| 2026-10-24 | `registerDevice` を新規実装(端末登録とペット作成)。テスト10件。API仕様を `docs/api.md` に記載 |
| 2026-10-24 | 本物のFirebaseで動作確認するスクリプト `scripts/smoke.mjs` を追加 |
| 2026-10-24 | すれ違い交換(`reportExchange`、`getExchangeResult`、`cancelExchange`)を新規実装。テスト27件 |
| 2026-10-24 | 音声会話 `talkToPet`(文字起こし、AI連携、声、回数制限)を新規実装。テスト54件。`scripts/talk.mjs` を追加 |
| 2026-10-24 | テスト用の声を作る `scripts/make-test-voice.ps1` を追加 |
| 2026-10-24 | 言葉を覚える処理(AIが選んだ言葉の安全確認と保存)を新規実装。テスト78件 |
