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
| 返る | `deviceId`、`petId`、`name`(未設定は `null`)、`points`(会話の回数)、`gauge`(0〜1。会話10回で満タン)、`totalTalks`(会話の累計。交換しても引き継ぐ)、`stage`(`baby`/`child`/`adult`)、`stageIndex`(1〜3)、`nextStageAt`(次の段階になる累計回数。大人は `null`)、`talksToNextStage`(あと何回か。大人は `null`)、`generation`(世代)、`personalityAxes`(6軸・0〜1)、`learnedWords`(覚えた言葉)、`createdAt`(ISO形式の文字列)、`birthStatus`(誕生の進み具合。下の「誕生のながれ」)、`birthTrait`(誕生時にいちばん強い軸。AIの名前。未設定は `null`)、`firstPerson`(一人称。未設定は `null`)、`birthProfile`(誕生プロフィール。なければ `null`)、`baseType`(種族。あるときだけ) |

- 飼い主のUIDなどは返さない。交換で端末のペットが変わっても、いまのペットを返す
- ゲージは、会話するたびに進む(詳しくは下の「ゲージ」)

エラー:
- `invalid-argument`: `deviceId` の形が違う
- `not-found`: 端末が未登録(先に `registerDevice`)
- `permission-denied`: 自分の端末ではない
- `unauthenticated`: ログインしていない

## registerPushToken
通知トークンを登録する。ログイン後、アプリ起動時に1回、トークンが変わったときにも呼ぶ。何度呼んでも同じ。

| 項目 | 内容 |
| --- | --- |
| 送る | `token`: Firebase Messaging のトークン(20〜4096文字)、`platform`: `android` か `ios`(省略は `android`) |
| 返る | `{ "status": "ok" }` |

エラー: `invalid-argument`(token の形が違う)、`unauthenticated`。1人が複数の端末を使っていても、全部に届く。

## getLetters
**一番最初に作った1体**のペットから届いた、自分宛ての手紙を、新しい順に返す(最大30通)。ホーム画面や手紙の画面を開くときに呼ぶ。

| 項目 | 内容 |
|---|---|
| 送る | なし |
| 返る | `{ "firstPetId": "ペットID" または null, "letters": [ { letterId, petId, petName, title, body, generation, createdAt } ] }` |

- 「一番最初に作った1体」は、`users/{uid}/createdPets` の作成日時が最も古いペット。あとから作った2体目以降の手紙は、返さない
- まだペットを作っていない: `{ "firstPetId": null, "letters": [] }`
- ペットはいるが手紙がまだない: `{ "firstPetId": "ペットID", "letters": [] }`
- `createdAt` は、ISO形式の文字列。`petName` は未設定なら `null`
- 通知をタップしたとき: 通知の `data` に `type: "letter"`、`petId`、`letterId` が入っている。`getLetters` の結果から、その `letterId` を探して表示する

## 手紙のしくみ
- 毎朝9時(日本時間)に、サーバーが全ペットを調べる(`sendLettersDaily`)
- 手紙が出るのは、次の3つが全部そろったペット
  1. 1回以上手放されている(1代目ではない)
  2. いまの持ち主が、最初に作った人ではない
  3. 「前回の手紙」または「いまの代が始まった日」のうち新しいほうから、14日以上たっている
- 宛先は、最初に作った人だけ。同じ日に、二重には作らない
- 本文は、OpenAI が、手放されたあとの代の会話の要約をもとに書く。失敗したら、定型の文になる。いまの飼い主の名前などは入らない
- 手紙ができると、宛先のユーザーにプッシュ通知が届く
- 間隔は、Firestore の `config/game` の `letterIntervalDays` で変えられる(0にすると、すぐ出る。デモ用)。再デプロイは要らない
- 朝9時を待たずに動かすには、Google Cloud コンソールの Cloud Scheduler で `sendLettersDaily` を「強制実行」する

## syncUser
ログイン中のユーザーの情報(メールアドレスなど)を、Firestore の `users/{uid}` に記録する。**ログイン直後と、メールアドレスを登録(紐づけ)した直後**に呼ぶ。何度呼んでもよい。

