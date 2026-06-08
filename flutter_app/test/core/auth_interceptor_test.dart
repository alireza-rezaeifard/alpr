// test/core/auth_interceptor_test.dart
// Unit tests for AuthInterceptor token attachment and 401 handling.
// Requirements: 18.2, 18.3

import 'package:flutter_test/flutter_test.dart';
import 'package:dio/dio.dart';
import 'package:flutter_app/core/auth_interceptor.dart';
import 'package:flutter_app/core/secure_storage.dart';

// Mock error handler that doesn't throw
class _MockErrorHandler extends ErrorInterceptorHandler {
  @override
  void next(DioException err) {
    // Do nothing - just absorb the error
  }
}

void main() {
  group('AuthInterceptor', () {
    late Dio dio;

    setUp(() async {
      // Reset storage and flag before each test
      await SecureStorage.deleteToken();
      AuthInterceptor.clearReauthFlag();

      // Create a test Dio instance with the auth interceptor
      dio = Dio(BaseOptions(baseUrl: 'http://test.api'));
      dio.interceptors.add(AuthInterceptor());
    });

    test('attaches Bearer token to requests when token exists', () async {
      // Store a test token
      await SecureStorage.writeToken('test-token-123');

      // Create a mock interceptor to capture the request
      String? capturedAuth;
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            capturedAuth = options.headers['Authorization'] as String?;
            // Return a success response to complete the request
            handler.resolve(Response(
              requestOptions: options,
              statusCode: 200,
              data: {'success': true},
            ));
          },
        ),
      );

      // Make a request
      await dio.get('/test');

      // Verify Bearer token was attached
      expect(capturedAuth, 'Bearer test-token-123');
    });

    test('does not attach Authorization header when no token exists', () async {
      // Ensure no token is stored
      await SecureStorage.deleteToken();

      // Create a mock interceptor to capture the request
      String? capturedAuth;
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            capturedAuth = options.headers['Authorization'] as String?;
            handler.resolve(Response(
              requestOptions: options,
              statusCode: 200,
              data: {'success': true},
            ));
          },
        ),
      );

      // Make a request
      await dio.get('/test');

      // Verify no Authorization header was attached
      expect(capturedAuth, isNull);
    });

    test('clears token and sets reauthentication flag on 401 response',
        () async {
      // Store a test token
      await SecureStorage.writeToken('expired-token');
      expect(await SecureStorage.hasToken(), isTrue);
      expect(AuthInterceptor.needsReauthentication, isFalse);

      // Manually simulate what happens on a 401
      // Create the error
      final err = DioException(
        requestOptions: RequestOptions(path: '/test'),
        response: Response(
          requestOptions: RequestOptions(path: '/test'),
          statusCode: 401,
          data: {'error': 'auth required'},
        ),
        type: DioExceptionType.badResponse,
      );

      // Get the auth interceptor
      final authInt = dio.interceptors.firstWhere(
        (i) => i is AuthInterceptor,
      ) as AuthInterceptor;

      // Create a mock handler that doesn't throw
      final mockHandler = _MockErrorHandler();

      // Call onError
      authInt.onError(err, mockHandler);

      // Wait for the async _handle401 to complete
      await Future.delayed(Duration(milliseconds: 200));

      // Verify token was cleared
      expect(await SecureStorage.hasToken(), isFalse,
          reason: 'Token should be cleared after 401');

      // Verify reauthentication flag was set
      expect(AuthInterceptor.needsReauthentication, isTrue,
          reason: 'Reauthentication flag should be set after 401');
    });

    test('does not clear token on non-401 errors', () async {
      // Store a test token
      await SecureStorage.writeToken('valid-token');

      // Create a mock interceptor to simulate 500 response
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            handler.reject(
              DioException(
                requestOptions: options,
                response: Response(
                  requestOptions: options,
                  statusCode: 500,
                  data: {'error': 'server error'},
                ),
              ),
            );
          },
        ),
      );

      // Make a request (should fail with 500)
      try {
        await dio.get('/error');
      } catch (_) {
        // Expected to throw
      }

      // Verify token was NOT cleared
      expect(await SecureStorage.hasToken(), isTrue);
      expect(await SecureStorage.readToken(), 'valid-token');

      // Verify reauthentication flag was NOT set
      expect(AuthInterceptor.needsReauthentication, isFalse);
    });

    test('clearReauthFlag resets the reauthentication flag', () {
      // Set the flag
      AuthInterceptor.needsReauthentication = true;
      expect(AuthInterceptor.needsReauthentication, isTrue);

      // Clear it
      AuthInterceptor.clearReauthFlag();
      expect(AuthInterceptor.needsReauthentication, isFalse);
    });
  });
}
