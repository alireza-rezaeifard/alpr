// lib/data/controllers/audit_controller.dart
// Audit log controller for Admin viewing security-relevant actions.
// Requirements: 15.3, 15.4

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/audit_entry.dart';
import '../repositories/audit_repo.dart';

/// Audit log state.
class AuditState {
  final List<AuditEntry> entries;
  final bool loading;
  final String? error;

  const AuditState({
    this.entries = const [],
    this.loading = false,
    this.error,
  });

  AuditState copyWith({
    List<AuditEntry>? entries,
    bool? loading,
    String? error,
  }) =>
      AuditState(
        entries: entries ?? this.entries,
        loading: loading ?? this.loading,
        error: error,
      );
}

/// Audit log controller.
class AuditController extends StateNotifier<AuditState> {
  final AuditRepo _repo;

  AuditController(this._repo) : super(const AuditState());

  /// Load audit log entries ordered from most recent to least recent.
  /// limit > 0: return that many entries
  /// limit == 0: return all entries
  /// Requirements 15.3, 15.4
  Future<void> loadAuditLog({int limit = 100}) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final entries = await _repo.listAuditLog(limit: limit);
      state = state.copyWith(entries: entries, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Load all audit entries (no limit).
  Future<void> loadAllEntries() async {
    await loadAuditLog(limit: 0);
  }

  /// Refresh audit log.
  Future<void> refresh() async {
    await loadAuditLog();
  }
}

// Provider for AuditRepo
final auditRepoProvider = Provider((ref) => AuditRepo());

// Provider for AuditController
final auditControllerProvider =
    StateNotifierProvider<AuditController, AuditState>((ref) {
  final repo = ref.watch(auditRepoProvider);
  return AuditController(repo);
});
