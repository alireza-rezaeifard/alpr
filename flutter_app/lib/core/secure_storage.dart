// lib/core/secure_storage.dart
// Simple in-memory token storage for Windows/Web platforms.
// In production, use flutter_secure_storage for native platforms.
// Requirements: 18.2, 18.3

/// Minimal token storage interface for session persistence.
/// Uses in-memory storage suitable for Windows and Web platforms.
class SecureStorage {
  static const _tokenKey = 'session_token';
  static String? _token;

  /// Store the session token
  static Future<void> writeToken(String token) async {
    _token = token;
  }

  /// Retrieve the stored session token
  static Future<String?> readToken() async {
    return _token;
  }

  /// Delete the stored session token (synchronous for immediate effect)
  static Future<void> deleteToken() async {
    _token = null;
  }

  /// Check if a token exists
  static Future<bool> hasToken() async {
    return _token != null && _token!.isNotEmpty;
  }
}
