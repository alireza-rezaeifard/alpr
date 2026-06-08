// lib/data/repositories/auth_repo.dart
// Authentication repository wrapping auth endpoints.
// Requirements: 1.1, 1.2, 1.7, 1.8

import 'package:dio/dio.dart';
import '../models/user_auth.dart';
import '../../core/api_client.dart';

class AuthRepo {
  final Dio _dio;
  AuthRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  /// Login with username and password.
  /// Returns UserAuth with session token and permissions.
  /// Requirement 1.1
  Future<UserAuth> login(String username, String password) async {
    final res = await _dio.post(
      '/auth/login',
      data: {'username': username, 'password': password},
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return UserAuth.fromJson(res.data as Map<String, dynamic>);
  }

  /// Logout and invalidate the current session token.
  /// Requirement 1.7
  Future<void> logout() async {
    await _dio.post(
      '/auth/logout',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
  }

  /// Get current authenticated user info.
  /// Requirement 1.4
  Future<Map<String, dynamic>> me() async {
    final res = await _dio.get(
      '/auth/me',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return res.data as Map<String, dynamic>;
  }
}
