import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kz_2607/foundation/services/authentication_service.dart';

class TestUser extends Fake implements User {
  TestUser({this.isAnonymous = true});
  @override
  bool isAnonymous;
  @override
  bool emailVerified = false;
  @override
  String get email => 'you@example.com';
  @override
  String get uid => 'original-uid';
  int links = 0, tokenRefreshes = 0;
  Object? linkError;
  Object? tokenError;
  @override
  Future<UserCredential> linkWithCredential(AuthCredential credential) async {
    expect(credential.providerId, 'password');
    links++;
    if (linkError != null) throw linkError!;
    isAnonymous = false;
    return TestCredential(this);
  }

  @override
  Future<void> reload() async {
    emailVerified = true;
  }

  @override
  Future<String?> getIdToken([bool forceRefresh = false]) async {
    if (forceRefresh) tokenRefreshes++;
    if (tokenError != null) throw tokenError!;
    return 'test-token';
  }
}

class TestCredential extends Fake implements UserCredential {
  TestCredential(this.user);
  @override
  final User user;
}

class TestAuth extends Fake implements FirebaseAuth {
  TestAuth(this.currentUser);
  @override
  TestUser? currentUser;
  int creates = 0;
  int anonymousLogins = 0, emailLogins = 0;
  Object? loginError;
  @override
  Future<UserCredential> signInAnonymously() async {
    anonymousLogins++;
    return TestCredential(currentUser = TestUser());
  }

  @override
  Future<UserCredential> signInWithEmailAndPassword({
    required String email,
    required String password,
  }) async {
    emailLogins++;
    if (loginError != null) throw loginError!;
    return TestCredential(currentUser = TestUser(isAnonymous: false));
  }

  @override
  Future<UserCredential> createUserWithEmailAndPassword({
    required String email,
    required String password,
  }) async {
    creates++;
    return TestCredential(currentUser = TestUser(isAnonymous: false));
  }
}

void main() {
  test(
    'startup creates one anonymous session and reuses it on subsequent restores',
    () async {
      final auth = TestAuth(null);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      expect(await service.restore(), isNull);
      final original = auth.currentUser;
      expect(await service.restore(), isNull);
      expect(auth.anonymousLogins, 1);
      expect(auth.currentUser, same(original));
    },
  );
  test(
    'startup preserves an existing email session without anonymous sign-in',
    () async {
      final user = TestUser(isAnonymous: false);
      final auth = TestAuth(user);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      expect((await service.restore())!.email, user.email);
      expect(auth.anonymousLogins, 0);
      expect(auth.currentUser, same(user));
    },
  );
  test(
    'failed token refresh retains linked identity without another login',
    () async {
      final user = TestUser()
        ..tokenError = FirebaseAuthException(code: 'network-request-failed');
      final auth = TestAuth(user);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      await expectLater(
        service.register('you@example.com', 'password'),
        throwsA(isA<FirebaseAuthException>()),
      );
      expect(auth.currentUser, same(user));
      expect(user.isAnonymous, false);
      expect(user.links, 1);
      expect(auth.emailLogins, 0);
    },
  );
  test(
    'registration upgrades anonymous identity instead of creating a new UID',
    () async {
      final original = TestUser();
      final auth = TestAuth(original);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      final session = await service.register('you@example.com', 'password');
      expect(original.links, 1);
      expect(auth.creates, 0);
      expect(auth.currentUser, same(original));
      expect(auth.currentUser!.uid, 'original-uid');
      expect(session.verified, false);
      expect(original.tokenRefreshes, 1);
    },
  );
  test(
    'fresh registration signs in anonymously then links email credentials',
    () async {
      final auth = TestAuth(TestUser());
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      expect(await service.restore(), isNull);
      auth.currentUser = null;
      await service.register('you@example.com', 'password');
      expect(auth.creates, 0);
      expect(auth.anonymousLogins, 1);
      expect(auth.currentUser!.links, 1);
      expect((await service.restore())!.email, 'you@example.com');
    },
  );
  test(
    'existing email signs in with password instead of replacing ownership',
    () async {
      final anonymous = TestUser()
        ..linkError = FirebaseAuthException(code: 'email-already-in-use');
      final auth = TestAuth(anonymous);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      await service.register('you@example.com', 'password');
      expect(auth.emailLogins, 1);
      expect(auth.creates, 0);
      expect(auth.currentUser, isNot(same(anonymous)));
    },
  );
  test(
    'failed existing-email login preserves anonymous user and reports failure',
    () async {
      final anonymous = TestUser()
        ..linkError = FirebaseAuthException(code: 'email-already-in-use');
      final auth = TestAuth(anonymous)
        ..loginError = FirebaseAuthException(code: 'invalid-credential');
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      await expectLater(
        service.register('you@example.com', 'wrong'),
        throwsA(isA<FirebaseAuthException>()),
      );
      expect(auth.currentUser, same(anonymous));
      expect(auth.creates, 0);
    },
  );
  test(
    'network failure while linking never falls back to email login',
    () async {
      final anonymous = TestUser()
        ..linkError = FirebaseAuthException(code: 'network-request-failed');
      final auth = TestAuth(anonymous);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      await expectLater(
        service.register('you@example.com', 'password'),
        throwsA(isA<FirebaseAuthException>()),
      );
      expect(auth.emailLogins, 0);
      expect(auth.currentUser, same(anonymous));
    },
  );
  test(
    'registration never replaces an already signed-in email account',
    () async {
      final user = TestUser(isAnonymous: false);
      final auth = TestAuth(user);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      await expectLater(
        service.register('new@example.com', 'password'),
        throwsA(isA<FirebaseAuthException>()),
      );
      expect(auth.currentUser, same(user));
      expect(auth.creates, 0);
      expect(auth.anonymousLogins, 0);
    },
  );
  test(
    'verification reloads user and refreshes callable authentication token',
    () async {
      final user = TestUser(isAnonymous: false);
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => TestAuth(user),
      );
      expect((await service.refreshVerification())!.verified, true);
      expect(user.tokenRefreshes, 1);
    },
  );
}
