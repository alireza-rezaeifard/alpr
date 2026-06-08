// lib/data/controllers/cameras_controller.dart
// Cameras management controller.
// Requirements: 4.1-4.7, 5.1-5.8

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/camera_model.dart';
import '../repositories/camera_repo.dart';

/// Cameras management state.
class CamerasState {
  final List<CameraModel> cameras;
  final int? concurrencyLimit;
  final bool loading;
  final String? error;

  const CamerasState({
    this.cameras = const [],
    this.concurrencyLimit,
    this.loading = false,
    this.error,
  });

  CamerasState copyWith({
    List<CameraModel>? cameras,
    int? concurrencyLimit,
    bool? loading,
    String? error,
  }) =>
      CamerasState(
        cameras: cameras ?? this.cameras,
        concurrencyLimit: concurrencyLimit ?? this.concurrencyLimit,
        loading: loading ?? this.loading,
        error: error,
      );
}

/// Cameras management controller.
class CamerasController extends StateNotifier<CamerasState> {
  final CameraRepo _repo;

  CamerasController(this._repo) : super(const CamerasState());

  /// Load all cameras.
  /// Requirement 4.2
  Future<void> loadCameras() async {
    state = state.copyWith(loading: true, error: null);
    try {
      final cameras = await _repo.listCameras();
      state = state.copyWith(cameras: cameras, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Create a new camera.
  /// Requirement 4.1
  Future<void> createCamera(String name, String url, int skipFrames) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final newCamera = await _repo.createCamera(name, url, skipFrames);
      state = state.copyWith(
        cameras: [...state.cameras, newCamera],
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Update a camera.
  /// Requirement 4.3
  Future<void> updateCamera(
    int id, {
    String? name,
    String? url,
    int? skipFrames,
  }) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final updatedCamera = await _repo.updateCamera(
        id,
        name: name,
        url: url,
        skipFrames: skipFrames,
      );
      state = state.copyWith(
        cameras: state.cameras
            .map((c) => c.id == id ? updatedCamera : c)
            .toList(),
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Delete a camera.
  /// Requirement 4.5
  Future<void> deleteCamera(int id) async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.deleteCamera(id);
      state = state.copyWith(
        cameras: state.cameras.where((c) => c.id != id).toList(),
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Start a camera.
  /// Requirements 5.1, 5.2
  Future<StartResultModel> startCamera(int id) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final result = await _repo.startCamera(id);
      // Reload cameras to get updated status
      await loadCameras();
      return result;
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Stop a camera.
  /// Requirement 5.3
  Future<void> stopCamera(int id) async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.stopCamera(id);
      // Reload cameras to get updated status
      await loadCameras();
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Start all cameras.
  /// Requirement 5.4
  Future<List<StartResultModel>> startAll() async {
    state = state.copyWith(loading: true, error: null);
    try {
      final results = await _repo.startAll();
      // Reload cameras to get updated status
      await loadCameras();
      return results;
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Stop all cameras.
  /// Requirement 5.5
  Future<void> stopAll() async {
    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.stopAll();
      // Reload cameras to get updated status
      await loadCameras();
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Get concurrency limit.
  /// Requirement 5.6
  Future<void> loadConcurrencyLimit() async {
    try {
      final limit = await _repo.getConcurrencyLimit();
      state = state.copyWith(concurrencyLimit: limit);
    } catch (e) {
      state = state.copyWith(error: e.toString());
      rethrow;
    }
  }

  /// Set concurrency limit.
  /// Requirement 5.6
  Future<void> setConcurrencyLimit(int value) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final limit = await _repo.setConcurrencyLimit(value);
      state = state.copyWith(concurrencyLimit: limit, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }
}

// Provider for CameraRepo
final cameraRepoProvider = Provider((ref) => CameraRepo());

// Provider for CamerasController
final camerasControllerProvider =
    StateNotifierProvider<CamerasController, CamerasState>((ref) {
  final repo = ref.watch(cameraRepoProvider);
  return CamerasController(repo);
});
