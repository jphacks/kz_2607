import 'dart:async';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/login_screen.dart';
import 'package:kz_2607/main.dart';
import 'package:kz_2607/foundation/services/authentication_service.dart';
import 'home_screen_test.dart' show loadHomeFont;

class FakeAuthentication extends AuthenticationService {
  AccountSession? restored;
  AccountSession result = const AccountSession(
    email: 'you@example.com',
    verified: true,
  );
  Object? failure, verificationFailure;
  Completer<void>? pending;
  int logins = 0, registrations = 0, resets = 0, verifications = 0;
  String? email, password;
  @override
  Future<AccountSession?> restore() async => restored;
  @override
  Future<AccountSession> login(String email, String password) async {
    logins++;
    this.email = email;
    this.password = password;
    await pending?.future;
    if (failure != null) throw failure!;
    return result;
  }

  @override
  Future<AccountSession> register(String email, String password) async {
    registrations++;
    this.email = email;
    return result;
  }

  @override
  Future<void> sendVerification() async {
    verifications++;
    if (verificationFailure != null) throw verificationFailure!;
  }

  @override
  Future<AccountSession?> refreshVerification() async => result;
  @override
  Future<void> resetPassword(String email) async {
    resets++;
    this.email = email;
    if (failure != null) throw failure!;
  }
}

void main() {
  setUpAll(loadHomeFont);
  Future<void> show(
    WidgetTester tester,
    FakeAuthentication auth, {
    VoidCallback? done,
  }) async {
    await tester.pumpWidget(
      MyApp(
        home: LoginScreen(authentication: auth, onSignedIn: done),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> input(WidgetTester tester) async {
    await tester.enterText(
      find.byType(TextFormField).first,
      ' you@example.com ',
    );
    await tester.enterText(find.byType(TextFormField).last, ' password ');
  }

  Future<void> tap(WidgetTester tester, String label) async {
    await tester.ensureVisible(find.text(label));
    await tester.tap(find.text(label));
    await tester.pumpAndSettle();
  }

  testWidgets('invalid inputs do not invoke authentication', (tester) async {
    final auth = FakeAuthentication();
    await show(tester, auth);
    await tap(tester, 'ログイン');
    expect(find.text('メールアドレスを入力してください。'), findsOneWidget);
    expect(find.text('パスワードを入力してください。'), findsOneWidget);
    await tester.enterText(find.byType(TextFormField).first, 'invalid');
    await tap(tester, 'ログイン');
    expect(find.text('メールアドレスの形式を確認してください。'), findsOneWidget);
    expect(auth.logins, 0);
  });
  testWidgets(
    'login trims email but preserves password and suppresses duplicate requests',
    (tester) async {
      final auth = FakeAuthentication()..pending = Completer<void>();
      var completed = 0;
      await show(tester, auth, done: () => completed++);
      await input(tester);
      await tap(tester, 'ログイン');
      await tap(tester, 'ログイン');
      expect(auth.logins, 1);
      expect(auth.email, 'you@example.com');
      expect(auth.password, ' password ');
      expect(completed, 0);
      auth.pending!.complete();
      await tester.pumpAndSettle();
      expect(completed, 1);
    },
  );
  testWidgets('failed login retains values and allows retry', (tester) async {
    final auth = FakeAuthentication()
      ..failure = FirebaseAuthException(code: 'invalid-credential');
    await show(tester, auth);
    await input(tester);
    await tap(tester, 'ログイン');
    expect(find.text('メールアドレスとパスワードを確認してください。'), findsOneWidget);
    expect(
      tester
          .widget<TextFormField>(find.byType(TextFormField).last)
          .controller!
          .text,
      ' password ',
    );
    auth.failure = null;
    await tap(tester, 'ログイン');
    expect(find.text('いま、一緒にいる子'), findsOneWidget);
    expect(find.byType(LoginScreen), findsNothing);
  });
  testWidgets(
    'verified persisted session goes home; unverified session stays at verification',
    (tester) async {
      final auth = FakeAuthentication()
        ..restored = const AccountSession(
          email: 'you@example.com',
          verified: false,
        );
      var completed = 0;
      await show(tester, auth, done: () => completed++);
      expect(find.text('メールを確認してください'), findsOneWidget);
      expect(completed, 0);
      await tap(tester, '認証状態を確認する');
      expect(completed, 1);
    },
  );
  testWidgets(
    'verified restored session bypasses login without a new sign-in',
    (tester) async {
      final auth = FakeAuthentication()
        ..restored = const AccountSession(
          email: 'you@example.com',
          verified: true,
        );
      var completed = 0;
      await show(tester, auth, done: () => completed++);
      expect(completed, 1);
      expect(auth.logins, 0);
    },
  );
  testWidgets(
    'registration keeps account after verification mail failure and permits resend',
    (tester) async {
      final auth = FakeAuthentication()
        ..result = const AccountSession(
          email: 'you@example.com',
          verified: false,
        )
        ..verificationFailure = FirebaseAuthException(
          code: 'network-request-failed',
        );
      await show(tester, auth);
      await tap(tester, '新しく登録する');
      await input(tester);
      await tap(tester, '新規登録して進む');
      expect(find.text('メールを確認してください'), findsOneWidget);
      expect(auth.registrations, 1);
      auth.verificationFailure = null;
      await tap(tester, '確認メールを再送する');
      expect(auth.verifications, 2);
      expect(auth.registrations, 1);
      await tap(tester, '認証状態を確認する');
      expect(find.text('まだメールの認証が完了していません。'), findsOneWidget);
    },
  );
  testWidgets('password reset does not claim success on network failure', (
    tester,
  ) async {
    final auth = FakeAuthentication()
      ..failure = FirebaseAuthException(code: 'network-request-failed');
    await show(tester, auth);
    await tester.enterText(find.byType(TextFormField).first, 'you@example.com');
    await tap(tester, 'パスワードを忘れた方');
    await tap(tester, '再設定メールを送る');
    expect(find.text('メールを送りました'), findsNothing);
    auth.failure = null;
    await tap(tester, '再設定メールを送る');
    expect(find.text('メールを送りました'), findsOneWidget);
    expect(auth.email, 'you@example.com');
    await tap(tester, 'ログインへ戻る');
    expect(find.text('おかえりなさい'), findsOneWidget);
  });
  testWidgets('login is scrollable at large text sizes with keyboard inset', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    tester.view.viewInsets = const FakeViewPadding(bottom: 240);
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.reset);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await show(tester, FakeAuthentication());
    await input(tester);
    await tap(tester, '新しく登録する');
    expect(find.text('はじめまして'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('login visual preview', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await show(tester, FakeAuthentication());
    await expectLater(
      find.byType(MyApp),
      matchesGoldenFile('login_preview.png'),
    );
  });
}
