// lib/core/api_client.dart
// Dio instance with base URL, per-request timeouts, and central error-mapping interceptor.
// Requirements: 1.5, 1.8, 2.1

import 'package:dio/dio.dart';
import '../app/config.dart';

/// Typed failure returned by the error-mapping interceptor.
class ApiFailure {
  final int? status;
  final String message;
  const ApiFailure({this.status, required this.message});

  @override
  String toString() => 'ApiFailure(status: $status, message: $message)';
}

/// Exception wrapping [ApiFailure] thrown by the interceptor.
class ApiException implements Exception {
  final ApiFailure failure;
  const ApiException(this.failure);
  @override
  String toString() => failure.toString();
}

/// Singleton Dio instance configured for the PLPR backend.
class ApiClient {
  ApiClient._();

  static final Dio _dio = _build();

  /// The shared Dio instance. Use [withTimeout] for custom timeouts.
  static Dio get instance => _dio;

  static Dio _build() {
    final dio = Dio(
      BaseOptions(
        baseUrl: '${RuntimeConfig.backendUrl}/api',
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 10),
        contentType: 'application/json',
      ),
    );
    dio.interceptors.add(_ErrorMappingInterceptor());
    return dio;
  }

  /// Returns a Dio options copy with a custom [receiveTimeout].
  static Options withTimeout(Duration timeout) =>
      Options(receiveTimeout: timeout);

  /// Shorthand timeouts used across the app.
  static const Duration healthTimeout = Duration(seconds: 5);
  static const Duration viewTimeout   = Duration(seconds: 10);
  static const Duration uploadTimeout = Duration(seconds: 60);
}

class _ErrorMappingInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final status = err.response?.statusCode;
    final body   = err.response?.data;
    String message;

    if (err.type == DioExceptionType.connectionTimeout ||
        err.type == DioExceptionType.receiveTimeout ||
        err.type == DioExceptionType.sendTimeout) {
      message = 'Request timed out';
    } else if (err.type == DioExceptionType.connectionError) {
      message = 'Cannot connect to backend';
    } else if (status != null) {
      // Try to extract error message from JSON body
      if (body is Map && body.containsKey('error')) {
        message = body['error'].toString();
      } else if (body is Map && body.containsKey('detail')) {
        message = body['detail'].toString();
      } else {
        message = 'Server error $status';
      }
    } else {
      message = err.message ?? 'Unknown error';
    }

    handler.next(
      err.copyWith(
        error: ApiException(ApiFailure(status: status, message: message)),
      ),
    );
  }
}
