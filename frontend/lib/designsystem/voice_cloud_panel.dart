import 'package:flutter/material.dart';
import '../foundation/services/voice_cloud_service.dart';

class VoiceCloudPanel extends StatelessWidget {
  const VoiceCloudPanel({super.key, required this.service});
  final VoiceCloudService service;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: service,
    builder: (context, _) {
      final cloud = service;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '録音音声をCloud Functionsへ送信',
            style: TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          const Text(
            '接続先が自分のCore2であることを確認してください。表示されたdeviceIdで登録し、次の録音から自動送信します。',
          ),
          SelectableText('deviceId: ${cloud.connectionDeviceId ?? "未取得"}'),
          if (cloud.connected && cloud.connectionDeviceId == null)
            const Text('接続先のBLEアドレスを取得できません。接続を確認してください。'),
          const SizedBox(height: 8),
          FilledButton(
            onPressed:
                !cloud.connected ||
                    cloud.connectionDeviceId == null ||
                    cloud.busy ||
                    cloud.enabled
                ? null
                : cloud.enable,
            child: const Text('この接続先を登録し音声送信を有効化'),
          ),
          if (cloud.enabled)
            OutlinedButton(
              onPressed: cloud.busy ? null : cloud.disable,
              child: const Text('音声送信を無効化'),
            ),
          if (cloud.busy) const LinearProgressIndicator(),
          SelectableText(cloud.status),
          if (cloud.deviceId != null)
            SelectableText(
              '登録deviceId: ${cloud.deviceId}\npetId: ${cloud.petId}',
            ),
          if (cloud.transcript != null && cloud.transcript!.isNotEmpty)
            SelectableText('聞き取った内容: ${cloud.transcript}'),
          if (cloud.replyText != null && cloud.replyText!.isNotEmpty)
            SelectableText('返答: ${cloud.replyText}'),
          if (cloud.learnedWords.isNotEmpty)
            Text('覚えた言葉: ${cloud.learnedWords.join("、")}'),
          if (cloud.connected && !cloud.canSendReply)
            const Text('このCore2は返答音声の受信サービスに未対応です。'),
          if (cloud.replyTransferStatus != null)
            Text(cloud.replyTransferStatus!),
          if (cloud.replyTotalBytes > 0) ...[
            LinearProgressIndicator(
              value: cloud.replySentBytes / cloud.replyTotalBytes,
            ),
            Text(
              'Core2へ転送: ${cloud.replySentBytes} / ${cloud.replyTotalBytes} bytes',
            ),
          ],
          if (cloud.replyAudio != null)
            Text('返答音声: ${cloud.replyAudio!.length} bytes受信'),
        ],
      );
    },
  );
}
