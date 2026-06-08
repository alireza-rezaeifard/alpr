// lib/core/auth_provider.dart
// Riverpod providers for authentication state management.
// Requirements: 18.2, 18.3

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';
import '../data/models/user_auth.dart';
import 'secure_storage.dart';
import 'auth_interceptor.dart';

part 'auth_provider.g.dart';

/// Provider that holds the current authentication state.
/// Returns UserAuth if authenticated, null if not.
///
/// This is the source of truth for authentication state across the app.
@riverpod
class AuthState extends _$AuthState {
  @override
  Future<UserAuth?> build() async {
    // On startup, check if we have a stored token
    final token = await SecureStorage.readToken();
    if (token == null) return null;

    // If token exists, try to reconstruct auth from it
    // In a real app, you might validate the token with the backend here
    // For now, we'll just check if it's expired
    try {
      // We'd need to decode the JWT to check expiry
      // For now, assume it's valid if it exists
      // The 401 interceptor will clear it if invalid
      return null; // Will be set properly after login
    } catch (_) {
      await SecureStorage.deleteToken();
      return null;
    }
  }

  /// Login with username and password
  Future<void> login(UserAuth auth) async {
    // Store the token
    await SecureStorage.writeToken(auth.token);
    // Clear the reauthentication flag
    AuthInterceptor.clearReauthFlag();
    // Update state
    state = AsyncValue.data(auth);
  }

  /// Logout - clear token and auth state
  Future<void> logout() async {
    await SecureStorage.deleteToken();
    state = const AsyncValue.data(null);
  }

  /// Check if user is authenticated
  bool get isAuthenticated {
    return state.value != null && !(state.value?.isExpired ?? true);
  }

  /// Get current user's role
  String? get role => state.value?.role;

  /// Check if user has a specific permission
  bool hasPermission(String permission) {
    return state.value?.hasPermission(permission) ?? false;
  }
}

/// Convenience provider for checking authentication status
@riverpod
bool isAuthenticated(Ref ref) {
  final authState = ref.watch(authStateProvider);
  return authState.when(
    data: (auth) => auth != null && !auth.isExpired,
    loading: () => false,
    error: (_, __) => false,
  );
}

/// Convenience provider for current user auth
@riverpod
UserAuth? currentAuth(Ref ref) {
  final authState = ref.watch(authStateProvider);
  return authState.value;
}

/// Provider for checking if user has a specific permission
@riverpod
bool hasPermission(Ref ref, String permission) {
  final auth = ref.watch(currentAuthProvider);
  return auth?.hasPermission(permission) ?? false;
}