| 項目 | 内容 |
| --- | --- |
| 送る | なし |
| 返る | `{ "status": "ok", "email": メールアドレス(匿名はnull), "isAnonymous": true/false }` |

- 記録する内容: `uid`、`email`、`signInProvider`(`anonymous` / `password` など)、`isAnonymous`、`emailVerified`、`createdAt`、`lastSeenAt`
- メールアドレスは、アプリが送った値ではなく、**ログインのトークン**から読む。匿名ユーザーにメールを紐づけた(`linkWithCredential`)あとは、`await user.getIdToken(true)` でトークンを更新してから呼ぶこと(更新しないと、メールが反映されない)
- `registerDevice` でも、裏で同じ記録をする(`syncUser` を忘れても、`users/{uid}` はできる)
- UID は、匿名からメールに紐づけても変わらない

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

## ゲージ
- ペットとの会話(`talkToPet` が成功したとき)が、1回ごとに、ゲージを進める。**10回で満タン(1.0)**(`config/game.talksToFull` で変える。本番は100)。アプリから何かを送る必要はない
- 声が聞き取れなかったとき(`no_speech`)は、数えない
- `talkToPet` の戻り値に `gauge` が入る。`getPet` でも読める
- 交換が確定すると、2匹のゲージは0に戻る(新しい飼い主のもとで、貯め直す)

## サーバーが記録するもの(手紙の準備)
- 会話(`talkToPet` が成功したとき)の文と返事を、代ごとに直近50件まで、ペットに記録する。手紙のための要約に使う。アプリからは読めない
- 交換が確定したとき、ペットに「いまの持ち主」と「この代が始まった日時」を記録する
- 交換が確定すると、サーバーが裏で、手放したペットの「終わった代」の会話を OpenAI で要約して取っておく(`summarizeHandoff`)。交換の返事は待たせない。要約に失敗しても、交換は取り消さない
- アプリが、何かを送る必要はない

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


## 思い出機能(AIサーバーへ渡すもの)

`talkToPet` は、AIサーバーへ次を追加で送る(空のものは送らない)。

| キー | 内容 |
|---|---|
| `generation` | ペットの今の代(数字) |
| `memories` | `[{id, text, generation, createdAt}]` 最新30件。今の飼い主が育てた代のもの(元の飼い主に戻ってきたら、昔の分も入る)。名前は `{shop_1}` のような伏せ字で、`nameMap` で本当の名前に戻せる。`createdAt` はISO文字列 |
| `pastMemories` | `[{id, text, generation, createdAt}]` 前の飼い主たちの思い出(最大10件)。直前の代から最大7件+1代目から最大3件(直前が1代目なら1代目から10件)、新しい順。**伏せ字は「あの人」「あのお店」などにぼかし済み**。今の飼い主が育てた代の分は入らない |
| `nameMap` | `{"{shop_1}": "ミスド"}` 伏せ字と本当の名前の対応(この飼い主のもの) |
| `journeys` | `[{generation, learnedWords, talkCount, timeOfDay?, summary?}]` 前の持ち主たちの旅の記録 |

- 前の持ち主の nameMap は、次の飼い主には渡さない。前の持ち主の思い出は、`pastMemories`(ぼかし済み)と journeys だけが引き継がれる。
- 交換が確定した少しあと(裏の処理が終わったあと)に、`memoryCache/current` を新しい飼い主用に作り直す。それまでの間も、会話のときに、保存済みの思い出から、その場で選んで渡す(`memories`・`pastMemories` が空になる時間はない。ただし、交換前の最後の会話の要約は、裏の処理が終わるまで間に合わない)。
- 要約(`summarizeMemories`)は Firestore トリガーで、会話が5往復(既定。`config/game.summarizeEveryTurns`、本番は10など)たまるたびに裏で動く。`/talk` の返事は待たせない。
- 交換時(`summarizeHandoff`)に、終わった代の、要約していない会話が1往復でも残っていれば、それも要約し、journeys に値(言葉・会話数・時間帯)と summary を書く。
- 思い出の日付(`createdAt`)は、出来事のあった日の12:00(JST)。
- モデル名は `functions/.env` の `OPENAI_MODEL`(仕様書の `gpt-6-luna` ではなく、実際の `gpt-5.6-luna`)。

