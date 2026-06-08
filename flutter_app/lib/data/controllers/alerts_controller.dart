// lib/data/controllers/alerts_controller.dart
// Alerts controller for watchlist match alerts.
// Requirements: 12.4, 12.6

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/alert.dart';
import '../repositories/alerts_repo.dart';

/// Alerts state.
class AlertsState {
  final List<Alert> alerts;
  final bool loading;
  final String? error;

  const AlertsState({
    this.alerts = const [],
    this.loading = false,
    this.error,
  });

  AlertsState copyWith({
    List<Alert>? alerts,
    bool? loading,
    String? error,
  }) =>
      AlertsState(
        alerts: alerts ?? this.alerts,
        loading: loading ?? this.loading,
        error: error,
      );
}

/// Alerts controller.
class AlertsController extends StateNotifier<AlertsState> {
  final AlertsRepo _repo;

  AlertsController(this._repo) : super(const AlertsState());

  /// Load alerts ordered from most recent to least recent.
  /// Requirement 12.6
  Future<void> loadAlerts({int? limit}) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final alerts = await _repo.listAlerts(limit: limit);
      state = state.copyWith(alerts: alerts, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Refresh alerts (reload from server).
  Future<void> refresh() async {
    await loadAlerts();
  }
}

// Provider for AlertsRepo
final alertsRepoProvider = Provider((ref) => AlertsRepo());

// Provider for AlertsController
final alertsControllerProvider =
    StateNotifierProvider<AlertsController, AlertsState>((ref) {
  final repo = ref.watch(alertsRepoProvider);
  return AlertsController(repo);
});
