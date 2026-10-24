import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'designsystem/action_button.dart';
import 'designsystem/connection_message_card.dart';
import 'foundation/app_colors.dart';
import 'foundation/services/core2_ble.dart';

class Core2ConnectionPage extends StatefulWidget {
  const Core2ConnectionPage({super.key, this.ble});
  final Core2Ble? ble;
  @override
  State<Core2ConnectionPage> createState() => _Core2ConnectionPageState();
}

class _Core2ConnectionPageState extends State<Core2ConnectionPage> {
  late final Core2Ble ble;
  String? _selectedId;
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

  ScanResult? get _selected {
    final results = ble.results;
    if (results.isEmpty) return null;
    for (final result in results) {
      if (result.device.remoteId.str == _selectedId) return result;
    }
    return results.first;
  }

  String _name(ScanResult result) => result.advertisementData.advName.isEmpty
      ? 'M5Stack'
      : result.advertisementData.advName;
  String get _deviceName {
    final id = ble.device?.remoteId.str;
    for (final result in ble.results) {
      if (result.device.remoteId.str == id) return _name(result);
    }
    return 'M5Stack';
  }

  String get _relayState {
    final cloud = ble.voiceCloud;
    if (cloud.busy) return cloud.enabled ? '中継中' : '準備中';
    if (ble.voiceStatus.contains('失敗') ||
        ble.voiceStatus.contains('タイムアウト') ||
        cloud.status.contains('失敗') ||
        (cloud.replyTransferStatus?.contains('失敗') ?? false)) {
      return '中断';
    }
    if (ble.voiceStarting) return '準備中';
    if (ble.voiceExpected > ble.voiceReceived) return '受信中';
    return cloud.enabled && ble.voiceListening ? '待機中' : '準備中';
  }

  Widget _text(String value) =>
      Text(value, style: const TextStyle(fontSize: 14, height: 1.5));

