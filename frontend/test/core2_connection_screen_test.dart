import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/core2_connection_screen.dart';
import 'package:kz_2607/foundation/app_colors.dart';
import 'package:kz_2607/foundation/services/core2_ble.dart';
import 'package:kz_2607/foundation/services/cloud_functions_service.dart';
import 'package:kz_2607/foundation/services/voice_cloud_service.dart';
import 'home_screen_test.dart' show loadHomeFont;

class FakeCore2Ble extends ChangeNotifier implements Core2Ble {
  FakeCore2Ble() {
    voiceCloud.addListener(notifyListeners);
  }
  @override
  final voiceCloud = VoiceCloudService(
    api: CloudFunctionsService(
      prepare: () async {},
      invoke: (name, data, _) async => {
        'deviceId': data['deviceId'],
        'petId': 'pet-1',
        'isNew': false,
      },
    ),
  );
  @override
  bool ready = false;
  @override
  bool scanning = false;
  @override
  bool busy = false;
  @override
  BluetoothDevice? device;
  @override
  String status = '未接続';
  @override
  String voiceStatus = '音声受信準備完了';
  @override
  bool voiceStarting = false;
  @override
  bool voiceListening = true;
  @override
  bool get canReceiveVoice => ready;
  @override
  int voiceExpected = 0;
  @override
  int voiceReceived = 0;
  @override
  String? audioPath;
  @override
  final List<String> messages = ['確認用のログ'];
  @override
  List<ScanResult> results = [];
  String? connectedId;
  int scans = 0;
  @override
  Future<void> scan() async {
    scans++;
    notifyListeners();
  }

  @override
  Future<void> connect(BluetoothDevice target) async {
    connectedId = target.remoteId.str;
    device = target;
    ready = true;
    voiceCloud.startForConnection(target.remoteId.str);
    notifyListeners();
  }

  @override
  Future<void> disconnect() async {
    device = null;
    ready = false;
    voiceCloud.setConnection(null);
    notifyListeners();
  }

  @override
  Future<void> startVoice() async {
    voiceListening = true;
    notifyListeners();
  }

  @override
  void dispose() {
    voiceCloud.removeListener(notifyListeners);
    voiceCloud.dispose();
    super.dispose();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

ScanResult candidate(String id, String name) => ScanResult(
  device: BluetoothDevice.fromId(id),
  advertisementData: AdvertisementData(
    advName: name,
    txPowerLevel: null,
    appearance: null,
    connectable: true,
    manufacturerData: {},
    serviceData: {},
    serviceUuids: [],
  ),
  rssi: -45,
  timeStamp: DateTime(2026, 10, 24),
);
Widget app(FakeCore2Ble ble) => MaterialApp(
  theme: ThemeData(
    useMaterial3: true,
    fontFamily: 'NotoSansJP',
    fontFamilyFallback: const [
      'NotoSans',
      'NotoSansSymbols',
      'NotoSansSymbols2',
    ],
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      primary: AppColors.primary,
      surface: AppColors.surface,
    ),
  ),
  home: Core2ConnectionPage(ble: ble),
);
void main() {
  setUpAll(() async {
    await loadHomeFont();
    final icons = FontLoader('MaterialIcons');
    icons.addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });
  void phone(WidgetTester tester, {Size size = const Size(390, 844)}) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  testWidgets(
    'selecting a Core2 automatically registers it without activation controls',
    (tester) async {
      final ble = FakeCore2Ble();
      addTearDown(ble.dispose);
      phone(tester);
      ble.results = [
        candidate('AA:BB:CC:DD:EE:01', 'M5Stack Core2 A'),
        candidate('AA:BB:CC:DD:EE:02', 'M5Stack Core2 B'),
      ];
      await tester.pumpWidget(app(ble));
      await tester.tap(find.text('M5Stack Core2 B'));
      await tester.pump();
      await tester.ensureVisible(find.text('このM5Stackに接続'));
      await tester.tap(find.text('このM5Stackに接続'));
      await tester.pumpAndSettle();
      expect(ble.connectedId, 'AA:BB:CC:DD:EE:02');
      await tester.drag(find.byType(ListView).first, const Offset(0, 600));
      await tester.pumpAndSettle();
      expect(find.text('M5Stackの接続'), findsOneWidget);
      expect(find.text('このM5Stackで音声をつなぐ'), findsNothing);
      expect(find.text('音声送信を有効化'), findsNothing);
      expect(find.text('設定へ'), findsNothing);
      expect(ble.voiceCloud.deviceId, 'AABBCCDDEE02');
      expect(ble.voiceCloud.enabled, true);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('diagnostic logs are collapsed and help allows rescanning', (
    tester,
  ) async {
    final ble = FakeCore2Ble();
    addTearDown(ble.dispose);
    phone(tester);
    await tester.pumpWidget(app(ble));
    expect(find.text('確認用のログ'), findsNothing);
    await tester.ensureVisible(find.text('見つからないとき'));
    await tester.tap(find.text('見つからないとき'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('もう一度探す'));
    await tester.pumpAndSettle();
    expect(ble.scans, 1);
    await tester.ensureVisible(find.text('接続・中継の詳細'));
    await tester.tap(find.text('接続・中継の詳細'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('確認用のログ'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('確認用のログ'), findsOneWidget);
    expect(find.text('Cloud Functionsの疎通確認'), findsNothing);
    expect(find.text('この接続先を登録し音声送信を有効化'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('connected screen matches Figma visual structure', (
    tester,
  ) async {
    final ble = FakeCore2Ble();
    addTearDown(ble.dispose);
    phone(tester);
    final target = candidate('AA:BB:CC:DD:EE:01', 'M5Stack');
    ble.results = [target];
    await ble.connect(target.device);
    await ble.voiceCloud.enable();
    await tester.pumpWidget(app(ble));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(Core2ConnectionPage),
      matchesGoldenFile('core2_connected_preview.png'),
    );
  });
  testWidgets('detected screen matches Figma visual structure', (tester) async {
    final ble = FakeCore2Ble();
    addTearDown(ble.dispose);
    phone(tester);
    ble.scanning = true;
    ble.results = [candidate('AA:BB:CC:DD:EE:01', 'M5Stack Core2')];
    await tester.pumpWidget(app(ble));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(Core2ConnectionPage),
      matchesGoldenFile('core2_scan_preview.png'),
    );
  });
  testWidgets('large text keeps connection settings and disconnect usable', (
    tester,
  ) async {
    final ble = FakeCore2Ble();
    addTearDown(ble.dispose);
    phone(tester, size: const Size(320, 640));
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await ble.connect(BluetoothDevice.fromId('AA:BB:CC:DD:EE:01'));
    await tester.pumpWidget(app(ble));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('再接続・接続を確認'),
      160,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.ensureVisible(find.text('再接続・接続を確認'));
    await tester.tap(find.text('再接続・接続を確認'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('M5Stackとの接続を解除'),
      120,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.ensureVisible(find.text('M5Stackとの接続を解除'));
    await tester.tap(find.text('M5Stackとの接続を解除'));
    await tester.pumpAndSettle();
    expect(ble.ready, false);
    expect(tester.takeException(), isNull);
  });
}
