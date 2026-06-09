// lib/data/repositories/watchlists_repo.dart
// Watchlist management repository.
// Requirements: 12.1, 12.2, 12.3

import 'package:dio/dio.dart';
import '../models/watchlist.dart';
import '../models/watchlist_entry.dart';
import '../../core/api_client.dart';

class WatchlistsRepo {
  final Dio _dio;
  WatchlistsRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  /// Get list of all watchlists with their entries.
  /// Requirement 12.1
  Future<List<Watchlist>> listWatchlists() async {
    final res = await _dio.get(
      '/watchlists',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    // GET /api/watchlists returns a JSON array (list[WatchlistView]).
    final data = _asList(res.data);
    return data.map((e) => Watchlist.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Create a new watchlist.
  /// Requirement 12.1
  Future<Watchlist> createWatchlist({
    required String name,
    required String listType,
  }) async {
    final res = await _dio.post(
      '/watchlists',
      data: {
        'name': name,
        'list_type': listType,
      },
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return Watchlist.fromJson(res.data as Map<String, dynamic>);
  }

  /// Add an entry to a watchlist.
  /// Requirement 12.2
  Future<WatchlistEntry> addEntry({
    required int watchlistId,
    required String plateValue,
    String? label,
    String? reason,
  }) async {
    final body = <String, dynamic>{
      'plate_value': plateValue,
    };
    if (label != null) body['label'] = label;
    if (reason != null) body['reason'] = reason;

    final res = await _dio.post(
      '/watchlists/$watchlistId/entries',
      data: body,
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return WatchlistEntry.fromJson(res.data as Map<String, dynamic>);
  }

  /// Remove an entry from a watchlist.
  /// Requirement 12.3
  Future<void> deleteEntry(int entryId) async {
    await _dio.delete(
      '/watchlists/entries/$entryId',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
  }

  /// Delete a watchlist (if this endpoint exists).
  Future<void> deleteWatchlist(int watchlistId) async {
    await _dio.delete(
      '/watchlists/$watchlistId',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
  }
}

/// Accepts either a bare JSON array or a ``{ "data": [...] }`` envelope and
/// returns the underlying list, so the repo is tolerant of both shapes.
List<dynamic> _asList(dynamic body) {
  if (body is List) return body;
  if (body is Map && body['data'] is List) return body['data'] as List;
  return const [];
}
