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
| 2026-10-24 | Core2向けの声(16kHz・IMA-ADPCM)を新規実装。`replyFormat: "ima_adpcm"`。テスト87件 |
| 2026-10-24 | ペット情報の取得 `getPet`(ホーム表示用)を新規実装。テスト92件 |
| 2026-10-24 | 会話でゲージが進む仕組み(会話3回で満タン)を新規実装。`getPet` にゲージを追加。交換でゲージを0に戻し、`config/game` で満タン条件を切り替え。テスト99件 |
| 2026-10-24 | 手紙の準備(1/3): 会話を代ごとに記録。交換で、ペットの持ち主と代の開始日時を記録。テスト104件 |
| 2026-10-24 | 手紙の準備(2/3): 交換のあと、裏で、終わった代の会話を OpenAI で要約して保存(`summarizeHandoff`)。テスト112件 |
| 2026-10-24 | 手紙の準備(3/3): 毎朝9時の手紙(`sendLettersDaily`)、`getLetters`、`registerPushToken`、通知(FCM)。テスト123件 |
| 2026-10-24 | ユーザーの記録 `syncUser`(`users/{uid}` にメールアドレスなどを保存)。`registerDevice` でも裏で記録。テスト127件 |
| 2026-10-24 | 思い出機能: 10往復ごとに裏で要約(`summarizeMemories`)、名前の伏せ字(nameMaps)、交換時の旅の記録(journeys)、会話でAIへ memories/nameMap/journeys/generation を送信。テスト144件 |
| 2026-10-24 | ゲージを「会話10回で満タン」に変更(`TALKS_TO_FULL`)。モデルを `gpt-6-luna` に変更 |
| 2026-10-25 | 性格の更新(6軸が飼い主に近づく)、`recordProgress`(歩数・すれ違い)を新規実装。交換で `axesBase` を記録。テスト158件 |
| 2026-10-25 | 姿の段階(赤ちゃん→子供→大人)を新規実装。会話の累計(`totalTalks`)で決め、`getPet` に `stage` などを追加、`talkToPet` に `evolved` を追加。テスト162件 |
| 2026-10-25 | 絵のキー(`appearance`)を新規実装。性格の強い2軸と段階で決め、`getPet` で返す(赤ちゃんの段階から性格を反映)。テスト167件 |
| 2026-10-25 | `getLetters` を、一番最初に作った1体の手紙だけ(新しい順・最大30通)に変更。戻り値に `firstPetId` を追加。テスト171件 |
| 2026-10-25 | `users/{uid}.firstPetId`(一番最初に作ったペット)を記録。`registerDevice` で書き、既存ユーザーは `getLetters` で自動補完。テスト176件 |
| 2026-10-25 | 性格の更新を見直し(更新間隔・好奇心の重みを `config/game` で変更可、質問の判定に文末を追加、材料をログに出力)。テスト180件 |
| 2026-10-25 | ペットの名前をつける `setPetName`(誕生のときに1回だけ・あとから変更不可・作った本人だけ)を新規実装。テスト185件 |
