// lib/data/repositories/users_repo.dart
// User management repository for Admin operations.
// Requirements: 2.8, 2.9, 2.10

import 'package:dio/dio.dart';
import '../models/user_model.dart';
import '../../core/api_client.dart';

class UsersRepo {
  final Dio _dio;
  UsersRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  /// Get list of all users.
  /// Requirement 2.x
  Future<List<UserModel>> listUsers() async {
    final res = await _dio.get(
      '/users',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    final data = _asList(res.data);
    return data.map((e) => UserModel.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Create a new user with username, password, and role.
  /// Requirement 2.8
  Future<UserModel> createUser({
    required String username,
    required String password,
    required String role,
  }) async {
    final res = await _dio.post(
      '/users',
      data: {
        'username': username,
        'password': password,
        'role': role,
      },
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return UserModel.fromJson(res.data as Map<String, dynamic>);
  }

  /// Update user role, disabled status, or password.
  /// Requirement 2.9
  Future<UserModel> updateUser(
    int id, {
    String? role,
    bool? disabled,
    String? password,
  }) async {
    final body = <String, dynamic>{};
    if (role != null) body['role'] = role;
    if (disabled != null) body['disabled'] = disabled;
    if (password != null) body['password'] = password;

    final res = await _dio.patch(
      '/users/$id',
      data: body,
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return UserModel.fromJson(res.data as Map<String, dynamic>);
  }

  /// Delete a user account.
  /// Requirement 2.10 - backend rejects deleting last Admin
  Future<void> deleteUser(int id) async {
    await _dio.delete(
      '/users/$id',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
  }
}

/// Accepts either a bare JSON array (new router) or a ``{ "data": [...] }``
/// envelope and returns the underlying list.
List<dynamic> _asList(dynamic body) {
  if (body is List) return body;
  if (body is Map && body['data'] is List) return body['data'] as List;
  return const [];
}
