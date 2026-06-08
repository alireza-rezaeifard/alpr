// test/core/auth_provider_test.dart
// Unit tests for auth and session providers.
// Requirements: 18.2, 18.3

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_app/core/auth_provider.dart';
import 'package:flutter_app/core/session_provider.dart';
import 'package:flutter_app/core/secure_storage.dart';
import 'package:flutter_app/data/models/user_auth.dart';

void main() {
  group('AuthState Provider', () {
    late ProviderContainer container;

    setUp(() {
      container = ProviderContainer();
      SecureStorage.deleteToken();
    });

    tearDown(() {
      container.dispose();
    });

    test('starts with null auth state when no token exists', () async {
      final auth = await container.read(authStateProvider.future);
      expect(auth, isNull);
    });

    test('login stores token and updates auth state', () async {
      final notifier = container.read(authStateProvider.notifier);

      final testAuth = UserAuth(
        token: 'test-token-123',
        role: 'Operator',
        expiresAt: DateTime.now().add(Duration(hours: 1)).toIso8601String(),
        permissions: ['view', 'manage_cameras', 'run_detection'],
      );

      await notifier.login(testAuth);

      // Verify token was stored
      expect(await SecureStorage.readToken(), 'test-token-123');

      // Verify auth state was updated
      final auth = container.read(authStateProvider).value;
      expect(auth, isNotNull);
      expect(auth?.token, 'test-token-123');
      expect(auth?.role, 'Operator');
    });

    test('logout clears token and auth state', () async {
      final notifier = container.read(authStateProvider.notifier);

      // First login
      final testAuth = UserAuth(
        token: 'test-token-123',
        role: 'Admin',
        expiresAt: DateTime.now().add(Duration(hours: 1)).toIso8601String(),
        permissions: ['view', 'manage_users'],
      );
      await notifier.login(testAuth);
      expect(await SecureStorage.hasToken(), isTrue);

      // Then logout
      await notifier.logout();

      // Verify token was cleared
      expect(await SecureStorage.hasToken(), isFalse);

      // Verify auth state is null
      final auth = container.read(authStateProvider).value;
      expect(auth, isNull);
    });

    test('isAuthenticated returns true when valid auth exists', () async {
      final notifier = container.read(authStateProvider.notifier);

      final testAuth = UserAuth(
        token: 'test-token',
        role: 'Viewer',
        expiresAt: DateTime.now().add(Duration(hours: 1)).toIso8601String(),
        permissions: ['view'],
      );
      await notifier.login(testAuth);

      final isAuth = container.read(isAuthenticatedProvider);
      expect(isAuth, isTrue);
    });

    test('isAuthenticated returns false when no auth exists', () {
      final isAuth = container.read(isAuthenticatedProvider);
      expect(isAuth, isFalse);
    });

    test('hasPermission checks user permissions correctly', () async {
      final notifier = container.read(authStateProvider.notifier);

      final testAuth = UserAuth(
        token: 'test-token',
        role: 'Operator',
        expiresAt: DateTime.now().add(Duration(hours: 1)).toIso8601String(),
        permissions: ['view', 'manage_cameras', 'run_detection'],
      );
      await notifier.login(testAuth);

      expect(
        container.read(hasPermissionProvider('manage_cameras')),
        isTrue,
      );
      expect(
        container.read(hasPermissionProvider('manage_users')),
        isFalse,
      );
    });
  });

  group('SessionInfo Provider', () {
    late ProviderContainer container;

    setUp(() {
      container = ProviderContainer();
      SecureStorage.deleteToken();
    });

    tearDown(() {
      container.dispose();
    });

    test('returns null when no auth exists', () {
      final session = container.read(sessionInfoProvider);
      expect(session, isNull);
    });

    test('returns session info when authenticated', () async {
      final notifier = container.read(authStateProvider.notifier);
      final expiresAt = DateTime.now().add(Duration(hours: 1));

      final testAuth = UserAuth(
        token: 'test-token',
        role: 'Admin',
        expiresAt: expiresAt.toIso8601String(),
        permissions: ['view', 'manage_users'],
      );
      await notifier.login(testAuth);

      final session = container.read(sessionInfoProvider);
      expect(session, isNotNull);
      expect(session?.role, 'Admin');
      expect(session?.permissions, ['view', 'manage_users']);
      expect(session?.isValid, isTrue);
    });

    test('detects expired sessions', () async {
      final notifier = container.read(authStateProvider.notifier);
      final expiresAt = DateTime.now().subtract(Duration(hours: 1));

      final testAuth = UserAuth(
        token: 'expired-token',
        role: 'Viewer',
        expiresAt: expiresAt.toIso8601String(),
        permissions: ['view'],
      );
      await notifier.login(testAuth);

      final session = container.read(sessionInfoProvider);
      expect(session, isNotNull);
      expect(session?.isValid, isFalse);
      expect(session?.isExpired, isTrue);
    });

    test('detects soon-to-expire sessions', () async {
      final notifier = container.read(authStateProvider.notifier);
      // Expires in 3 minutes (less than 5 minute threshold)
      final expiresAt = DateTime.now().add(Duration(minutes: 3));

      final testAuth = UserAuth(
        token: 'test-token',
        role: 'Operator',
        expiresAt: expiresAt.toIso8601String(),
        permissions: ['view'],
      );
      await notifier.login(testAuth);

      final isExpiringSoon = container.read(isSessionExpiringSoonProvider);
      expect(isExpiringSoon, isTrue);
    });

    test('calculates time remaining correctly', () async {
      final notifier = container.read(authStateProvider.notifier);
      final expiresAt = DateTime.now().add(Duration(minutes: 30));

      final testAuth = UserAuth(
        token: 'test-token',
        role: 'Viewer',
        expiresAt: expiresAt.toIso8601String(),
        permissions: ['view'],
      );
      await notifier.login(testAuth);

      final timeRemaining = container.read(sessionTimeRemainingProvider);
      // Should be approximately 30 minutes
      expect(timeRemaining.inMinutes, greaterThanOrEqualTo(29));
      expect(timeRemaining.inMinutes, lessThanOrEqualTo(30));
    });
  });
}
