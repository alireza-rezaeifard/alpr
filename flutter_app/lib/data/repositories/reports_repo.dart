// lib/data/repositories/reports_repo.dart
// Reports and analytics repository.
// Requirements: 13.1-13.7, 14.1-14.4

import 'package:dio/dio.dart';
import '../../core/api_client.dart';

/// Retention policy configuration.
class RetentionConfig {
  final int? days;

  const RetentionConfig({this.days});

  factory RetentionConfig.fromJson(Map<String, dynamic> json) =>
      RetentionConfig(
        days: json['days'] as int?,
      );

  Map<String, dynamic> toJson() => {
        'days': days,
      };
}

class ReportsRepo {
  final Dio _dio;
  ReportsRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  /// Export detections as CSV file.
  /// Returns raw bytes of the CSV file.
  /// Requirements 14.1-14.4
  Future<List<int>> exportDetections({
    String? sourceType,
    String? search,
  }) async {
    final queryParams = <String, dynamic>{};
    if (sourceType != null) queryParams['source_type'] = sourceType;
    if (search != null) queryParams['search'] = search;

    final res = await _dio.get(
      '/export/detections',
      queryParameters: queryParams,
      options: Options(
        responseType: ResponseType.bytes,
        receiveTimeout: ApiClient.uploadTimeout,
      ),
    );
    return res.data as List<int>;
  }

  /// Get retention policy configuration.
  /// Requirement 16.x
  Future<RetentionConfig> getRetentionPolicy() async {
    final res = await _dio.get(
      '/config/retention',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return RetentionConfig.fromJson(res.data as Map<String, dynamic>);
  }

  /// Set retention policy (days > 0).
  /// Requirement 16.1
  Future<RetentionConfig> setRetentionPolicy(int days) async {
    final res = await _dio.put(
      '/config/retention',
      data: {'days': days},
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return RetentionConfig.fromJson(res.data as Map<String, dynamic>);
  }

  /// Trigger manual pruning of old detections.
  Future<void> pruneDetections() async {
    await _dio.post(
      '/retention/prune',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
  }
}
