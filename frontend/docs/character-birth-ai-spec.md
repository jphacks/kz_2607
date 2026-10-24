# キャラクター生成仕様書（AI担当用）

更新日：2026-10-25
対象：初めて作るペットの誕生プロフィール生成。会話・交換・手紙生成は対象外。

## 1. 目的と役割分担

飼い主が6問・各4択に答え、その回答から決まった性格をもとに、AIがキャラクターの紹介と名前候補などを作成します。

- Flutter：M5の接続・登録、質問への回答、生成中表示、紹介表示、名前選択・自由入力、誕生演出。
- Cloud Functions：認証・所有権確認、回答から6軸を計算、AI呼び出し、応答検証、Firestore保存、再送・再開管理、失敗時の予備文。
- AI：確定済みの6軸と代表特徴をもとに、名前候補・紹介・一人称・話し方の説明・最初のひとことを生成。
- Core2：登録されたペットの識別と表示・育成。AI生成を直接呼び出さない。

**AIは6軸を計算・変更しません。AIからFirestoreへの直接書き込みも行いません。**
キャラクター生成は今回、画像生成ではなく「設定文章の生成」を意味します。種族・画像キーの決定は別の仕様です。

## 2. ユーザーの操作順と状態

1. アカウント作成・ログイン。
2. M5Stackを接続・登録。registerDeviceでpetIdを取得し、卵の状態にする。
3. 6問・各4択に回答。setInitialPersonalityで回答・初期性格を保存。
4. generateBirthProfileでAI生成を依頼し、下書きを保存。
5. 名前候補3つから選ぶ、または名前を自由入力。
6. setPetNameで名前・一人称を確定して誕生。最初のひとことを表示。

| birthStatus | 意味 | 再開位置 |
|---|---|---|
| egg | 登録済み、初期性格は未確定 | 質問画面 |
| personality_set | 初期性格を保存済み | 設定生成 |
| profile_ready | 誕生プロフィールを保存済み | 名前選択 |
| born | 誕生完了 | ホーム |

状態はCloud Functionsが管理します。保存済みプロフィールがあれば、再開のたびにAIを呼び直しません。
既存・交換済みペットを勝手に卵へ戻しません。

## 3. 6問4択と値の決定

各質問の選択肢は、対応する軸の低い順から高い順です。選択番号は0始まりです。

| 選択番号 | 表示上の選択肢 | 初期値 |
|---|---|---|
| 0 | 1番目 | 0.2 |
| 1 | 2番目 | 0.4 |
| 2 | 3番目 | 0.6 |
| 3 | 4番目 | 0.8 |

式：`v0 = 0.5 + 0.6 × (選択番号 / 3 - 0.5)`。
サーバーが回答から計算し直します。Flutterでの計算値を正として保存しません。

| 画面順 | 質問 | 選択肢（低→高） | DBの軸 | AIの軸 |
|---|---|---|---|---|
| 1 | 休みの日は、どう過ごしたい？ | 家でのんびり／近所で少し気分転換／外でいろいろ活動／朝から外でたっぷり遊ぶ | activity | active |
| 2 | 自分の時間を楽しむなら、いつが好き？ | 朝早く／どちらかというと朝／どちらかというと夜／夜遅く | nightowl | night |
| 3 | 何かを選ぶとき、どうやって決める？ | 直感／気持ちを大切に少し考える／理由を比べ最後は気持ち／理由や根拠をじっくり比較 | logical | logic |
| 4 | 初めて会う人とは、どう接したい？ | 離れて様子を見る／話しかけられたら少し話す／慣れたら自分から話す／自分からどんどん話す | friendly | affection |
| 5 | 初めてのことに出会ったら、どうしたい？ | 慣れたことを楽しむ／評判を聞いて考える／少し調べて試す／まず自分で試す | curious | curious |
| 6 | 会話では、どんな役になることが多い？ | じっくり聞く／聞くことが多い／話すことが多い／自分からたくさん話す | talkative | talkative |

APIのanswers配列の順は画面順と異なり、`activity, friendly, talkative, logical, curious, nightowl`です。
questionnaireVersionは`birth_v1_6q4`です。
今回、性格決定用の自由記入はありません。名前の自由入力はあります。

