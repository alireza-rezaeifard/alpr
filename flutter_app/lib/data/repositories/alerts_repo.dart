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
    final data = (res.data as Map)['data'] as List;
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