## recordProgress(歩数とすれ違いを送る)

アプリが、Core2 から受け取った1日分の歩数・すれ違い数を送る。性格の「活発さ」「人懐っこさ」の計算に使う(ゲージには入れない)。

| 入力 | 内容 |
|---|---|
| `deviceId` | 端末ID(自分の端末) |
| `steps` | その日の歩数(0〜200000の整数) |
| `meetCount` | その日のすれ違い数(0〜1000の整数) |
| `date` | `YYYY-MM-DD`(省略すると今日。今日から7日前まで) |

返る: `{status: "ok", date, personalityUpdated}`。同じ日に送り直すと、上書きする(その日の累計を送ればよい)。同期のたびに、今日の累計を送る形がよい。

## 性格のしくみ

- 6軸(`activity` `friendly` `talkative` `logical` `curious` `nightowl`)が、飼い主の話し方・関わり方に、少しずつ近づく。`getPet` の `personalityAxes` で見られる。
- 更新のタイミング: 会話が2回ふえたとき。または、前回の更新から24時間たって、何か材料(会話1回以上、または `recordProgress`)があるとき。
- 水準の計算
  - `activity`: 1日の平均歩数 ÷ 12000
  - `friendly`: 1日の平均すれ違い数 ÷ 5
  - `talkative`: 1日の平均会話回数 ÷ 20
  - `nightowl`: 22時〜4時の会話の割合
  - `logical`: 理由・順序を表す言葉と、感覚の言葉の比
  - `curious`: 新しい話題の割合と、質問の割合
- 更新式: `v ← v + η·c·(L − v)`(`c` は材料の多さ。会話10件、歩数3日分で1.0)。1人の飼い主で動ける幅は、受け取った時点から ±0.2。
- 調整: Firestore の `config/game` で変えられる(再デプロイは要らない)。

| キー | 既定 | 意味 |
|---|---|---|
| `personalityUpdateEvery` | 2 | 会話がこの回数ふえるごとに更新する。資料の式②(ΔP ≥ P_full÷6)で、P_full が満タンの10回(デモ)なら約2。本番(100回)なら約17。**1人の飼い主のもとで長く話す(満タン後も交換しない)なら、17など大きくする** |
| `talksToFull` | 10 | ゲージが満タンになる会話の回数。デモは10、本番は100 |
| `summarizeEveryTurns` | 5 | 何往復ごとに思い出を要約するか(2以上)。デモは5、本番は10など |
| `personalityEta` | 0.12 | 近づく速さ。デモでは 0.5 などにすると、変化が見えやすい |
| `personalityMaxShift` | 0.2 | 1人の飼い主で動ける幅 |
| `curiousNewTopicWeight` | 0.5 | 好奇心のうち「新しい話題」の割合(0〜1)。実際の会話で「新しい話題」が8割を超えて差がつかないときは、0 にすると、質問の割合だけで決まる |

- 時刻(夜ふかし・1日あたりの回数)は、日本時間(UTC+9)に直して数える。
- 質問は、「？」「なんで」「教えて」「ですか」などのほか、文の終わりが「か」「の」のものも数える(音声から変換した文字には「？」が付かないことがあるため)。
- 更新のたびに、材料(会話の件数・新しい話題の割合・質問の割合・論理と感覚の言葉の数)を、Cloud Functions のログ(`性格の材料: ...`)に出す。実際の値を見て、設定を調整できる。
- 会話の材料は、直近50件のみ。

## 姿の段階(赤ちゃん → 子供 → 大人)

- 段階は、**会話の累計回数**で決まる。既定は、30回で子供、100回で大人。交換してもゲージ(10回で満タン)は戻るが、累計は引き継ぐ。
- 絵は、アプリ・Core2 が持つ。バックエンドは、どの絵かを示す**キー**だけ返す(`getPet` の `appearance`)。下の「絵のキー」を見る。
- `talkToPet` の結果に、`stage` と `evolved`(この会話で進化したとき true)が付く。進化の演出に使える。
- AIサーバーへの送信にも、`stage` が付く(口調を変えたいときに使う)。
- 回数は、Firestore の `config/game` の `stageChildAt`・`stageAdultAt` で変えられる。デモでは、3 と 6 などにすると、すぐ進化する。

