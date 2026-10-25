# キャラクター誕生フロー

ブランチ: feature/pet-birth-flow

1. アカウント作成・ログイン。
2. ホームの「キャラクターを誕生させる・続きから」を押す。未登録ならM5接続画面へ進む。
3. 接続・端末登録完了後にホームへ戻り、同じボタンを押す。
4. eggでは6問4択に回答し、性格を保存する。
5. personality_setでは設定を生成する。
6. profile_readyでは候補または自由入力で名前を決める。
7. bornになったら最初のひとことを表示し、ホームへ戻る。

## 保存とAPI
- getPet(deviceId)のbirthStatusを再開位置の正とする。
- setInitialPersonality(deviceId, answers, questionnaireVersion, requestId)。回答はactivity/friendly/talkative/logical/curious/nightowl順。6軸の正式計算・保存はサーバー。
- generateBirthProfile(petId, regenerate:false)。Macへの直接接続なし。birthProfile.sourceがtemplateでも使用可能。
- setPetName(deviceId, name, firstPerson)。名前の禁止語判定はサーバー。
- 回答・requestId・確定待ちの名前をスマホ内にUIDとpetId別で保存。通信結果が不明な場合は同じ内容で再送する。
- 再開時とアプリ復帰時はgetPetで再確認する。対象petIdが変わっていれば停止。
- baseTypeは質問から決めず、既存値を変更しない。

## 検証の範囲
Flutter画面とCallable接続を実装。APIの本番デプロイ状態、実機での一連の誕生、誕生によるCore2表示の変化は別途確認が必要。
ホームの既存ペット画像・性格・ゲージは表示サンプルのまま。誕生画面の名前と紹介はAPI結果。
