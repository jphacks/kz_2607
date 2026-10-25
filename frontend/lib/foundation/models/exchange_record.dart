import 'pending_exchange.dart';

/// Read-only view of one persisted exchange, including Core2 acknowledgement.
class ExchangeRecord {
  const ExchangeRecord({
    required this.exchange,
    required this.result,
    required this.acknowledged,
  });
  final PendingExchange exchange;
  final String result;
  final bool acknowledged;
  bool get completed => {'done', 'already_done'}.contains(result);
  bool get cancelled => result == 'rejected';
  String get status {
    if (completed) return acknowledged ? '交換完了' : '交換確定・M5への反映待ち';
    if (cancelled) return acknowledged ? '取消完了' : '取消確定・M5への反映待ち';
    return '交換結果を確認中';
  }
}