## 絵のキー(`getPet` の `appearance`)

性格の**いちばん強い軸**と**2番目に強い軸**、そして**成長の段階**で、絵が決まる。生まれたての赤ちゃんの段階から、性格に合った絵が出る。

```
appearance: {
  stage: "baby",                  // baby / child / adult
  primary: "nightowl",            // いちばん強い軸
  secondary: "curious",           // 2番目に強い軸
  tertiary: "talkative",          // 3番目に強い軸(パーツ方式の口などに)
  key: "nightowl_curious_baby",   // 出す絵のキー
  fallbackKey: "nightowl_baby"    // key の絵がないときの代わり
}
```

- `primary` `secondary` `tertiary` は、いつも別の軸。パーツ方式では、動物 = `primary` と `stage`、目 = `secondary`、口 = `tertiary` のように使える(組み合わせは、アプリで決める)。
- 軸の名前: `activity`(活発さ)、`nightowl`(夜ふかし)、`logical`(理屈っぽさ)、`talkative`(おしゃべり)、`friendly`(人懐っこさ)、`curious`(好奇心)
- 絵は、`{primary}_{secondary}_{stage}`(6×5×3 = 90枚)と、`{primary}_{stage}`(6×3 = 18枚)の、合計108枚。全部そろわなくても、`fallbackKey` の18枚があれば動く。
- 性格が変わると、キーも変わる(交換のあとなど)。表示のたびに、`getPet` の `appearance.key` を見る。
- 軸の値が同じときの順番(`primary` も `secondary` も同じ規則):
  - **誕生のながれ(`setInitialPersonality`)で性格を決めたペット**: 決まった順 `activity → friendly → talkative → logical → curious → nightowl`。`birthTrait`(`active → affection → talkative → logic → curious → night`)と同じ順なので、**誕生のときは `birthTrait` と `primary` が必ず同じ軸**(`active` = `activity`、`affection` = `friendly`、`logic` = `logical`、`night` = `nightowl`)になる。
  - 昔のペット(誕生のながれを通っていない): ペットごとに決まった順。同じペットなら、いつも同じ結果になる。
  - 性格が育つと、値が少しずつ変わって同じ値でなくなるので、`primary` は `birthTrait` と違う軸になることがある。
- 進化(`talkToPet` の `evolved: true`)のあとは、`getPet` を呼び直すと、新しいキーが取れる。
- 絵のデザインは、人型ではない生き物にする(段階が進んでも、人型にはしない)。

## 最初のペットの記録(`users/{uid}.firstPetId`)

- ユーザーが**一番最初に作ったペット**のIDを、`users/{uid}` の `firstPetId` に記録する。`registerDevice` で、初めてペットが作られたときに書かれる。
- 一度決まったら、変わらない(あとから2体目、3体目を作っても同じ)。
- 以前から使っているユーザーは、`getLetters` を呼んだときに、自動で記録される(作成日時が最古のペット)。
- 「一番最初」は、`users/{uid}/createdPets` の作成日時が最も古いもの。同じなら、IDの小さいほう。
- 手紙(`getLetters`・毎朝9時の配信)は、このペットだけが対象。

## 誕生のながれ(birthStatus)

誕生の画面は、①→②→③の順に呼ぶ。進み具合は `pets/{petId}.birthStatus` が唯一の状態で、**`getPet` の `birthStatus` で読める**(アプリの開始・再開のたびに、これを見る)。

| `birthStatus` | 意味 | 次にやること |
|---|---|---|
| `egg` | まだ性格を決めていない | ① `setInitialPersonality` |
| `personality_set` | 性格を決めた | ② `generateBirthProfile` |
| `profile_ready` | 誕生プロフィールができた | 名前を選んで ③ `setPetName` |
| `born` | 生まれた | ホームへ |

