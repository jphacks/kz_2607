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
