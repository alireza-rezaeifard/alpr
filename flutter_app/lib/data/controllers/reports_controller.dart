// lib/data/controllers/reports_controller.dart
// Reports and settings controller for analytics export and retention.
// Requirements: 14.1-14.4, 16.1-16.4

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../repositories/reports_repo.dart';

/// Reports and settings state.
class ReportsState {
  final RetentionConfig? retentionConfig;
  final bool loading;
  final String? error;

  const ReportsState({
    this.retentionConfig,
    this.loading = false,
    this.error,
  });

  ReportsState copyWith({
    RetentionConfig? retentionConfig,
    bool? loading,
    String? error,
  }) =>
      ReportsState(
        retentionConfig: retentionConfig ?? this.retentionConfig,
        loading: loading ?? this.loading,
        error: error,
      );
}

/// Reports and settings controller.
class ReportsController extends StateNotifier<ReportsState> {
  final ReportsRepo _repo;

  ReportsController(this._repo) : super(const ReportsState());

  /// Export detections as CSV file.
  /// Requirements 14.1-14.4
  Future<List<int>> exportDetections({
    String? sourceType,
    String? search,
  }) async {
    return await _repo.exportDetections(
      sourceType: sourceType,
      search: search,
    );
  }

  /// Load retention policy configuration.
  Future<void> loadRetentionPolicy() async {
    state = state.copyWith(loading: true, error: null);
    try {
      final config = await _repo.getRetentionPolicy();
      state = state.copyWith(retentionConfig: config, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Set retention policy.
  /// Requirement 16.1
  Future<void> setRetentionPolicy(int days) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final config = await _repo.setRetentionPolicy(days);
      state = state.copyWith(retentionConfig: config, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Trigger manual pruning of old detections.
  Future<void> pruneDetections() async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.pruneDetections();
      state = state.copyWith(loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }
}

// Provider for ReportsRepo
final reportsRepoProvider = Provider((ref) => ReportsRepo());

// Provider for ReportsController
final reportsControllerProvider =
    StateNotifierProvider<ReportsController, ReportsState>((ref) {
  final repo = ref.watch(reportsRepoProvider);
  return ReportsController(repo);
});
