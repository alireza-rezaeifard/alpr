// lib/data/controllers/auth_controller.dart
// Authentication state controller using Riverpod.
// Requirements: 1.1, 1.7, 18.2, 18.3

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/user_auth.dart';
import '../repositories/auth_repo.dart';
import '../../core/secure_storage.dart';
import '../../core/auth_interceptor.dart';

/// Authentication state.
class AuthState {
  final UserAuth? session;
  final bool loading;
  final String? error;

  const AuthState({
    this.session,
    this.loading = false,
    this.error,
  });

  bool get isAuthenticated => session != null && !session!.isExpired;

  AuthState copyWith({
    UserAuth? session,
    bool? loading,
    String? error,
  }) =>
      AuthState(
        session: session ?? this.session,
        loading: loading ?? this.loading,
        error: error,
      );

  AuthState clearSession() => const AuthState();
}

/// Authentication controller managing login/logout state.
class AuthController extends StateNotifier<AuthState> {
  final AuthRepo _repo;

  AuthController(this._repo) : super(const AuthState()) {
    _loadStoredSession();
  }

  /// Load stored session on startup.
  Future<void> _loadStoredSession() async {
    final token = await SecureStorage.readToken();
    if (token != null) {
      // Token exists, but we need full session info
      // For now, just mark as authenticated
      // In a real implementation, validate token with backend
      try {
        final userInfo = await _repo.me();
        final session = UserAuth(
          token: token,
          role: userInfo['role'] as String,
          expiresAt: userInfo['expires_at'] as String? ?? '',
          permissions: (userInfo['permissions'] as List?)?.cast<String>() ?? [],
        );
        if (!session.isExpired) {
          state = AuthState(session: session);
        } else {
          await _clearStorage();
        }
      } catch (_) {
        await _clearStorage();
      }
    }
  }

  /// Login with username and password.
  /// Requirement 1.1, 18.2
  Future<void> login(String username, String password) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final session = await _repo.login(username, password);
      await _storeSession(session);
      AuthInterceptor.clearReauthFlag();
      state = AuthState(session: session);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Logout and invalidate session.
  /// Requirement 1.7, 18.3
  Future<void> logout() async {
    try {
      await _repo.logout();
    } catch (_) {
      // Continue logout even if backend call fails
    } finally {
      await _clearStorage();
      state = const AuthState();
    }
  }

  /// Clear session (called on 401 responses).
  /// Requirement 18.3
  Future<void> clearSession() async {
    await _clearStorage();
    state = const AuthState();
  }

  Future<void> _storeSession(UserAuth session) async {
    await SecureStorage.writeToken(session.token);
  }

  Future<void> _clearStorage() async {
    await SecureStorage.deleteToken();
  }
}

// Provider for AuthRepo
final authRepoProvider = Provider((ref) => AuthRepo());

// Provider for AuthController
final authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
  final repo = ref.watch(authRepoProvider);
  return AuthController(repo);
});

// Convenience provider for checking authentication
final isAuthenticatedProvider = Provider<bool>((ref) {
  return ref.watch(authControllerProvider).isAuthenticated;
});

// Convenience provider for current session
final currentSessionProvider = Provider<UserAuth?>((ref) {
  return ref.watch(authControllerProvider).session;
});
