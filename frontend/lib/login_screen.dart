import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'designsystem/action_button.dart';
import 'designsystem/app_card.dart';
import 'designsystem/authentication_field.dart';
import 'foundation/app_colors.dart';
import 'foundation/services/authentication_service.dart';
import 'home_screen.dart';

enum _Mode { login, register, reset, sent, verify }

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, this.authentication, this.onSignedIn});
  final AuthenticationService? authentication;
  final VoidCallback? onSignedIn;
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  late final _auth = widget.authentication ?? AuthenticationService();
  final _email = TextEditingController(), _password = TextEditingController();
  var _form = GlobalKey<FormState>();
  _Mode _mode = _Mode.login;
  bool _busy = true;
  String? _error, _notice;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    try {
      final session = await _auth.restore();
      if (!mounted) return;
      if (session != null) _accept(session);
    } catch (e) {
      if (mounted) _error = authenticationError(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _accept(AccountSession session) {
    _email.text = session.email;
    if (!session.verified) {
      setState(() => _mode = _Mode.verify);
      return;
    }
    TextInput.finishAutofillContext();
    _password.clear();
    final completed = widget.onSignedIn;
    if (completed != null) {
      completed();
    } else {
      Navigator.of(context).pushReplacement<void, void>(
        MaterialPageRoute(builder: (_) => const HomeScreen()),
      );
    }
  }

  void _switch(_Mode mode) {
    if (_busy) return;
    FocusScope.of(context).unfocus();
    _password.clear();
    _form = GlobalKey<FormState>();
    setState(() {
      _mode = mode;
      _error = _notice = null;
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = _notice = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) setState(() => _error = authenticationError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _submit() {
    if (_busy || !(_form.currentState?.validate() ?? false)) return;
    final email = _email.text.trim(), password = _password.text;
    _run(() async {
      if (_mode == _Mode.reset) {
        await _auth.resetPassword(email);
        if (mounted) setState(() => _mode = _Mode.sent);
      } else if (_mode == _Mode.register) {
        final session = await _auth.register(email, password);
        if (!mounted) return;
        _password.clear();
        _accept(session);
        if (!session.verified) {
          await _auth.sendVerification();
          if (mounted) setState(() => _notice = '確認メールを送りました。');
        }
      } else {
        final session = await _auth.login(email, password);
        if (mounted) _accept(session);
      }
    });
  }

  Widget _button(String label, VoidCallback action) =>
      ActionButton(label: label, onPressed: _busy ? null : action);

  Widget _message(
    String title,
    String body, {
    Color color = AppColors.surface,
  }) => AppCard(
    padding: 16,
    radius: 20,
    color: color,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            fontSize: 16,
            height: 1.5,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 8),
        Text(body, style: const TextStyle(fontSize: 14, height: 1.5)),
      ],
    ),
  );

  List<Widget> _contents() => switch (_mode) {
    _Mode.login || _Mode.register || _Mode.reset => [
      if (_mode == _Mode.register)
        _message('これからの旅を、一緒に', 'ガジェットと暮らして、スマホで旅を見守る。', color: AppColors.soft),
      AuthenticationField(
        label: 'メールアドレス',
        controller: _email,
        enabled: !_busy,
      ),
      if (_mode != _Mode.reset)
        AuthenticationField(
          label: 'パスワード',
          controller: _password,
          password: true,
          enabled: !_busy,
          onSubmitted: _submit,
        ),
      if (_mode == _Mode.reset) _message('メールで再設定できます', '再設定用のリンクをメールでお送りします。'),
      _button(switch (_mode) {
        _Mode.register => '新規登録して進む',
        _Mode.reset => '再設定メールを送る',
        _ => 'ログイン',
      }, _submit),
      if (_mode == _Mode.login) ...[
        _button('パスワードを忘れた方', () => _switch(_Mode.reset)),
        _button('新しく登録する', () => _switch(_Mode.register)),
      ] else
        _button('ログインに戻る', () => _switch(_Mode.login)),
    ],
    _Mode.sent => [
      _message(
        '受信箱を確認してください',
        '登録されている場合、再設定の案内が届きます。メールのリンクから新しいパスワードを設定してください。',
        color: AppColors.soft,
      ),
      _button('ログインへ戻る', () => _switch(_Mode.login)),
      _button('メールアドレスを確認', () => _switch(_Mode.reset)),
    ],
    _Mode.verify => [
      _message(
        'メール内のリンクで認証',
        '${_email.text}\nメール内のリンクを開いたら、アプリに戻って確認してください。',
        color: AppColors.soft,
      ),
      _button(
        '認証状態を確認する',
        () => _run(() async {
          final session = await _auth.refreshVerification();
          if (!mounted) return;
          if (session == null) {
            _mode = _Mode.login;
            _notice = 'もう一度ログインしてください。';
          } else if (session.verified) {
            _accept(session);
          } else {
            setState(() => _notice = 'まだメールの認証が完了していません。');
          }
        }),
      ),
      _button(
        '確認メールを再送する',
        () => _run(() async {
          await _auth.sendVerification();
          if (mounted) setState(() => _notice = '確認メールを再送しました。');
        }),
      ),
      _button('ログインに戻る', () => _switch(_Mode.login)),
      const Text(
        '迷惑メールフォルダもご確認ください。',
        style: TextStyle(fontSize: 12, height: 1.5, color: AppColors.muted),
      ),
    ],
  };

  @override
  Widget build(BuildContext context) {
    final title = switch (_mode) {
      _Mode.login => 'おかえりなさい',
      _Mode.register => 'はじめまして',
      _Mode.reset => 'パスワードの再設定',
      _Mode.sent => 'メールを送りました',
      _Mode.verify => 'メールを確認してください',
    };
    final subtitle = switch (_mode) {
      _Mode.login => 'メール / パスワードでログイン',
      _Mode.register => 'メールアドレスで、旅の記録をつなぎます。',
      _Mode.reset => 'ログインのお手伝い',
      _Mode.sent => 'パスワード再設定 / 送信後',
      _Mode.verify => '登録したメールアドレスの認証',
    };
    final children = <Widget>[
      const Text(
        'アカウント',
        style: TextStyle(fontSize: 11, height: 1.5, color: AppColors.muted),
      ),
      Text(
        title,
        style: const TextStyle(
          fontSize: 24,
          height: 1.5,
          fontWeight: FontWeight.bold,
        ),
      ),
      Text(
        subtitle,
        style: const TextStyle(
          fontSize: 14,
          height: 1.5,
          color: AppColors.muted,
        ),
      ),
      ..._contents(),
      if (_busy)
        Semantics(
          liveRegion: true,
          child: Text('確認中…', style: TextStyle(color: AppColors.muted)),
        ),
      if (_error != null)
        Semantics(
          liveRegion: true,
          child: _message(
            '手続きを完了できませんでした',
            _error!,
            color: AppColors.memoryBackground,
          ),
        ),
      if (_notice != null)
        Semantics(
          liveRegion: true,
          child: _message('お知らせ', _notice!, color: AppColors.soft),
        ),
    ];
    return Scaffold(
      body: SafeArea(
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: AutofillGroup(
              child: Form(
                key: _form,
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(24),
                  keyboardDismissBehavior:
                      ScrollViewKeyboardDismissBehavior.onDrag,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      for (var index = 0; index < children.length; index++) ...[
                        if (index > 0) const SizedBox(height: 14),
                        children[index],
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }
}
