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

## getPet
自分の端末にいるペットの、表示用の情報を返す(読むだけ)。ホーム画面を開くたびに呼んでよい。

| 項目 | 内容 |
| --- | --- |
| 送る | `deviceId` |
| 返る | `deviceId`、`petId`、`name`(未設定は `null`)、`points`、`gauge`、`generation`(世代)、`personalityAxes`(6軸・0〜1)、`learnedWords`(覚えた言葉)、`createdAt`(ISO形式の文字列) |

- 飼い主のUIDなどは返さない。交換で端末のペットが変わっても、いまのペットを返す
- `points`(貯めたポイント)と `gauge`(0〜1)も返す。ポイントは `recordProgress` で貯まる

エラー:
- `invalid-argument`: `deviceId` の形が違う
- `not-found`: 端末が未登録(先に `registerDevice`)
- `permission-denied`: 自分の端末ではない
- `unauthenticated`: ログインしていない

## recordProgress
会話・歩数・すれ違いを記録して、ペットのゲージを進める。呼べるのは、その端末の持ち主だけ。

| 項目 | 内容 |
| --- | --- |
| 送る | `deviceId`、`nTalk`(会話の回数)、`steps`(歩数)、`nMeet`(すれ違いの回数)、`eventKey`(任意) |
| 返る | `status`(`recorded` / `already_recorded`)、`petId`、`points`、`gauge` |

- `nTalk`・`steps`・`nMeet` は、どれか1つ以上が必要(0以上の数)。1回の上限は 100回・10万歩・50回
- ポイント: 会話1回=1、1000歩=1、すれ違い1回=3。**120ポイントでゲージが満タン(1.0)**
- `eventKey` を付けると、同じ値の再送は足さない(`already_recorded`)。通信が切れて再送するときは、同じ値を使う
- 交換が確定すると、2匹のポイントとゲージは0に戻る(新しい飼い主のもとで、貯め直す)

エラー: `invalid-argument`(数の形が違う、全部0)、`not-found`(端末が未登録)、`permission-denied`(自分の端末ではない)、`unauthenticated`

## ping
動作確認用。`{ "ok": true }` を返す。

# すれ違い交換
2台の端末が、持っているペットを入れ替える。呼べるのは、ログイン済みのアプリだけ。
`myDeviceId` は、呼んだユーザーが `registerDevice` で登録した端末であること(他人の端末は `permission-denied`)。

共通の決まり
- `transactionId`: 英数字と `_ -` の1〜64文字。**交換1回につき1つ。両端末が同じ値を使う**(Core2同士の仮交換のときに共有する)
- エラーを返したときは、何も書き込んでいない

## reportExchange
交換の確定を報告する。1台が報告すると、その時点で確定する。

| 送る | 内容 |
| --- | --- |
| `myDeviceId` | 自分の端末 |
| `peerDeviceId` | 相手の端末 |
| `givenPetId` | 手放したペット |
| `gotPetId` | 受け取ったペット |
| `transactionId` | 交換のID(必須) |
| `location`、`rssi` | 任意(記録用) |

返る: `status`、`handoffId`、`receivedPetId`(**呼んだ端末が受け取るペット**)、`receivedPetGeneration`、`transactionId`、`givenPetId`、`replayed`
- `done`: 確定した。同じ端末からの再送も `done`(`replayed: true`)
- `already_done`: もう一方の端末の報告(手放すと受け取るが逆)。同じ交換とみなす

## getExchangeResult(読むだけ)
送る: `transactionId`、`myDeviceId`

| status | 意味 |
| --- | --- |
| `confirmed` | 確定済み。`handoffId`、`givenPetId`、`receivedPetId`、`receivedPetGeneration`、`currentPetId` も返る(`myDeviceId` の端末から見た内容) |
| `cancelled` | 取り消し済み。この交換が確定することは、もうない |
| `unknown` | サーバーはまだ何も受け取っていない |

## cancelExchange
送る: `transactionId`、`myDeviceId`、`peerDeviceId`

| status | 意味 |
| --- | --- |
| `cancelled` | 取り消した。以後、この `transactionId` の報告は `exchange_cancelled` で拒否される |
| `confirmed` | 取り消す前に、確定していた。取り消されていない。Core2には、取り消しを指示しない |

## 交換のエラー
| code | reason | 意味 |
| --- | --- | --- |
| `invalid-argument` | | 引数の不備、自分自身や同じペットとの交換 |
| `permission-denied` | | 自分の端末ではない |
| `not-found` | | 端末やペットが未登録 |
| `failed-precondition` | `exchange_cancelled` | 取り消し済み |
| `failed-precondition` | `transaction_mismatch` | 同じ `transactionId` が、別の内容の交換に使われている |
| `failed-precondition` | (なし) | 報告が、サーバーの状態と合わない |

## 推奨の流れ
1. Core2同士が仮交換する(`transactionId` を共有)
2. `reportExchange` を呼ぶ
3. `done` か `already_done` なら、Core2を確定する
4. 交換が成立しないエラーなら、Core2を元に戻す。あわせて `cancelExchange` を呼ぶと、以後その `transactionId` では確定しなくなる
5. 結果が分からないとき(通信切れなど)は、同じ内容で再送する。それでも分からなければ `getExchangeResult` で確認する。`unknown` なら `cancelExchange` を呼び、`cancelled` を確認してから戻す

## ゲージの条件(サーバーの設定)
Firestore の `config/game` の `requireFullGauge` を `true` にすると、ゲージが満タン(1.0)でない2匹の交換を、`failed-precondition`(`reason: "pet_not_ready"`、`details.petIds` に満タンでないペット)で断る。**既定はオフ**(設定がなければ、ゲージに関係なく交換できる)。切り替えに再デプロイは要らない。

