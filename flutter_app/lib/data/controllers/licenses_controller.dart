// lib/data/controllers/licenses_controller.dart
// License management controller.
// Requirements: 3.1, 3.2, 3.5

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/license_status.dart';
import '../repositories/licenses_repo.dart';

/// License management state.
class LicensesState {
  final LicenseStatus? status;
  final bool loading;
  final String? error;

  const LicensesState({
    this.status,
    this.loading = false,
    this.error,
  });

  LicensesState copyWith({
    LicenseStatus? status,
    bool? loading,
    String? error,
  }) =>
      LicensesState(
        status: status ?? this.status,
        loading: loading ?? this.loading,
        error: error,
      );
}

/// License management controller.
class LicensesController extends StateNotifier<LicensesState> {
  final LicensesRepo _repo;

  LicensesController(this._repo) : super(const LicensesState());

  /// Load current license status.
  /// Requirement 3.5
  Future<void> loadStatus() async {
    state = state.copyWith(loading: true, error: null);
    try {
      final status = await _repo.getLicenseStatus();
      state = state.copyWith(status: status, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Activate a license key.
  /// Requirements 3.1, 3.2
  Future<void> activateLicense(String licenseKey) async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.activateLicense(licenseKey);
      // Reload status after activation
      final status = await _repo.getLicenseStatus();
      state = state.copyWith(status: status, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }
}

// Provider for LicensesRepo
final licensesRepoProvider = Provider((ref) => LicensesRepo());

// Provider for LicensesController
final licensesControllerProvider =
    StateNotifierProvider<LicensesController, LicensesState>((ref) {
  final repo = ref.watch(licensesRepoProvider);
  return LicensesController(repo);
});
