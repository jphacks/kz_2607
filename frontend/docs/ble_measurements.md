# BLE音声転送の比較

ACK窓・UUID・送信順序・再送条件は従来どおりです。ACKは4 DATAパケットごと。
write without responseも各writeをawaitし、無制限に並列送信しません。
今回の変更は計測が中心で、Core2の6 ms送信間隔に対してAndroid側の待機は追加しません。

## 記録

接続画面の詳細ログに `BLE計測` とJSONL保存先を表示します。
Android Studioのコンソールにも `BLE_METRIC {JSON}` を出力します。
保存先はアプリの一時ディレクトリ内の `core2_voice/transfers.jsonl`。
一時ファイルなので必要な計測後は取得してください。音声や会話本文は保存せず、
端末ID・時刻・計測値を記録します。

- 上り: START受信からEND受信までの `receiveUs`。録音時間やCore2がSTARTを送る前の時間は含みません。
- 下り: `cloudToStartAckUs`、`dataUs`、`endAckUs`。
  `transferUs` はAndroidの送信開始からEND ACKまで、`totalUs` はCloud応答受領からEND ACKまで。
  `endAckUs` 単独はEND送信段階の時間です。失敗した未完了段階はnull。
- `ackWaitUs`: write完了後に実際にACK待ちした合計時間。write中に到着したACKの時間は含みません。
- MTUは `mtu`、実際に使用したチャンク長は `chunkSize`。
- 下りの `retries` はSTART・DATA窓・ENDの再試行回数の合計。
  `resentPackets` はDATAの重複送信数、`retransmitRate` は全DATA送信数に対する割合。
- 上りの `duplicatePackets` / `outOfOrderPackets` はAndroidで観測したDATA数。
  パケットが届かなかった回数やCore2の実再送回数は断定できないため、Core2ログと照合します。
- `conversationId` で、Cloudへ渡した上りと下りを対応づけます。
  Cloud処理中の新しい録音は従来どおり送信せず、下りのIDは上書きしません。

## 比較手順

1. 同じAndroid端末・Core2・距離・音声サンプル数で、変更前後のログをそれぞれ取得。
   旧ファームウェアにもこの計測版アプリを使用し、12 msと6 msを比較します。
2. `python tools/summarize_ble.py before.jsonl after.jsonl` で中央値と95パーセンタイルを比較。
   端末・方向・サンプル数・codecごとに集計し、失敗も件数に表示します。
   p95はnearest-rank方式。実機の十分な反復数と失敗率も合わせて判断してください。
3. Core2シリアルの転送時間・初回再生キュー投入時間を、方向・セッション番号・順序で照合。
   sessionは8 bitで循環するため番号だけを長時間の一意キーにしないでください。

Core2で最初に音が鳴る時刻はAndroidには通知されていません。
初回再生キュー投入は初回発音と別の指標として扱い、実際の発音はCore2側で計測してください。
端末間の時計を直接引き算せず、それぞれのローカルな経過時間で比較します。
END ACKは受信完了であり、再生完了ではありません。約0.75秒分を受信した時点で
再生が始まるため、初回発音がEND ACKより早くなることがあります。