## まだ対応していないこと
- 両端末の報告がそろってから確定する、というモード

# 音声会話(talkToPet)
録音 → 文字 → AIの返答 → 声、を1回で行う。待ち時間は最大120秒。

| 送る | 内容 |
| --- | --- |
| `deviceId` | 録音した端末(自分の端末) |
| `audioBase64` | WAVをBase64にしたもの。**16bit・モノラル・8000〜48000Hz**(16000Hz推奨)、**30秒まで** |
| `languageCode` | `ja-JP`(既定)か `en-US` |
| `petId` | 任意。渡すと、いまその端末のペットか確かめる(交換直後に古いペットへ話しかけるのを防ぐ) |
| `wantAudio` | 既定 `true`。`false` なら、返事の声を作らない(文章だけ返す) |
| `replyFormat` | 既定 `"wav"`。`"ima_adpcm"` にすると、Core2向けの形で返る(下の「Core2向けの声」) |

返る
```
{ status: "ok" | "no_speech", transcript, replyText,
  audioStatus: "ok" | "failed" | "skipped",
  replyAudioBase64, replyAudio: { format: "wav", sampleRate, channels },   // audioStatus が ok のときだけ
  learnedWords,   // この会話で、新しく覚えた言葉(なければ空の配列)
  petId, durationSec }
```
- `no_speech`: 声が聞き取れなかった。AIは呼ばない。再録音を促す
- `audioStatus: "failed"`: 声が作れなかった。**文章(`replyText`)は返る**ので、画面には出せる
- 返事の文章は200文字まで。声は、24kHz・モノラル・16bitのWAV
- `learnedWords`: AIが選んだ言葉のうち、ペットが覚えたもの。アプリは「〇〇を覚えたよ」の表示に使える
- 音声は保存しない

エラー
| code | reason | 意味・対処 |
| --- | --- | --- |
| `invalid-argument` | `bad_wav` / `bad_format` / `audio_empty` | WAVとして読めない、ステレオなど、空 |
| `invalid-argument` | `audio_too_long` / `audio_too_large` | 30秒を超えた、またはデータが大きすぎる |
| `permission-denied` | | 自分の端末ではない |
| `not-found` | | 端末が未登録 |
| `failed-precondition` | `pet_changed`(`currentPetId` つき) | 端末のペットが変わっていた。**その会話は捨てる** |
| `resource-exhausted` | `rate_limited`(`retryAfterSec` つき) | 1分間に6回まで |
| `unavailable` | `stt_failed` | 文字起こしに失敗。少し待って再送してよい |
| `unavailable` | `ai_failed` | AIの返答を作れなかった。少し待って再送してよい |
| `unavailable` | `ai_not_configured` | AIがまだつながっていない |

## AIサーバーに送る内容
`POST <config/ai の url>` に、JSONを送る。ヘッダー `X-Api-Key` に、Secret Managerの `TALK_API_KEY` を入れる。

| 項目 | 内容 |
| --- | --- |
| `text` | 聞き取った文字 |
| `petId` | ペットID |
| `petName` | ペットの名前(あれば) |
| `personalityAxes` | 性格6軸(0〜1)。`active`、`affection`、`talkative`、`logic`、`curious`、`night` |
| `hour` | 日本時間の「いまの時」(0〜23) |

返事は `reply_text`(`replyText` や `reply` でもよい)に、文章を入れる。覚えさせたい言葉があれば、`learn_words`(文字列の配列。`learnWords` や `learned_words` でもよい)に入れる。

AIサーバーのURLは、Firestoreの `config/ai`(ドキュメントID `ai`)の `url` から読む(`https://` で始まるもの)。変えるのに、再デプロイは要らない。
`mode` を `"echo"` にすると、AIを呼ばず、聞いた言葉をそのまま返す(AIが用意できるまでの、動作確認用)。

## まだ対応していないこと
- 会話の履歴(AIに渡す、直前の会話)

## 言葉を覚える決まり
- 1回の会話で、覚えるのは最大3語。1語は20文字まで。ペットは50語まで覚える
- すでに覚えた言葉は、増えない
- 次の言葉は、覚えない: URL、メールアドレス、4桁以上の数字、AIへの指示のように見えるもの、改行などの制御文字
- いまの持ち主の、いまのペットだけが覚える。覚える処理に失敗しても、会話の返事は返す(`learnedWords` は空)
- 覚えた言葉は、ペットの `learnedWords` と、履歴(`pets/{petId}/history`)に記録される

## Core2向けの声(replyFormat: "ima_adpcm")
- 返事の声が、**16kHz・モノラル・IMA-ADPCM**で返る。アプリは、`replyAudioBase64` をBase64から戻したバイト列を、そのまま、BLEでCore2に送ればよい
- 形式は、Core2の録音と同じ。1サンプル4ビットで、**偶数番目のサンプルが下位4ビット**、奇数番目が上位4ビット。初期状態は、予測値0・ステップ番号0。WAVのヘッダーは付かない
- `replyAudio` は `{ format: "ima_adpcm", sampleRate: 16000, channels: 1, sampleCount, durationSec }`
- 24kHzから16kHzへの変換は、簡単な方法のため、声は聞き取れるが、WAVより音質が少し落ちる
- 未確認: Core2側が、この形をそのまま再生できるか。最大の長さ(返事は200文字までで、十数秒になりうる)。組み込みに確認すること

