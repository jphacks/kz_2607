# パーツ合成表示

素材は提供されたPNGを変更せず assets/pet_parts/{animals,eyes,mouth}/ に格納。
バックエンドのappearanceの選択をそのまま使い、フロントで性格順位を再計算しない。

## フロントの暫定対応

- primary: 体の種類
- stage: baby / child / adult の体画像
- secondary: 目の種類
- tertiary: 口の種類（旧APIで未設定の場合のみsecondaryを使用）
- activity: 犬・mouth_01_open_smile
- friendly: カピバラ・mouth_02_cat
- talkative: インコ・mouth_03_open_o
- logical: フクロウ・mouth_04_smile
- curious: ミーアキャット・mouth_05_small_o
- nightowl: ハリネズミ・mouth_06_smile_side

Core2との正式な対応表は未確認。この表はフロント表示用。
18枚の体ごとに元の画像サイズ、目の座標、口の座標をpet_part_layout.dartで定義。
目と口は透過余白や縦横比を維持してサイズ調整し、体のピクセル座標でStack合成。
最後に全体をFittedBoxで一括拡縮するので画面サイズで位置がずれない。
体には元から目があるため、元画像を編集せず、顔色の下地で元の目を隠す。
犬の目付近はクリーム色の口元にまたがるため、下地にも口元の色を重ねる。
現在は静止画のみ。口パクは対象外。
