// lib/data/repositories/audit_repo.dart
// Audit log repository for security-relevant action records.
// Requirements: 15.3, 15.4

import 'package:dio/dio.dart';
import '../models/audit_entry.dart';
import '../../core/api_client.dart';

class AuditRepo {
  final Dio _dio;
  AuditRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  /// Get audit log entries ordered from most recent to least recent.
  /// limit > 0: return that many entries
  /// limit == 0: return all entries
  /// Requirements 15.3, 15.4
  Future<List<AuditEntry>> listAuditLog({int limit = 100}) async {
    final res = await _dio.get(
      '/audit',
      queryParameters: {'limit': limit},
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    final data = (res.data as Map)['data'] as List;
    return data.map((e) => AuditEntry.fromJson(e as Map<String, dynamic>)).toList();
  }
}
