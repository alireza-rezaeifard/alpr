// lib/features/detection/video_task_controller.dart
// VideoTaskController: manages video upload, polling, and terminal state.
// Requirements: 8.1–8.12, 9.2, 9.3

import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/video_task_model.dart';
import '../../data/models/enhanced_plate_log_entry.dart';
import '../../data/repositories/detect_repo.dart';
import '../../core/api_client.dart';

// ── Video task state ──────────────────────────────────────────────────────

enum VideoTaskPhase { idle, uploading, polling, done, error, cancelled }

class VideoTaskState {
  final VideoTaskPhase phase;
  final String? taskId;
  final VideoTaskStatus? status;
  final String? errorDetail;
  final bool hasPartialOutput;
  final String? outputMediaPath;

  const VideoTaskState({
    this.phase = VideoTaskPhase.idle,
    this.taskId,
    this.status,
    this.errorDetail,
    this.hasPartialOutput = false,
    this.outputMediaPath,
  });

  VideoTaskState copyWith({
    VideoTaskPhase? phase,
    String? taskId,
    VideoTaskStatus? status,
    String? errorDetail,
    bool? hasPartialOutput,
    String? outputMediaPath,
  }) =>
      VideoTaskState(
        phase: phase ?? this.phase,
        taskId: taskId ?? this.taskId,
        status: status ?? this.status,
        errorDetail: errorDetail ?? (phase == VideoTaskPhase.error
            ? errorDetail
            : this.errorDetail),
        hasPartialOutput: hasPartialOutput ?? this.hasPartialOutput,
        outputMediaPath: outputMediaPath ?? this.outputMediaPath,
      );

  /// Progress 0-100 or null when indeterminate (Req 8.2, 8.11).
  int? get progressPercent => status?.progressPercent;

  /// The list of enhanced plate log entries parsed from the latest poll response.
  /// These include iranian validation info and metadata (Req 2.1, 2.2).
  List<EnhancedPlateLogEntry> get plateEntries => status?.plateLog ?? const [];

  /// True when the phase is a terminal state.
  bool get isTerminal =>
      phase == VideoTaskPhase.done ||
      phase == VideoTaskPhase.error ||
      phase == VideoTaskPhase.cancelled;
}

// ── Controller ─────────────────────────────────────────────────────────────

class VideoTaskController extends StateNotifier<VideoTaskState> {
  final DetectRepo _repo;
  Timer? _pollTimer;

  VideoTaskController(this._repo) : super(const VideoTaskState());

  /// Submit a video file for processing.
  /// [bytes] is the raw file content; [filename] is the original file name.
  /// [skipFrames] must be 1–1000 (validated by the caller, default 30).
  Future<void> submit(
    List<int> bytes,
    String filename, {
    int skipFrames = 30,
  }) async {
    _stopPolling();
    state = const VideoTaskState(phase: VideoTaskPhase.uploading);
    try {
      final result = await _repo.startVideoTask(bytes, filename, skipFrames);
      state = state.copyWith(
        phase: VideoTaskPhase.polling,
        taskId: result.taskId,
      );
      _startPolling(result.taskId);
    } catch (e) {
      state = state.copyWith(
        phase: VideoTaskPhase.error,
        errorDetail: _errMsg(e),
      );
    }
  }

  /// Stop the running video task.
  Future<void> stop() async {
    final taskId = state.taskId;
    if (taskId == null) return;
    _stopPolling();
    try {
      await _repo.stopVideoTask(taskId);
    } catch (_) {}
    // Mark cancelled — the backend will update status on its next state change
    state = state.copyWith(phase: VideoTaskPhase.cancelled);
  }

  void reset() {
    _stopPolling();
    state = const VideoTaskState();
  }

  // ── Polling ───────────────────────────────────────────────────────────────

  void _startPolling(String taskId) {
    _pollTimer = Timer.periodic(const Duration(milliseconds: 1000), (_) {
      _poll(taskId);
    });
  }

  void _stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  Future<void> _poll(String taskId) async {
    try {
      final status = await _repo.pollVideoTask(taskId);
      _applyStatus(status);
    } catch (e) {
      // Don't stop polling on a transient network error; keep showing last state
    }
  }

  void _applyStatus(VideoTaskStatus status) {
    switch (status.status) {
      case 'done':
        _stopPolling();
        final outputPath = status.outputPath;
        state = state.copyWith(
          phase: VideoTaskPhase.done,
          status: status,
          outputMediaPath: outputPath,
        );
        break;

      case 'error':
        _stopPolling();
        // Req 8.8 — check for partial output
        final partial =
            status.outputPath != null && status.outputPath!.isNotEmpty;
        state = state.copyWith(
          phase: VideoTaskPhase.error,
          status: status,
          errorDetail: status.error ?? 'An error occurred',
          hasPartialOutput: partial,
          outputMediaPath: status.outputPath,
        );
        break;

      case 'cancelled':
        _stopPolling();
        state = state.copyWith(
          phase: VideoTaskPhase.cancelled,
          status: status,
        );
        break;

      default: // queued, opening, processing
        state = state.copyWith(
          phase: VideoTaskPhase.polling,
          status: status,
          // Persist the previous error detail (Req 8.10)
          errorDetail: state.errorDetail,
        );
    }
  }

  @override
  void dispose() {
    _stopPolling();
    super.dispose();
  }
}

// ── Provider ──────────────────────────────────────────────────────────────

final _detectRepoProvider = Provider((_) => DetectRepo());

final videoTaskControllerProvider =
    StateNotifierProvider.autoDispose<VideoTaskController, VideoTaskState>(
        (ref) => VideoTaskController(ref.read(_detectRepoProvider)));

// ── Helpers ───────────────────────────────────────────────────────────────

String _errMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
