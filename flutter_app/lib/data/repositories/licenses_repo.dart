// lib/data/repositories/licenses_repo.dart
// License management repository.
// Requirements: 3.1, 3.2, 3.5

import 'package:dio/dio.dart';
import '../models/license_status.dart';
import '../../core/api_client.dart';

class LicensesRepo {
  final Dio _dio;
  LicensesRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  /// Activate a license key.
  /// Returns the activated license details.
  /// Requirements 3.1, 3.2
  Future<Map<String, dynamic>> activateLicense(String licenseKey) async {
    final res = await _dio.post(
      '/licenses/activate',
      data: {'key': licenseKey},
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return res.data as Map<String, dynamic>;
  }

  /// Get current license status.
  /// Returns activation state, expiry, camera limit, and configured camera count.
  /// Requirement 3.5
  Future<LicenseStatus> getLicenseStatus() async {
    final res = await _dio.get(
      '/licenses/status',
      options: ApiClient.withTimeout(ApiClient.viewTimeout),
    );
    return LicenseStatus.fromJson(res.data as Map<String, dynamic>);
  }
}
