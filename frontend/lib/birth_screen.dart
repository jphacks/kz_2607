import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:flutter/material.dart';
import 'foundation/models/birth_character.dart';
import 'designsystem/birth_question_panel.dart';
import 'foundation/app_colors.dart';
import 'foundation/models/birth_questionnaire.dart';
import 'foundation/models/birth_request_id.dart';
import 'foundation/services/birth_service.dart';
import 'foundation/services/birth_flow_store.dart';

/// The device must already be registered before this route is opened.
class BirthScreen extends StatefulWidget {
  const BirthScreen({
    super.key,
    required this.deviceId,
    required this.petId,
    required this.canContinue,
    this.service,
    this.uid,
  });
  final String deviceId, petId;
  final bool Function() canContinue;
  final BirthService? service;
  final String? uid;
  @override
  State<BirthScreen> createState() => _BirthScreenState();
}

class _BirthScreenState extends State<BirthScreen> with WidgetsBindingObserver {
  late final BirthService _service = widget.service ?? BirthService();
  BirthFlowStore? _store;
  BirthState? _state;
  BirthProfile? _profile;
  final _name = TextEditingController();
  List<int?> _answers = List.filled(6, null);
  String _requestId = createBirthRequestId();
  bool _busy = true, _initialPending = false, _namePending = false;
  String? _error;
  Future<void> _writes = Future.value();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _restore();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _name.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && !_busy) _run(_refresh);
  }

  String _errorMessage(Object error) {
    if (error is FirebaseFunctionsException) {
      final details = error.details;
      final reason = details is Map ? details['reason'] : null;
      return '${error.message ?? "処理を完了できませんでした。"}\ncode: ${error.code}${reason == null ? "" : " / reason: $reason"}';
    }
    return '$error';
  }

  Future<void> _save() {
    final answers = List<int?>.of(_answers);
    final name = _name.text;
    final requestId = _requestId;
    final initialPending = _initialPending, namePending = _namePending;
    _writes = _writes
        .catchError((Object _) {})
        .then(
          (_) => _store!.save(
            requestId,
            answers,
            name,
            initialPending: initialPending,
            namePending: namePending,
          ),
        );
    return _writes;
  }

  Future<void> _restore() async {
    try {
      final uid = widget.uid ?? FirebaseAuth.instance.currentUser?.uid;
      if (uid == null) throw StateError('ログインしてからやり直してください。');
      _store = BirthFlowStore(uid, widget.petId);
      final saved = await _store!.load();
      if (saved != null) {
        _requestId = saved['requestId'] as String;
        _answers = (saved['answers'] as List).cast<int?>();
        _name.text = saved['name'] is String ? saved['name'] as String : '';
        _initialPending = saved['initialPending'] == true;
        _namePending = saved['namePending'] == true;
      }
      await _refresh();
    } catch (e) {
      if (mounted) setState(() => _error = _errorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _refresh() async {
    final state = await _service.load(
      deviceId: widget.deviceId,
      petId: widget.petId,
    );
    if (!mounted) return;
    setState(() {
      _state = state;
      _profile = state.profile;
      if (state.status == BirthStatus.profileReady &&
          !_namePending &&
          _name.text.isEmpty) {
        _name.text = state.profile!.nameCandidates.first;
      }
    });
  }

  Future<void> _run(Future<void> Function() operation) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (!widget.canContinue()) throw StateError('登録したM5に接続し直してください。');
      await operation();
    } catch (e) {
      if (mounted) setState(() => _error = _errorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitAnswers() async {
    _initialPending = true;
    await _save(); // Keep the same answers and request ID if the response is lost.
    await _service.setInitial(
      deviceId: widget.deviceId,
      petId: widget.petId,
      requestId: _requestId,
      answers: BirthAnswers(_answers.cast<int>()),
    );
    await _refresh();
  }

  Future<void> _generate() async {
    await _refresh();
    if (_state!.status != BirthStatus.personalitySet) return;
    await _service.generate(petId: widget.petId);
    await _refresh();
  }

  Future<void> _confirm() async {
    if (_name.text.trim().isEmpty || _name.text.trim().runes.length > 12) {
      throw const FormatException('名前は1〜12文字で入力してください。');
    }
    _namePending = true;
    await _save();
    final BirthConfirmation result;
    try {
      result = await _service.confirm(
        deviceId: widget.deviceId,
        petId: widget.petId,
        name: _name.text,
        firstPerson: _profile!.firstPerson,
      );
    } on FirebaseFunctionsException catch (e) {
      if (e.code == 'invalid-argument') {
        _namePending = false;
        await _save();
      }
      rethrow;
    }
    await _refresh();
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${result.name}が生まれました！'),
        content: Text(result.firstWords ?? 'はじめまして！'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('閉じる'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: AppColors.background,
    appBar: AppBar(
      title: const Text('キャラクターの誕生'),
      backgroundColor: AppColors.background,
      surfaceTintColor: Colors.transparent,
    ),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const Text(
          'あなたとの出会いから、この子の物語がはじまります。',
          style: TextStyle(color: AppColors.muted, height: 1.7),
        ),
        const SizedBox(height: 16),
        if (_busy && _state?.status != BirthStatus.born)
          const Column(
            children: [
              LinearProgressIndicator(),
              SizedBox(height: 8),
              Text('保存状態を確認・処理しています…'),
            ],
          ),
        if (_error != null) ...[
          Text(
            _error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          const Text('通信が途切れた場合も、まず保存状態を再確認してください。'),
        ],
        if (_state?.status == BirthStatus.egg) ...[
          BirthQuestionPanel(
            answers: _answers,
            busy: _busy,
            locked: _initialPending,
            onChanged: (question, choice) async {
              if (_busy || _initialPending) return;
              setState(() {
                _answers[question] = choice;
                _error = null;
              });
              try {
                await _save();
              } catch (_) {
                if (mounted) {
                  setState(() => _error = '回答をスマホに保存できませんでした。もう一度選択してください。');
                }
              }
            },
            onSubmit: () => _run(_submitAnswers),
          ),
        ],
        if (_state?.status == BirthStatus.personalitySet) ...[
          const Text('性格を保存しました。次に、名前候補や性格の紹介を生成します。'),
          FilledButton(
            onPressed: _busy ? null : () => _run(_generate),
            child: const Text('キャラクター設定を生成する'),
          ),
        ],
        if (_state?.status == BirthStatus.profileReady && _profile != null) ...[
          Text(_profile!.description),
          const SizedBox(height: 12),
          Text('一人称：${_profile!.firstPerson}'),
          Text('話し方：${_profile!.speechNote}'),
          if (_profile!.source == 'template')
            const Text('予備の設定で作成しました。このまま誕生できます。'),
          const SizedBox(height: 16),
          const Text('名前を選ぶか、自分で入力してください（1〜12文字）'),
          Wrap(
            spacing: 8,
            children: [
              for (final name in _profile!.nameCandidates)
                ChoiceChip(
                  label: Text(name),
                  selected: _name.text == name,
                  onSelected: _busy || _namePending
                      ? null
                      : (_) => setState(() => _name.text = name),
                ),
            ],
          ),
          TextField(
            controller: _name,
            enabled: !_busy && !_namePending,
            decoration: const InputDecoration(labelText: '名前'),
          ),
          FilledButton(
            onPressed: _busy ? null : () => _run(_confirm),
            child: Text(_namePending ? '同じ名前で確定を再試行' : 'この名前で誕生する'),
          ),
        ],
        if (_state?.status == BirthStatus.born) ...[
          Text('${_state!.name ?? "この子"}は誕生済みです。'),
          FilledButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('ホームへ'),
          ),
        ],
        const SizedBox(height: 16),
        TextButton(
          onPressed: _busy ? null : () => _run(_refresh),
          child: const Text('保存状態を再確認'),
        ),
      ],
    ),
  );
}
