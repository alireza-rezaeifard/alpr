// lib/core/health_controller.dart
// Riverpod AsyncNotifier: polls GET /api/health at startup (5s timeout)
// and every 30s while disconnected.
// Requirements: 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7

import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import 'api_client.dart';
import '../app/config.dart';

enum ConnectivityStatus { unknown, connected, disconnected, configError }

class HealthState {
  final ConnectivityStatus status;
  final String? errorMessage;
  const HealthState({required this.status, this.errorMessage});
}

class HealthController extends AsyncNotifier<HealthState> {
  Timer? _retryTimer;

  @override
  Future<HealthState> build() async {
    // Clean up timer when the notifier is disposed
    ref.onDispose(() {
      _retryTimer?.cancel();
      _retryTimer = null;
    });
    // If the config is invalid, immediately return configError (Req 1.8)
    if (!RuntimeConfig.isValid) {
      return const HealthState(
        status: ConnectivityStatus.configError,
        errorMessage: 'Backend URL is missing or invalid. '
            'Set BACKEND_URL via --dart-define.',
      );
    }
    return _checkHealth();
  }

  Future<HealthState> _checkHealth() async {
    try {
      final response = await ApiClient.instance.get(
        '/health',
        options: ApiClient.withTimeout(ApiClient.healthTimeout),
      );
      final data = response.data;
      if (data is Map && data['status'] == 'ok') {
        _stopRetryTimer();
        return const HealthState(status: ConnectivityStatus.connected);
      }
      return _disconnected('Unexpected health response: ${data.toString()}');
    } on DioException catch (e) {
      final msg = (e.error is ApiException)
          ? (e.error as ApiException).failure.message
          : e.message ?? 'Connection failed';
      return _disconnected(msg);
    } catch (e) {
      return _disconnected(e.toString());
    }
  }

  HealthState _disconnected(String message) {
    _scheduleRetry();
    return HealthState(
      status: ConnectivityStatus.disconnected,
      errorMessage: message,
    );
  }

  void _scheduleRetry() {
    _retryTimer?.cancel();
    // Re-check every 30 seconds while disconnected (Req 2.6)
    _retryTimer = Timer(const Duration(seconds: 30), () {
      if (state.value?.status == ConnectivityStatus.disconnected) {
        retry();
      }
    });
  }

  void _stopRetryTimer() {
    _retryTimer?.cancel();
    _retryTimer = null;
  }

  /// Manually trigger a health re-check (Req 2.7).
  Future<void> retry() async {
    if (!RuntimeConfig.isValid) return;
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(_checkHealth);
    // If now connected, stop the auto-retry timer
    if (state.value?.status == ConnectivityStatus.connected) {
      _stopRetryTimer();
    }
  }

}

final healthControllerProvider =
    AsyncNotifierProvider<HealthController, HealthState>(
  HealthController.new,
);
