// lib/data/repositories/alerts_repo.dart
// Alerts repository for watchlist match alerts.
// Requirements: 12.4, 12.6

import 'package:dio/dio.dart';
import '../models/alert.dart';
import '../../core/api_client.dart';

class AlertsRepo {
  final Dio _dio;
  AlertsRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  /// Get list of alerts ordered from most recent to least recent.
  /// Requirement 12.6
  Future<List<Alert>> listAlerts({int? limit}) async {
    final queryParams = <String, dynamic>{};
    if (limit != null) queryParams['limit'] = limit;

    final res = await _dio.get(
      '/alerts',
      queryParameters: queryParams,
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    // GET /api/alerts returns a JSON array (list[AlertView]).
    final data = _asList(res.data);
    return data.map((e) => Alert.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Get a single alert by ID (if endpoint exists).
  Future<Alert> getAlert(int id) async {
    final res = await _dio.get(
      '/alerts/$id',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return Alert.fromJson(res.data as Map<String, dynamic>);
  }
}

/// Accepts either a bare JSON array or a ``{ "data": [...] }`` envelope and
/// returns the underlying list.
List<dynamic> _asList(dynamic body) {
  if (body is List) return body;
  if (body is Map && body['data'] is List) return body['data'] as List;
  return const [];
}
