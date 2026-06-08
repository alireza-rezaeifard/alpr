// lib/core/session_provider.dart
// Session management provider for tracking active user session.
// Requirements: 18.2, 18.3

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'auth_provider.dart';

part 'session_provider.g.dart';

/// Session information derived from auth state
class SessionInfo {
  final String role;
  final List<String> permissions;
  final DateTime expiresAt;
  final bool isExpired;

  const SessionInfo({
    required this.role,
    required this.permissions,
    required this.expiresAt,
    required this.isExpired,
  });

  /// Check if session is still valid (not expired)
  bool get isValid => !isExpired && DateTime.now().isBefore(expiresAt);

  /// Time remaining until expiry
  Duration get timeRemaining {
    if (isExpired) return Duration.zero;
    return expiresAt.difference(DateTime.now());
  }

  /// Check if session will expire soon (within 5 minutes)
  bool get isExpiringSoon {
    return isValid && timeRemaining.inMinutes < 5;
  }
}

/// Provider that tracks the current session state.
/// Returns SessionInfo if a valid session exists, null otherwise.
@riverpod
SessionInfo? sessionInfo(Ref ref) {
  final auth = ref.watch(currentAuthProvider);
  if (auth == null) return null;

  final expiresAt = DateTime.tryParse(auth.expiresAt);
  if (expiresAt == null) return null;

  return SessionInfo(
    role: auth.role,
    permissions: auth.permissions,
    expiresAt: expiresAt,
    isExpired: auth.isExpired,
  );
}

/// Provider for checking if session is valid
@riverpod
bool isSessionValid(Ref ref) {
  final session = ref.watch(sessionInfoProvider);
  return session?.isValid ?? false;
}

/// Provider for checking if session is expiring soon
@riverpod
bool isSessionExpiringSoon(Ref ref) {
  final session = ref.watch(sessionInfoProvider);
  return session?.isExpiringSoon ?? false;
}

/// Provider for session time remaining
@riverpod
Duration sessionTimeRemaining(Ref ref) {
  final session = ref.watch(sessionInfoProvider);
  return session?.timeRemaining ?? Duration.zero;
}