- 新しいペットは `egg` で始まる。
- **交換で受け取ったペット(2代目以降、または作った本人ではないペット)は、保存されている値にかかわらず、いつも `born`** として返す。誕生のながれは、作った本人が1代目のときだけ進められる。
- 状態の値がない昔のペットは、中身から決めて返す(勝手に `egg` とはしない): 名前がある・会話した・2代目以降・他人が作った → `born`。誕生プロフィールがある → `profile_ready`。回答がある → `personality_set`。どれもなければ `egg`。
- 種族(`baseType`)は、誕生のながれでは決めない。あるときは、そのまま残して返す。

`getPet`(引数: `deviceId` だけ)の返却例(誕生プロフィールができたあと):
```json
{"deviceId":"dev1","petId":"abc","name":null,"generation":1,"points":0,"gauge":0,"totalTalks":0,
 "stage":"baby","stageIndex":1,"nextStageAt":30,"talksToNextStage":30,
 "appearance":{"stage":"baby","primary":"logical","secondary":"curious","key":"logical_curious_baby","fallbackKey":"logical_baby"},
 "personalityAxes":{"activity":0.2,"friendly":0.4,"talkative":0.6,"logical":0.8,"curious":0.8,"nightowl":0.2},
 "learnedWords":[],"createdAt":"2026-10-25T05:00:00+00:00",
 "birthStatus":"profile_ready","birthTrait":"logic","firstPerson":null,
 "birthProfile":{"nameCandidates":["モチ","ポポ","ルル"],"description":"元気いっぱいで人なつっこい子。","firstPerson":"ぼく","speechNote":"元気な話し方。","firstWords":"はじめまして！あえて、うれしいよっ！","source":"ai"}}
```

## setInitialPersonality(① 誕生のときに性格の初期値を決める)

6問4択の回答から、6軸の初期値を決める。**1体につき1回だけ**。決める値は、アプリの計算ではなく、回答からサーバーで計算する(アプリの値は使わない)。

| 入力 | 内容 |
|---|---|
| `deviceId` | 端末ID |
| `answers` | 0〜3の整数が6個(選択肢の番号)。**この順**: `activity`, `friendly`, `talkative`, `logical`, `curious`, `nightowl`。軸の名前をキーにした辞書でもよい(このサーバーの名前でも、AIの名前 `active` / `affection` / `talkative` / `logic` / `curious` / `night` でも可) |
| `questionnaireVersion` | 質問のバージョン。`"birth_v1_6q4"` のような文字列、または1以上の整数 |
| `requestId` | (任意)アプリの依頼ID(UUIDなど。英数字と `-` `_` `.` `:`、64文字まで)。保存だけする |

- 回答と値: 0 → 0.2、1 → 0.4、2 → 0.6、3 → 0.8
- 返却例:
```json
{"status":"ok","petId":"abc","alreadySet":false,"birthStatus":"personality_set","birthTrait":"logic",
 "personalityAxes":{"activity":0.2,"friendly":0.4,"talkative":0.6,"logical":0.8,"curious":0.8,"nightowl":0.2},
 "appearance":{"stage":"baby","primary":"logical","secondary":"curious","key":"logical_curious_baby","fallbackKey":"logical_baby"}}
```
  - `birthTrait`: いちばん強い軸(AIの名前)。同じ値なら、`active → affection → talkative → logic → curious → night` の順
  - `personalityAxes` のキーは、このサーバーの名前(`activity` `friendly` `talkative` `logical` `curious` `nightowl`)
- 保存先(`pets/{petId}`): `personalityAxes`、`axesBase`(性格が動ける幅の基準。同じ値)、`birthAnswers`、`questionnaireVersion`、`birthRequestId`、`birthTrait`、`birthStatus`
- 送り直し: 同じ回答・同じバージョンなら、成功(`alreadySet: true`)。違うなら、エラー(`failed-precondition`、`reason: "personality_already_set"`)
- できる人: そのペットを作った本人が、いまも持っていて、**交換前の1代目で、まだ話していない**ときだけ。それ以外は `personality_not_allowed`(作った人でないと `not_creator`)
- 入力の誤りは `invalid-argument`(`invalid_answers` / `invalid_version` / `invalid_request_id`)
- 性格の更新の基準は `axesBase` に統一(別の保存先は作らない)。種族(`baseType`)は触らない

