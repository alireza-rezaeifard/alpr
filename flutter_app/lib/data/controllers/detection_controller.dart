// lib/data/controllers/detection_controller.dart
// Detection controller for image/video/RTSP detection tasks.
// Requirements: 8.1-8.5, 9.1-9.6, 10.1-10.4

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/video_task_model.dart';
import '../models/rtsp_task_model.dart';
import '../repositories/detect_repo.dart';

/// Detection state for active tasks.
class DetectionState {
  final String? activeVideoTaskId;
  final int? activeVideoSessionId;
  final VideoTaskStatus? videoStatus;
  final String? activeRtspTaskId;
  final int? activeRtspSessionId;
  final RtspTaskStatus? rtspStatus;
  final bool loading;
  final String? error;

  const DetectionState({
    this.activeVideoTaskId,
    this.activeVideoSessionId,
    this.videoStatus,
    this.activeRtspTaskId,
    this.activeRtspSessionId,
    this.rtspStatus,
    this.loading = false,
    this.error,
  });

  DetectionState copyWith({
    String? activeVideoTaskId,
    int? activeVideoSessionId,
    VideoTaskStatus? videoStatus,
    String? activeRtspTaskId,
    int? activeRtspSessionId,
    RtspTaskStatus? rtspStatus,
    bool? loading,
    String? error,
  }) =>
      DetectionState(
        activeVideoTaskId: activeVideoTaskId ?? this.activeVideoTaskId,
        activeVideoSessionId: activeVideoSessionId ?? this.activeVideoSessionId,
        videoStatus: videoStatus ?? this.videoStatus,
        activeRtspTaskId: activeRtspTaskId ?? this.activeRtspTaskId,
        activeRtspSessionId: activeRtspSessionId ?? this.activeRtspSessionId,
        rtspStatus: rtspStatus ?? this.rtspStatus,
        loading: loading ?? this.loading,
        error: error,
      );

  DetectionState clearVideo() => copyWith(
        activeVideoTaskId: null,
        activeVideoSessionId: null,
        videoStatus: null,
      );

  DetectionState clearRtsp() => copyWith(
        activeRtspTaskId: null,
        activeRtspSessionId: null,
        rtspStatus: null,
      );
}

/// Detection controller for managing detection tasks.
class DetectionController extends StateNotifier<DetectionState> {
  final DetectRepo _repo;

  DetectionController(this._repo) : super(const DetectionState());

  /// Detect plates in an image.
  /// Requirement 8.1
  Future<DetectImageResult> detectImage(
    List<int> fileBytes,
    String filename,
  ) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final result = await _repo.detectImage(fileBytes, filename);
      state = state.copyWith(loading: false);
      return result;
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Start a video detection task.
  /// Requirement 9.1
  Future<void> startVideoTask(
    List<int> fileBytes,
    String filename,
    int skipFrames,
  ) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final result = await _repo.startVideoTask(fileBytes, filename, skipFrames);
      state = state.copyWith(
        activeVideoTaskId: result.taskId,
        activeVideoSessionId: result.sessionId,
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Poll video task status.
  /// Requirement 9.2
  Future<void> pollVideoTask() async {
    final taskId = state.activeVideoTaskId;
    if (taskId == null) return;

    try {
      final status = await _repo.pollVideoTask(taskId);
      state = state.copyWith(videoStatus: status);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  /// Stop a video detection task.
  /// Requirement 9.3
  Future<void> stopVideoTask() async {
    final taskId = state.activeVideoTaskId;
    if (taskId == null) return;

    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.stopVideoTask(taskId);
      state = state.clearVideo().copyWith(loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Start an RTSP detection task.
  /// Requirement 10.1
  Future<void> startRtspTask(String url, int skipFrames) async {
    state = state.copyWith(loading: true, error: null);
    try {
      final result = await _repo.startRtsp(url, skipFrames);
      state = state.copyWith(
        activeRtspTaskId: result['task_id'] as String,
        activeRtspSessionId: result['session_id'] as int,
        loading: false,
      );
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }

  /// Poll RTSP task status.
  /// Requirement 10.2
  Future<void> pollRtspTask() async {
    final taskId = state.activeRtspTaskId;
    if (taskId == null) return;

    try {
      final status = await _repo.pollRtsp(taskId);
      state = state.copyWith(rtspStatus: status);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  /// Stop an RTSP detection task.
  /// Requirement 10.3
  Future<void> stopRtspTask() async {
    final taskId = state.activeRtspTaskId;
    if (taskId == null) return;

    state = state.copyWith(loading: true, error: null);
    try {
      await _repo.stopRtsp(taskId);
      state = state.clearRtsp().copyWith(loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
      rethrow;
    }
  }
}

// Provider for DetectRepo
final detectRepoProvider = Provider((ref) => DetectRepo());

// Provider for DetectionController
final detectionControllerProvider =
    StateNotifierProvider<DetectionController, DetectionState>((ref) {
  final repo = ref.watch(detectRepoProvider);
  return DetectionController(repo);
});
