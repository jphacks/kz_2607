import '../models/pending_exchange.dart';

class ExchangeApiError implements Exception {
  const ExchangeApiError(this.code, this.message, {this.reason});
  final String code, message;
  final String? reason;
  @override
  String toString() => '$code${reason == null ? '' : '/$reason'}: $message';
}

class ExchangeDecision {
  const ExchangeDecision(this.result, this.message, {this.petId});
  final String result; // done / already_done / rejected / confirming
  final String message;
  final String? petId;
  bool get terminal => result != 'confirming';
}

typedef ExchangeCall =
    Future<Map<String, dynamic>> Function(
      String name,
      Map<String, dynamic> arguments,
    );

/// Pure decision logic: BLE and persistence are handled by the controller.
class ExchangeResolver {
  const ExchangeResolver(this.call);
  final ExchangeCall call;

  Future<ExchangeDecision> resolve(PendingExchange x) async {
    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        final report = await call('reportExchange', x.toMap());
        if (report['transactionId'] != x.transactionId ||
            !{'done', 'already_done'}.contains(report['status']) ||
            report['givenPetId'] != x.givenPetId ||
            report['receivedPetId'] != x.gotPetId) {
          return const ExchangeDecision(
            'confirming',
            '交換応答が想定と一致しません。確定せず確認してください。',
          );
        }
        return ExchangeDecision(
          report['status'] as String,
          'サーバーで交換確定',
          petId: x.gotPetId,
        );
      } on ExchangeApiError catch (error) {
        if (error.reason == 'transaction_mismatch') {
          return const ExchangeDecision(
            'confirming',
            '交換IDの内容が不一致です。自動取消せず担当者へ確認してください。',
          );
        }
        if ({
          'invalid-argument',
          'permission-denied',
          'not-found',
          'failed-precondition',
        }.contains(error.code)) {
          break;
        }
      } catch (_) {
        /* Retry the exact same request once before querying. */
      }
    }
    try {
      final query = await call('getExchangeResult', {
        'transactionId': x.transactionId,
        'myDeviceId': x.myDeviceId,
      });
      final result = _status(query, x);
      if (result != null) return result;
      // Only an explicitly unknown result is eligible for a cancellation request.
      if (query['transactionId'] != x.transactionId ||
          query['status'] != 'unknown') {
        return const ExchangeDecision('confirming', '照会応答の形式が不明です。保留しています。');
      }
      final cancel = await call('cancelExchange', {
        'transactionId': x.transactionId,
        'myDeviceId': x.myDeviceId,
        'peerDeviceId': x.peerDeviceId,
      });
      return _status(cancel, x) ??
          const ExchangeDecision('confirming', '取消の確定を確認できません。');
    } catch (error) {
      return ExchangeDecision('confirming', '交換結果の確認待ち：$error');
    }
  }

  ExchangeDecision? _status(Map<String, dynamic> data, PendingExchange x) {
    if (data['transactionId'] != x.transactionId) return null;
    if (data['status'] == 'cancelled') {
      return ExchangeDecision('rejected', 'サーバーで取消確定', petId: x.givenPetId);
    }
    if (data['status'] == 'confirmed') {
      if (data['givenPetId'] != x.givenPetId ||
          data['receivedPetId'] != x.gotPetId) {
        return const ExchangeDecision(
          'confirming',
          '確定結果のペットIDが不一致です。担当者へ確認してください。',
        );
      }
      if (data['currentPetId'] != null && data['currentPetId'] != x.gotPetId) {
        return const ExchangeDecision(
          'confirming',
          'この交換は確定済みですが、現在のペットが異なります。再同期を確認してください。',
        );
      }
      return ExchangeDecision('done', '交換確定を照会で確認しました', petId: x.gotPetId);
    }
    return null;
  }
}


