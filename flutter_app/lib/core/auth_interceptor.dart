// lib/core/auth_interceptor.dart
// Dio interceptor that attaches Bearer token and handles 401 by clearing token.
// Requirements: 18.2, 18.3

import 'package:dio/dio.dart';
import 'secure_storage.dart';

/// Interceptor that adds Bearer token to requests and handles 401 responses.
///
/// On every request:
/// - Reads the stored token and attaches it as `Authorization: Bearer <token>`
///
/// On 401 response:
/// - Clears the stored token
/// - Sets a flag that triggers redirect to login (checked by router)
class AuthInterceptor extends Interceptor {
  /// Flag indicating that a 401 was received and auth state should be cleared.
  /// The router redirect guard will check this flag.
  static bool needsReauthentication = false;

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
    // On 401, clear token and set reauthentication flag
    if (err.response?.statusCode == 401) {
      await _handle401();
    }
    handler.next(err);
  }

  Future<void> _handle401() async {
    // Clear the stored token
    await SecureStorage.deleteToken();
    // Set flag for router to redirect to login
    needsReauthentication = true;
  }

  /// Reset the reauthentication flag (called after successful login)
  static void clearReauthFlag() {
    needsReauthentication = false;
  }
}
