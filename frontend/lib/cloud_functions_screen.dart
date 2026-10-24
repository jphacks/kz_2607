import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'foundation/services/cloud_functions_service.dart';

class CloudFunctionsScreen extends StatefulWidget {
  const CloudFunctionsScreen({super.key, this.service});
  final CloudFunctionsService? service;
  @override
  State<CloudFunctionsScreen> createState() => _CloudFunctionsScreenState();
}

class _CloudFunctionsScreenState extends State<CloudFunctionsScreen> {
  late final service = widget.service ?? CloudFunctionsService();
  bool _busy = false;
  String _status = '未確認';
  @override
  void initState() {
    super.initState();
    unawaited(_ping());
  }

  Future<void> _ping() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _status = 'Firebase初期化・認証・疎通確認中…';
    });
    var message = '';
    try {
      await service.ping();
      message = '疎通確認成功：ping → {ok: true}';
    } on FirebaseFunctionsException catch (e) {
      final details = e.details;
      final reason = details is Map ? details['reason'] : null;
      message = '関数呼び出し失敗\ncode: ${e.code}\nreason: ${reason ?? "なし"}';
    } on FirebaseAuthException catch (e) {
      message = '認証失敗\ncode: ${e.code}';
      if (e.code == 'operation-not-allowed' ||
          e.code == 'admin-restricted-operation') {
        message += '\nFirebase Authenticationの匿名ログイン設定を確認してください。';
      }
    } on FirebaseException catch (e) {
      message =
          'Firebase初期化・設定エラー\ncode: ${e.code}\n設定ファイルの配置後、アプリをビルドし直してください。';
    } on PlatformException catch (e) {
      message =
          '端末のFirebase設定エラー\ncode: ${e.code}\n設定ファイルの配置後、アプリをビルドし直してください。';
    } catch (e) {
      message = '疎通確認失敗：$e';
    }
    if (!mounted) return;
    setState(() {
      _busy = false;
      _status = message;
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Cloud Functionsの疎通確認')),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Text('接続先：asia-northeast1 / ping'),
          const SizedBox(height: 12),
          const Text(
            'この画面を開くと、Firebase初期化 → 未ログインなら匿名ログイン → pingの順に自動確認します。M5Stackの接続は不要です。',
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy ? null : _ping,
            child: Text(_busy ? '確認中…' : '再確認'),
          ),
          if (_busy)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            ),
          const SizedBox(height: 16),
          SelectableText(_status),
          const Divider(height: 32),
          const Text(
            '設定ファイル：android/app/google-services.json\nAndroidパッケージ：com.example.kz_2607\nファイル受領後に配置し、アプリを停止して再ビルドしてください。',
          ),
        ],
      ),
    ),
  );
}
