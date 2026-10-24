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
  @override
  Future<UserCredential> linkWithCredential(AuthCredential credential) async {
    expect(credential.providerId, 'password');
    links++;
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
    },
  );
  test(
    'fresh registration creates an email account and restore ignores anonymous users',
    () async {
      final auth = TestAuth(TestUser());
      final service = AuthenticationService(
        prepare: () async {},
        auth: () => auth,
      );
      expect(await service.restore(), isNull);
      auth.currentUser = null;
      await service.register('you@example.com', 'password');
      expect(auth.creates, 1);
      expect((await service.restore())!.email, 'you@example.com');
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
