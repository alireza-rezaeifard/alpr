// lib/data/controllers/watchlists_controller.dart
// Watchlist management controller.
// Requirements: 12.1, 12.2, 12.3

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/watchlist.dart';
import '../repositories/watchlists_repo.dart';

/// Watchlist management state.
class WatchlistsState {
  final List<Watchlist> watchlists;
  final bool loading;
  final String? error;

  const WatchlistsState({
    this.watchlists = const [],
    this.loading = false,
    this.error,
  });

  WatchlistsState copyWith({
    List<Watchlist>? watchlists,
    bool? loading,
    String? error,
  }) =>
      WatchlistsState(
        watchlists: watchlists ?? this.watchlists,
        loading: loading ?? this.loading,
        error: error,
      );
}

/// Watchlist management controller.
class WatchlistsController extends StateNotifier<WatchlistsState> {
  final WatchlistsRepo _repo;

  WatchlistsController(this._repo) : super(const WatchlistsState());

  /// Load all watchlists with their entries.
  Future<void> loadWatchlists() async {
    state = state.copyWith(loading: true, error: null);
    try {
      final watchlists = await _repo.listWatchlists();
      state = state.copyWith(watchlists: watchlists, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Create a new watchlist.
  /// Requirement 12.1
  Future<void> createWatchlist({
    required String name,
    required String listType,
  }) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final newWatchlist = await _repo.createWatchlist(
        name: name,
        listType: listType,
      );
      state = state.copyWith(
        watchlists: [...state.watchlists, newWatchlist],
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Add an entry to a watchlist.
  /// Requirement 12.2
  Future<void> addEntry({
    required int watchlistId,
    required String plateValue,
    String? label,
    String? reason,
  }) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final newEntry = await _repo.addEntry(
        watchlistId: watchlistId,
        plateValue: plateValue,
        label: label,
        reason: reason,
      );

      // Update the watchlist in state with the new entry
      state = state.copyWith(
        watchlists: state.watchlists.map((wl) {
          if (wl.id == watchlistId) {
            return wl.copyWith(entries: [...wl.entries, newEntry]);
          }
          return wl;
        }).toList(),
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Remove an entry from a watchlist.
  /// Requirement 12.3
  Future<void> deleteEntry(int entryId) async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.deleteEntry(entryId);

      // Update state by removing the entry
      state = state.copyWith(
        watchlists: state.watchlists.map((wl) {
          return wl.copyWith(
            entries: wl.entries.where((e) => e.id != entryId).toList(),
          );
        }).toList(),
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Delete a watchlist.
  Future<void> deleteWatchlist(int watchlistId) async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.deleteWatchlist(watchlistId);
      state = state.copyWith(
        watchlists: state.watchlists.where((wl) => wl.id != watchlistId).toList(),
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }
}

// Provider for WatchlistsRepo
final watchlistsRepoProvider = Provider((ref) => WatchlistsRepo());

// Provider for WatchlistsController
final watchlistsControllerProvider =
    StateNotifierProvider<WatchlistsController, WatchlistsState>((ref) {
  final repo = ref.watch(watchlistsRepoProvider);
  return WatchlistsController(repo);
});
