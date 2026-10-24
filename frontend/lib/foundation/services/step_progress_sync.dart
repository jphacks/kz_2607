import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'cloud_functions_service.dart';

/// Converts a Core2 lifetime counter into daily totals for recordProgress.
class StepProgressSync {
  StepProgressSync({CloudFunctionsService? api, DateTime Function()? now})
      : _api = api ?? CloudFunctionsService(),
        _now = now ?? DateTime.now;

  static const _uploadInterval = Duration(minutes: 1);
  static const _maxDailySteps = 200000;
  final CloudFunctionsService _api;
  final DateTime Function() _now;
  final Map<String, DateTime> _lastAttempt = {};
  Future<void> _queue = Future<void>.value();

  Future<void> observe({
    required String uid,
    required String deviceId,
    required String petId,
    required int cumulative,
  }) =>
      _enqueue(() async {
    if (cumulative < 0) return;
    final prefs = await SharedPreferences.getInstance();
    final key = _key(uid, deviceId, petId);
    final today = _day(_now());
    final state = _load(prefs, key);
    if (state == null) {
      // A lifetime total cannot reveal steps taken before the first observation.
      await _save(prefs, key, _ProgressState(cumulative, today, {}));
      return;
    }
    if (state.date != today || cumulative < state.lastCount) {
      // At a day boundary or after a counter reset, take a fresh baseline.
      state.date = today;
      state.lastCount = cumulative;
      _prune(state, today);
      await _save(prefs, key, state);
    } else if (cumulative > state.lastCount) {
      final current = state.days.putIfAbsent(today, () => _DailySteps());
      current.steps = (current.steps + cumulative - state.lastCount)
          .clamp(0, _maxDailySteps)
          .toInt();
      state.lastCount = cumulative;
      _prune(state, today);
      await _save(prefs, key, state);
    }
    await _upload(prefs, key, deviceId, state);
  });

  Future<void> flush({
    required String uid,
    required String deviceId,
    required String petId,
  }) =>
      _enqueue(() async {
    final prefs = await SharedPreferences.getInstance();
    final key = _key(uid, deviceId, petId);
    final state = _load(prefs, key);
    if (state != null) await _upload(prefs, key, deviceId, state);
  });

  Future<void> _upload(SharedPreferences prefs, String key, String deviceId,
      _ProgressState state) async {
    final now = _now();
    final lastAttempt = _lastAttempt[key];
    if (lastAttempt != null &&
        !now.isBefore(lastAttempt) &&
        now.difference(lastAttempt) < _uploadInterval) {
      return;
    }
    final today = _day(now);
    final pending = state.days.keys.where((day) {
      final age = DateTime.parse(today).difference(DateTime.parse(day)).inDays;
      final value = state.days[day]!;
      return age >= 0 && age <= 7 && value.steps > value.synced;
    }).toList()..sort();
    if (pending.isEmpty) return;
    _lastAttempt[key] = now;
    for (final day in pending) {
      final value = state.days[day]!;
      final steps = value.steps;
      try {
        await _api.recordProgress(deviceId: deviceId, date: day, steps: steps);
      } catch (error) {
        throw StateError('recordProgress(date=$day, steps=$steps): $error');
      }
      value.synced = steps;
      await _save(prefs, key, state);
    }
  }

  Future<void> _save(
      SharedPreferences prefs, String key, _ProgressState state) async {
    final stored = await prefs.setString(key, jsonEncode(state.toMap()));
    if (!stored) throw StateError('歩数の保存に失敗しました');
  }

  _ProgressState? _load(SharedPreferences prefs, String key) {
    final raw = prefs.getString(key);
    if (raw == null) return null;
    try {
      return _ProgressState.fromMap(jsonDecode(raw));
    } catch (error) {
      throw StateError('保存済みの歩数を読み取れません: $error');
    }
  }

  Future<void> _enqueue(Future<void> Function() action) {
    final result = _queue.then((_) => action());
    _queue = result.catchError((Object _) {});
    return result;
  }

  static String _key(String uid, String deviceId, String petId) =>
      'step_progress_v1_${Uri.encodeComponent(uid)}_${Uri.encodeComponent(deviceId)}_${Uri.encodeComponent(petId)}';

  static void _prune(_ProgressState state, String today) {
    final oldest = DateTime.parse(today).subtract(const Duration(days: 7));
    state.days.removeWhere((day, _) => DateTime.parse(day).isBefore(oldest));
  }

  static String _day(DateTime instant) {
    final jst = instant.toUtc().add(const Duration(hours: 9));
    return '${jst.year.toString().padLeft(4, '0')}-'
        '${jst.month.toString().padLeft(2, '0')}-'
        '${jst.day.toString().padLeft(2, '0')}';
  }
}

class _ProgressState {
  _ProgressState(this.lastCount, this.date, this.days);
  int lastCount;
  String date;
  final Map<String, _DailySteps> days;

  factory _ProgressState.fromMap(Object? raw) {
    if (raw is! Map || raw['lastCount'] is! int ||
        (raw['lastCount'] as int) < 0 || raw['date'] is! String ||
        raw['days'] is! Map) {
      throw const FormatException('歩数データの形式が不正です');
    }
    final days = <String, _DailySteps>{};
    for (final entry in (raw['days'] as Map).entries) {
      if (entry.key is! String) throw const FormatException('日付が不正です');
      days[entry.key as String] = _DailySteps.fromMap(entry.value);
    }
    return _ProgressState(raw['lastCount'] as int, raw['date'] as String, days);
  }

  Map<String, Object?> toMap() => {
        'lastCount': lastCount,
        'date': date,
        'days': days.map((day, value) => MapEntry(day, value.toMap())),
      };
}

class _DailySteps {
  _DailySteps({this.steps = 0, this.synced = 0});
  int steps;
  int synced;

  factory _DailySteps.fromMap(Object? raw) {
    if (raw is! Map || raw['steps'] is! int || raw['synced'] is! int ||
        (raw['steps'] as int) < 0 || (raw['synced'] as int) < 0 ||
        (raw['synced'] as int) > (raw['steps'] as int)) {
      throw const FormatException('日別歩数の形式が不正です');
    }
    return _DailySteps(steps: raw['steps'] as int, synced: raw['synced'] as int);
  }

  Map<String, int> toMap() => {'steps': steps, 'synced': synced};
}
