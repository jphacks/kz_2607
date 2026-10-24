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

## まだ対応していないこと
- ゲージが満タンでないと交換できない、という条件
- 両端末の報告がそろってから確定する、というモード

