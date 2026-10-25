# Core2向けキャラクター画像BLE転送

Androidは`getPet.appearance`に対応する表示済みの体・目・口を192×192ピクセル以下で撮影し、PNGで圧縮して送る。Cloud Functionsは画像バイト列ではなく`appearance`を返す。PNGが32 KiBを超える場合は160、128、96ピクセルに縮小し、最大128 KiBまで許可する。

Core2の既存サービス`7f5a0001-7b7d-4f3b-9d01-000000000001`に、以下の特性を追加する必要がある。現在のCore2ファームウェアには未実装なので、Androidは特性が見つからなければ「未対応」と表示する。

| 特性 | UUID末尾 | プロパティ |
| --- | --- | --- |
| Image DATA | `0009` | WRITE、可能ならWRITE WITHOUT RESPONSE |
| Image ACK | `000a` | NOTIFY |

整数はリトルエンディアン。1回のDATA書き込みはMTUに合わせて最大244バイト（ヘッダ4バイト＋画像240バイト）。Androidは8パケットごとに累積ACKを待ち、700 ms以内に届かなければ同じ窓を再送する。

| 種類 | バイト列 |
| --- | --- |
| START | `01 session width:u16 height:u16 codec=01 chunkSize:u8 byteLength:u32 crc32:u32 petIdCrc32:u32`。合計20バイト |
| DATA | `02 session sequence:u16 pngBytes...`。sequenceは1から |
| END | `03 session sequence:u16`。sequenceは最終DATA+1 |
| ACK | `02 session sequence:u16`。STARTは0、DATAは受信済み最大連続番号、ENDはEND番号 |
| ERROR | `04 session code 00`。1=形式、2=処理中、3=メモリ不足、4=CRC不一致等 |

Core2はSTARTで幅・高さ・長さ・形式と、現在のpetIdのUTF-8バイト列に対するCRC32を検査し、DATAを順番どおりに組み立てる。ENDで長さ・PNGのCRC32・現在のpetIdを再確認し、PNGのデコード・表示を完了してからENDのACKを送る。音声受信・録音・再生中はERROR(2)を返す。Androidの画面には送信済み容量、進捗、経過時間から計算したKiB/秒を表示し、転送完了時の計測値をJSONLログにも保存する。
