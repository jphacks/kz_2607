import 'package:flutter/material.dart';
import 'foundation/services/core2_ble.dart';

/// Temporary diagnostic UI; product screens will be implemented separately.
class Core2ConnectionPage extends StatefulWidget {
  const Core2ConnectionPage({super.key, this.ble});
  final Core2Ble? ble;
  @override
  State<Core2ConnectionPage> createState() => _Core2ConnectionPageState();
}

class _Core2ConnectionPageState extends State<Core2ConnectionPage> {
  late final Core2Ble ble;
  @override
  void initState() {
    super.initState();
    ble = widget.ble ?? Core2Ble();
  }

  @override
  void dispose() {
    if (widget.ble == null) ble.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: ble,
    builder: (context, _) => Scaffold(
      appBar: AppBar(title: const Text('Core2 BLE接続確認')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Android実機で使用してください。Core2側は共有UUIDのRead / Notifyが必要です。'),
          const SizedBox(height: 12),
          Text(ble.status, style: Theme.of(context).textTheme.titleMedium),
          if (ble.device != null) Text('接続先: ${ble.device!.remoteId}'),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: ble.busy || ble.scanning || ble.device != null
                ? null
                : ble.scan,
            child: Text(ble.scanning ? '検索中…' : 'デバイスを検索'),
          ),
          if (ble.device != null)
            OutlinedButton(
              onPressed: ble.busy ? null : ble.disconnect,
              child: const Text('切断'),
            ),
          const Text('検索結果（名前にM5Stackを含む機器のみ）'),
          for (final result in ble.results)
            ListTile(
              title: Text(
                result.advertisementData.advName.isNotEmpty
                    ? result.advertisementData.advName
                    : '名前なし',
              ),
              subtitle: Text('${result.device.remoteId} / ${result.rssi} dBm'),
              trailing: TextButton(
                onPressed: ble.busy || ble.device != null
                    ? null
                    : () => ble.connect(result.device),
                child: const Text('接続'),
              ),
            ),
          const Divider(),
          const Text('Core2の録音音声'),
          FilledButton(
            onPressed:
                ble.canReceiveVoice && !ble.voiceStarting && !ble.voiceListening
                ? ble.startVoice
                : null,
            child: Text(ble.voiceStarting ? '準備中…' : '音声受信を開始'),
          ),
          Text(ble.voiceStatus),
          if (ble.ready && !ble.canReceiveVoice)
            const Text('Core2側に音声用のBLE特性が必要です。'),
          if (ble.voiceExpected > 0) ...[
            LinearProgressIndicator(
              value: ble.voiceReceived / ble.voiceExpected,
            ),
            Text('${ble.voiceReceived} / ${ble.voiceExpected} bytes（転送データ）'),
          ],
          if (ble.audioPath != null)
            SelectableText('最新WAV（一時保存）: ${ble.audioPath}'),
          const Divider(),
          const Text('受信・エラーログ（新しい順、最大100件）'),
          if (ble.messages.isEmpty) const Text('まだデータはありません'),
          for (final message in ble.messages)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: SelectableText(message),
            ),
        ],
      ),
    ),
  );
}