## generateBirthProfile(② 誕生プロフィールをAIで作る)

性格を決めたあと、名前の候補・紹介・一人称・最初のひとことを、AIで作って保存する。性格は、サーバーが保存済みの値を読む(アプリからは送らない)。AIは最大12秒で打ち切り、失敗したら固定の文(`source: "template"`)で返す(誕生は止まらない)。

| 入力 | 内容 |
|---|---|
| `petId` | ペットのID(`getPet` の `petId`) |
| `regenerate` | (任意・既定 `false`)`true` なら作り直す。`profile_ready` のときだけ。初期性格は変わらない |

返却例:
```json
{"status":"ok","petId":"abc","birthStatus":"profile_ready","regenerated":false,"source":"ai",
 "nameCandidates":["モチ","ポポ","ルル"],"description":"元気いっぱいで人なつっこい子。",
 "firstPerson":"ぼく","speechNote":"元気な話し方。","firstWords":"はじめまして！あえて、うれしいよっ！"}
```
- `firstPerson` は「ぼく」「わたし」「おれ」「うち」のどれか。
- 保存先: `pets/{petId}.birthProfile`(`source` を含む)、`birthStatus` は `profile_ready` になる。
- 保存済みで `regenerate: false` なら、AIを呼ばず、保存済みを返す(`regenerated: false`)。
- エラー(`failed-precondition`): `personality_not_set`(先に①)、`already_born`(もう生まれている)、`birth_not_allowed`(1代目ではない)。`permission-denied`(`not_creator`): 作った本人ではない。`not-found`: ペットがない。

## setPetName(③ 名前と一人称をつけて、生まれたことにする)

誕生の画面で、名前を決めたあとに、**1回だけ**呼ぶ。つけた名前は、ずっと変わらない(交換しても、次の飼い主になっても同じ)。名前は、`getPet` の `name`、手紙、AIへの送信(`petName`)に使われる。成功すると `birthStatus` は `born` になる。

| 入力 | 内容 |
|---|---|
| `deviceId` | 端末ID(自分の端末) |
| `name` | 名前(前後の空白は取る。1〜12文字)。候補以外の自由入力でもよい |
| `firstPerson` | (任意)「ぼく」「わたし」「おれ」「うち」。省略すると、誕生プロフィールの下書きの値を使う(なければ、つけない) |

返却例:
```json
{"status":"ok","petId":"abc","name":"モチ","firstPerson":"ぼく","firstWords":"はじめまして！あえて、うれしいよっ！",
 "birthStatus":"born","alreadySet":false,"alreadyBorn":false}
```
- `firstWords`: 誕生プロフィールの「最初のひとこと」(なければ `null`)。誕生の演出に使う。
- 送り直し: 同じ名前なら成功(`alreadySet: true`、`alreadyBorn: true`)。応答が届かなかったときや、アプリの再起動後も、もう一度呼べばよい。
- 一人称は、AIへの送信(`firstPerson`)にも使われる。

エラー:
- `invalid-argument`(`reason: "invalid_name"`): 空、13文字以上、改行などの制御文字、URL・連絡先・指示のような文字、数字4桁以上
- `invalid-argument`(`reason: "invalid_first_person"`): 一人称が決まりの外
- `failed-precondition`(`reason: "name_already_set"`): すでに違う名前がついている(`details.name` に、今の名前)
- `failed-precondition`(`reason: "first_person_already_set"`): すでに違う一人称がついている
- `permission-denied`(`reason: "not_creator"`): そのペットを作った人ではない(交換で受け取ったペットには、つけられない)
- `permission-denied`: 自分の端末ではない / `not-found`: 端末が未登録

名前をつける前は、`getPet` の `name` は `null`。誕生の画面は、`registerDevice` → ① → ② → ③ の順に呼ぶ。