### birthTrait（代表特徴）

最も値が大きいAI軸のキーを1つ保存します。同率なら次の優先順で選びます。

`active → affection → talkative → logic → curious → night`

すべて同じ値ならbirthTraitはactiveです。ただし、6軸自体は同値のままです。
AIは代表特徴だけでなく6軸全体を参照し、同率の場合に「活発さだけが突出している」紹介にしないでください。
birthTraitは誕生後に変更しません。育成で変化する6軸とは別の項目です。

## 4. FlutterとCloud Functionsの契約（実装済み）

Callableのリージョン：`asia-northeast1`。ログイン中のFirebase認証を利用します。

### ① setInitialPersonality

```json
{
  "deviceId": "AABBCCDDEEFF",
  "answers": [0, 2, 1, 3, 0, 1],
  "questionnaireVersion": "birth_v1_6q4",
  "requestId": "550e8400-e29b-41d4-a716-446655440000"
}
```

作った本人かつ現在所有者、第1世代、会話前が条件です。同じ回答の再送は成功、異なる回答への変更は拒否します。
初期6軸はpersonalityAxesとaxesBaseへ、回答はbirthAnswersへ保存します。v0の別保存先をAI側で作る必要はありません。

### ② generateBirthProfile

```json
{"petId":"pet_example","regenerate":false}
```

6軸・birthTraitは保存済みデータをCloud Functionsが読み出します。Flutterからの再送は不要です。
保存済み下書きがあればそれを返します。regenerate:trueはprofile_readyでのみ可能です。現在のFlutter画面には再生成ボタンを設けていません。

### ③ setPetName

```json
{"deviceId":"AABBCCDDEEFF","name":"モチ","firstPerson":"ぼく"}
```

名前は前後空白除去後1〜12文字。禁止語等はバックエンドが検証します。
同じ名前での再送は成功として扱います。自由入力した名前を確認するために、FlutterからAIサーバーを直接呼びません。

## 5. AIへの入力

### 現在のリポジトリの実装

Cloud FunctionsがOpenAIを直接呼び、次の形式で渡します。Macの/birthは現在の生成経路ではありません。

```json
{
  "personalityAxes": {
    "active": 0.2,
    "affection": 0.6,
    "talkative": 0.4,
    "logic": 0.8,
    "curious": 0.2,
    "night": 0.4
  },
  "strongestAxis": "logic"
}
```

strongestAxisはDBのbirthTraitと同じ値です。現在の直接呼び出しでは、質問・回答の文章やbaseTypeはAIへ渡していません。

### Mac /birthへ切り替える場合の接続案（未確定）

```json
{
  "personalityAxes": {
    "active": 0.2,
    "affection": 0.6,
    "talkative": 0.4,
    "logic": 0.8,
    "curious": 0.2,
    "night": 0.4
  },
  "birthTrait": "logic"
}
```

- Cloud Functions → Macの/birthという経路にする。FlutterのCallable仕様は変更しない。
- AI側はAI名・DB名の両方の軸キーを受け付ける予定。送信時はAI名に統一する案。
- baseTypeは任意。ない場合でも生成できること。6問から種族を断定しない。
- 質問と回答の文章を渡す場合は、配列形式・項目名を別途合意する。現在の実装では未送信。
- URL、認証方法、実際のリクエスト形式、利用モデルはAI・バックエンド担当で確定する。
- モデルの種類（Haiku等）はAI内部の実装選択で、Flutterの依存条件にしない。

## 6. AIの出力

Markdownや説明を付けず、次の5項目を持つJSONを返します。

```json
{
  "nameCandidates": ["モチ", "ポポ", "ルル"],
  "description": "ものごとをじっくり考える、落ち着いた子。",
  "firstPerson": "ぼく",
  "speechNote": "落ち着いて、やさしく話します。",
  "firstWords": "はじめまして。いろいろ、おしえてね。"
}
```

