// lib/core/auth_interceptor.dart
// Dio interceptor that attaches Bearer token and handles 401 by clearing token.
// Requirements: 18.2, 18.3

import 'package:flutter/foundation.dart';
import 'package:dio/dio.dart';
import 'secure_storage.dart';

/// Interceptor that adds Bearer token to requests and handles 401 responses.
///
/// On every request:
/// - Reads the stored token and attaches it as `Authorization: Bearer <token>`
///
/// On 401 response:
/// - Clears the stored token
/// - Flips [reauthNotifier], which the router's `refreshListenable` observes so
///   the redirect guard re-evaluates and sends the user back to `/login`.
class AuthInterceptor extends Interceptor {
  /// Reactive signal that a 401 was received and re-authentication is required.
  ///
  /// The go_router configuration merges this into its `refreshListenable` so a
  /// 401 during any request (e.g. loading cameras) immediately triggers a
  /// redirect to the login screen.
  static final ValueNotifier<bool> reauthNotifier = ValueNotifier<bool>(false);

  /// Whether the most recent activity requires re-authentication.
  /// Backed by [reauthNotifier] so reads/writes stay reactive for the router.
  static bool get needsReauthentication => reauthNotifier.value;
  static set needsReauthentication(bool value) => reauthNotifier.value = value;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    // Attach the Bearer token if one exists
    final token = await SecureStorage.readToken();
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    // On 401, clear token and raise the reauthentication signal
    if (err.response?.statusCode == 401) {
      await _handle401();
    }
    handler.next(err);
  }

  Future<void> _handle401() async {
    // Clear the stored token
    await SecureStorage.deleteToken();
    // Raise the signal for the router to redirect to login
    reauthNotifier.value = true;
  }

  /// Reset the reauthentication flag (called after successful login)
  static void clearReauthFlag() {
    reauthNotifier.value = false;
  }
}