  void _help() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '近くに置いて、もう一度',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 16),
              _text(
                'M5Stackの電源と、スマートフォンのBluetoothを確認してください。接続の許可を拒否した場合は、Androidのアプリ設定から許可してください。',
              ),
              const SizedBox(height: 24),
              ActionButton(
                label: 'もう一度探す',
                onPressed: ble.busy || ble.scanning
                    ? null
                    : () {
                        Navigator.pop(sheetContext);
                        ble.scan();
                      },
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: () => Navigator.pop(sheetContext),
                child: const Text('閉じる'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _connectionSettings() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: ListenableBuilder(
          listenable: ble,
          builder: (_, _) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '接続を確認',
                  style: const TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 16),
                _text(ble.ready ? 'M5Stackと接続しています。' : 'M5Stackとの接続を確認してください。'),
                if (ble.voiceCloud.connectionDeviceId != null)
                  SelectableText(
                    'deviceId: ${ble.voiceCloud.connectionDeviceId}',
                  ),
                const SizedBox(height: 16),
                ActionButton(
                  label: '接続し直す',
                  onPressed: ble.busy || ble.voiceCloud.busy
                      ? null
                      : () async {
                          Navigator.pop(sheetContext);
                          await ble.disconnect();
                          if (mounted) await ble.scan();
                        },
                ),
                const SizedBox(height: 8),
                if (ble.ready)
                  TextButton(
                    onPressed: ble.busy || ble.voiceCloud.busy
                        ? null
                        : () async {
                            Navigator.pop(sheetContext);
                            await ble.disconnect();
                          },
                    child: const Text('M5Stackとの接続を解除'),
                  ),
                TextButton(
                  onPressed: () => Navigator.pop(sheetContext),
                  child: const Text('閉じる'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _searchContent() {
    final selected = _selected;
    return [
      ConnectionMessageCard(
        color: AppColors.memoryBackground,
        title: ble.busy && ble.device != null
            ? 'M5Stackに接続しています'
            : ble.scanning
            ? '近くのデバイスを探しています'
            : ble.status.contains('検索終了') && selected == null
            ? 'M5Stackが見つかりません'
            : 'M5Stackを探しましょう',
        child: _text('Bluetoothをオンにして、M5Stackを近づけてください。'),
      ),
      const SizedBox(height: 16),
      if (selected == null)
        const ConnectionMessageCard(
          title: '近くのM5Stack',
          child: Text(
            'まだデバイスが見つかっていません。',
            style: TextStyle(fontSize: 14, height: 1.5),
          ),
        ),
      for (final result in ble.results) ...[
        Semantics(
          selected: result == selected,
          button: true,
          child: InkWell(
            borderRadius: BorderRadius.circular(20),
            onTap: ble.busy
                ? null
                : () =>
                      setState(() => _selectedId = result.device.remoteId.str),
            child: ConnectionMessageCard(
              title: _name(result),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(result == selected ? '検出済み / 接続先に選択中' : '検出済み / 未接続'),
                  Text(
                    result.device.remoteId.str,
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.muted,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 16),
      ],
      if (selected == null) const SizedBox(height: 16),
      ActionButton(
        label: ble.busy
            ? '接続中…'
            : selected != null
            ? 'このM5Stackに接続'
            : ble.scanning
            ? '探索中…'
            : 'デバイスを探す',
        onPressed:
            ble.busy || ble.device != null || (ble.scanning && selected == null)
            ? null
            : selected == null
            ? ble.scan
            : () => ble.connect(selected.device),
      ),
      const SizedBox(height: 16),
      const ConnectionMessageCard(
        color: AppColors.soft,
        title: '接続する前に',
        child: Text('AndroidのBluetoothの許可が必要です。接続するM5Stackを確認してから選んでください。'),
      ),
      const SizedBox(height: 16),
      ActionButton(label: '見つからないとき', onPressed: _help),
      if (selected != null)
        Center(
          child: TextButton(
            onPressed: ble.busy || ble.scanning || ble.device != null
                ? null
                : ble.scan,
            child: const Text('もう一度探す'),
          ),
        ),
      const SizedBox(height: 16),
      Text(
        ble.status.contains('失敗') || ble.status.contains('できません')
            ? '接続を完了できませんでした。接続先と許可を確認し、もう一度お試しください。'
            : '接続するM5Stackの電源とBluetoothをご確認ください。',
        style: const TextStyle(
          fontSize: 12,
          height: 1.5,
          color: AppColors.muted,
        ),
      ),
    ];
  }

  List<Widget> _connectedContent() {
    final cloud = ble.voiceCloud;
    return [
      ConnectionMessageCard(
        color: AppColors.soft,
        title: _deviceName,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('BLE：接続済み'),
            Text(
              'クラウド：${cloud.busy
                  ? "通信中"
                  : cloud.enabled
                  ? "端末登録済み"
                  : "未確認"}',
            ),
            const Text('最終同期：未確認'),
            if (cloud.connectionDeviceId != null)
              SelectableText(
                'deviceId: ${cloud.connectionDeviceId}',
                style: const TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: AppColors.muted,
                ),
              ),
          ],
        ),
      ),
      const SizedBox(height: 14),
      ConnectionMessageCard(
        title: '音声の中継：$_relayState',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _text('会話はM5Stackで行います。アプリは音声の中継状態をお知らせします。'),
            if (cloud.replyTotalBytes > 0 && cloud.busy) ...[
              const SizedBox(height: 8),
              LinearProgressIndicator(
                value: cloud.replySentBytes / cloud.replyTotalBytes,
              ),
            ],
            if (_relayState == '中断') _text('音声を中継できませんでした。接続を確認してください。'),
          ],
        ),
      ),
      const SizedBox(height: 14),
      ActionButton(label: '再接続・接続を確認', onPressed: _connectionSettings),
      const SizedBox(height: 14),
      const Text(
        '話す・録音する・再生する操作はM5Stackで行います。',
        style: TextStyle(fontSize: 12, height: 1.5, color: AppColors.muted),
      ),
    ];
  }

  Widget _details() => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    childrenPadding: const EdgeInsets.only(bottom: 16),
    title: const Text(
      '接続・中継の詳細',
      style: TextStyle(fontSize: 13, color: AppColors.muted),
    ),
    children: [
      ConnectionMessageCard(
        title: '接続・音声の状態',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SelectableText(ble.status),
            SelectableText(ble.voiceStatus),
            if (ble.canReceiveVoice &&
                !ble.busy &&
                !ble.voiceStarting &&
                !ble.voiceListening)
              TextButton(
                onPressed: ble.startVoice,
                child: const Text('音声受信を再試行'),
              ),
            if (ble.voiceExpected > 0)
              Text('受信: ${ble.voiceReceived} / ${ble.voiceExpected} bytes'),
            if (ble.audioPath != null)
              SelectableText('最新WAV（一時保存）: ${ble.audioPath}'),
            const SizedBox(height: 16),
            SelectableText(ble.voiceCloud.status),
            SelectableText(ble.petConfigStatus),
            if (ble.voiceCloud.replyTransferStatus != null)
              SelectableText(ble.voiceCloud.replyTransferStatus!),
            const Divider(),
            const Text('受信・エラーログ（新しい順）'),
            if (ble.messages.isEmpty) const Text('まだログはありません'),
            for (final message in ble.messages)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: SelectableText(message),
              ),
          ],
        ),
      ),
    ],
  );

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: ble,
    builder: (context, _) => Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                const Text(
                  'M5Stack · 接続設定',
                  style: TextStyle(
                    fontSize: 11,
                    height: 1.5,
                    color: AppColors.muted,
                  ),
                ),
                const SizedBox(height: 14),
                Text(
                  ble.ready ? 'M5Stackの接続' : 'M5Stackをつなぐ',
                  style: const TextStyle(
                    fontSize: 24,
                    height: 1.5,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 14),
                Text(
                  ble.ready ? '接続中のM5Stackを確認できます。' : '近くのM5Stackの電源を入れてください。',
                  style: const TextStyle(
                    fontSize: 14,
                    height: 1.5,
                    color: AppColors.muted,
                  ),
                ),
                const SizedBox(height: 14),
                ...ble.ready ? _connectedContent() : _searchContent(),
                const SizedBox(height: 16),
                _details(),
                Center(
                  child: TextButton(
                    onPressed: () => Navigator.maybePop(context),
                    child: const Text('ホームに戻る'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
