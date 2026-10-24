import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';

class AccountSession {
  const AccountSession({required this.email, required this.verified});
  final String email;
  final bool verified;
}

/// Keeps Firebase authentication out of the screen and reuses persisted UIDs.
class AuthenticationService {
  AuthenticationService({
    Future<void> Function()? prepare,
    FirebaseAuth Function()? auth,
  }) : _prepare = prepare ?? _initialize,
       _auth = auth ?? (() => FirebaseAuth.instance);
  final Future<void> Function() _prepare;
  final FirebaseAuth Function() _auth;
  static Future<void> _initialize() async {
    if (Firebase.apps.isEmpty) await Firebase.initializeApp();
  }

  AccountSession? _session(User? user) => user == null || user.isAnonymous
      ? null
      : AccountSession(email: user.email ?? '', verified: user.emailVerified);

  Future<AccountSession?> restore() async {
    await _prepare();
    return _session(_auth().currentUser);
  }

  Future<AccountSession> login(String email, String password) async {
    await _prepare();
    final result = await _auth().signInWithEmailAndPassword(
      email: email,
      password: password,
    );
    return _session(result.user)!;
  }

  Future<AccountSession> register(String email, String password) async {
    await _prepare();
    final auth = _auth();
    final current = auth.currentUser;
    // Linking preserves ownership of devices already registered anonymously.
    final result = current?.isAnonymous == true
        ? await current!.linkWithCredential(
            EmailAuthProvider.credential(email: email, password: password),
          )
        : await auth.createUserWithEmailAndPassword(
            email: email,
            password: password,
          );
    return _session(result.user)!;
  }

  Future<void> sendVerification() async {
    await _prepare();
    final user = _auth().currentUser;
    if (user == null || user.isAnonymous) {
      throw StateError('ログインし直してください');
    }
    await user.sendEmailVerification();
  }

  Future<AccountSession?> refreshVerification() async {
    await _prepare();
    await _auth().currentUser?.reload();
    final user = _auth().currentUser;
    if (user?.emailVerified == true) await user!.getIdToken(true);
    return _session(user);
  }

  Future<void> resetPassword(String email) async {
    await _prepare();
    try {
      await _auth().sendPasswordResetEmail(email: email);
    } on FirebaseAuthException catch (e) {
      // Do not disclose whether an email address is registered.
      if (e.code != 'user-not-found') rethrow;
    }
  }
}

String authenticationError(Object error) {
  if (error is FirebaseAuthException) {
    return switch (error.code) {
      'invalid-email' => 'メールアドレスの形式を確認してください。',
      'invalid-credential' ||
      'wrong-password' ||
      'user-not-found' => 'メールアドレスとパスワードを確認してください。',
      'email-already-in-use' ||
      'credential-already-in-use' => 'このメールアドレスは登録済みです。ログインしてください。',
      'weak-password' => 'パスワードが登録条件を満たしていません。別のパスワードをお試しください。',
      'network-request-failed' => '通信できません。接続を確認して、もう一度お試しください。',
      'too-many-requests' => '操作が集中しています。しばらく待ってからお試しください。',
      'user-disabled' => 'このアカウントは利用できません。',
      'operation-not-allowed' => 'メール・パスワード認証が有効になっていません。管理者に確認してください。',
      _ => '認証できませんでした。もう一度お試しください。',
    };
  }
  return '認証の準備ができませんでした。通信状態とFirebase設定を確認してください。';
}