| 項目 | 条件・用途 |
|---|---|
| nameCandidates | 必ず異なる3候補。生成目標は1〜6文字のひらがな・カタカナ。呼びやすく、不適切な語や実在ブランド等を避ける。候補もバックエンドで再検証。 |
| description | 性格の紹介。生成目標40文字以内、現在のサーバー受入上限80文字。 |
| firstPerson | ぼく／わたし／おれ／うち のいずれか。会話用に保存し、名前確定時にも送る。 |
| speechNote | 話し方の説明。生成目標30文字以内、受入上限60文字。表示用であり、自由な会話指示として扱わない。 |
| firstWords | 誕生時に表示する最初のひとこと。生成目標40文字以内、受入上限80文字。赤ちゃんらしく、ひらがな多め。 |

すべて空文字不可。子どもにも安心な内容にし、性別・年齢・体・家族を勝手に推測した文章にしません。
画像・音声・petId・所有者情報・6軸の更新値は、このAI応答に含める必要はありません。

### Cloud FunctionsからFlutterへの返却例

```json
{
  "status":"ok",
  "petId":"pet_example",
  "birthStatus":"profile_ready",
  "regenerated":false,
  "source":"ai",
  "nameCandidates":["モチ","ポポ","ルル"],
  "description":"ものごとをじっくり考える、落ち着いた子。",
  "firstPerson":"ぼく",
  "speechNote":"落ち着いて、やさしく話します。",
  "firstWords":"はじめまして。いろいろ、おしえてね。"
}
```

status・petId・birthStatus等のAPI管理項目はCloud Functionsが付けます。sourceも検証・採用結果に応じてCloud Functionsが管理します。
Mac側でsourceを返す場合も、保存時の最終判定はCloud Functionsです。

## 7. 保存・再開・失敗時

- 保存先はpets/{petId}.birthProfile。sourceはbirthProfile.sourceに入れます。
- birthProfileには5つの生成項目とsourceを保存します。現在のバックエンドはgeneratedAt・regenerateCountも管理します。
- 採用した名前・firstPersonの最終保存はsetPetNameが担当します。
- 初期性格・birthTrait・所有権・世代をAI生成の都合で書き換えません。
- AI停止、タイムアウト、不正JSON、項目不足、候補名不正ではCloud Functionsが予備文へ切り替え、source:"template"として返します。
- source:"template"でもそのまま名前選択・誕生へ進めます。
- 現行バックエンドのAI呼び出し設定は12秒。FlutterのgenerateBirthProfile待機は25秒。
- AI担当の提案にある「/birthを10秒で打ち切る」はMac接続時の案です。現在の12秒設定と同じものとして扱わず、切替時にバックエンド担当と調整してください。
- 通信応答が不明な場合は、FlutterがgetPetで状態を確認します。保存済みの下書きがあれば再利用します。
- APIキー等はサーバー側で管理し、Flutter・Core2に埋め込みません。

## 8. 担当間で確認すること

1. 現行のCloud Functions → OpenAI直接呼び出しを継続するか、Cloud Functions → Mac /birthへ切り替えるか。
2. Macへ切り替える場合のURL・認証・入出力キー・タイムアウト。
3. baseTypeの決定方法・時点。未決定でも誕生プロフィール生成は進められるようにする。
4. 質問・回答の文章もAIへ渡すか。現行は6軸と代表特徴だけ。
5. 本番デプロイ完了と、実機から①②③を通せること。リポジトリに実装があることと本番確認済みであることは別。

## 9. AI側の確認項目

- 代表軸ごとに入力し、性格と矛盾しない5項目のJSONが返る。
- 6軸同率でも生成でき、代表軸以外の情報を失わない。
- 名前候補は3つ・重複なし、一人称は指定4種類のみ。
- baseTypeなしでも生成できる。
- 文字数上限と不適切表現の条件を満たす。
- サーバー停止・遅延・不正応答時はCloud Functionsの予備文で誕生を継続できる。
- 再開時は保存済みプロフィールを返し、意図しない再生成をしない。

## 10. この資料の根拠

現在のFlutterのbirth_screen.dart・birth_service.dart・birth_questionnaire.dart、バックエンドのpetlogic/birth_profile.py、および担当者間で共有された誕生フローを基に作成。
「実装済み」と「Mac接続時の案」は区別して記載しています。本番の動作保証を示す資料ではありません。
