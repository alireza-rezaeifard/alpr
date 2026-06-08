// lib/data/controllers/users_controller.dart
// User management controller for Admin operations.
// Requirements: 2.8, 2.9, 2.10

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/user_model.dart';
import '../repositories/users_repo.dart';

/// User management state.
class UsersState {
  final List<UserModel> users;
  final bool loading;
  final String? error;

  const UsersState({
    this.users = const [],
    this.loading = false,
    this.error,
  });

  UsersState copyWith({
    List<UserModel>? users,
    bool? loading,
    String? error,
  }) =>
      UsersState(
        users: users ?? this.users,
        loading: loading ?? this.loading,
        error: error,
      );
}

/// User management controller.
class UsersController extends StateNotifier<UsersState> {
  final UsersRepo _repo;

  UsersController(this._repo) : super(const UsersState());

  /// Load all users.
  Future<void> loadUsers() async {
    state = state.copyWith(loading: true, error: null);
    try {
      final users = await _repo.listUsers();
      state = state.copyWith(users: users, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Create a new user.
  /// Requirement 2.8
  Future<void> createUser({
    required String username,
    required String password,
    required String role,
  }) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final newUser = await _repo.createUser(
        username: username,
        password: password,
        role: role,
      );
      state = state.copyWith(
        users: [...state.users, newUser],
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Update a user.
  /// Requirement 2.9
  Future<void> updateUser(
    int id, {
    String? role,
    bool? disabled,
    String? password,
  }) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final updatedUser = await _repo.updateUser(
        id,
        role: role,
        disabled: disabled,
        password: password,
      );
      state = state.copyWith(
        users: state.users
            .map((u) => u.id == id ? updatedUser : u)
            .toList(),
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Delete a user.
  /// Requirement 2.10 - backend prevents deleting last Admin
  Future<void> deleteUser(int id) async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.deleteUser(id);
      state = state.copyWith(
        users: state.users.where((u) => u.id != id).toList(),
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }
}

// Provider for UsersRepo
final usersRepoProvider = Provider((ref) => UsersRepo());

// Provider for UsersController
final usersControllerProvider =
    StateNotifierProvider<UsersController, UsersState>((ref) {
  final repo = ref.watch(usersRepoProvider);
  return UsersController(repo);
});
