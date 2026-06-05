// lib/features/cameras/camera_poll_controller.dart
// Independent per-camera polling controller. One instance per running camera.
// Requirements: 13.1, 13.3, 13.4

import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/rtsp_task_model.dart';
import '../../data/repositories/detect_repo.dart';

class CameraPollState {
  final RtspTaskStatus? status;
  final String? lastAnnotated; // retained last frame
  final bool terminal;         // done or error

  const CameraPollState({
    this.status,
    this.lastAnnotated,
    this.terminal = false,
  });

  CameraPollState copyWith({
    RtspTaskStatus? status,
    String? lastAnnotated,
    bool? terminal,
  }) =>
      CameraPollState(
        status: status ?? this.status,
        lastAnnotated: lastAnnotated ?? this.lastAnnotated,
        terminal: terminal ?? this.terminal,
      );
}

/// Polls /api/detect/rtsp/{taskId} at 1000ms for a single camera.
/// Call [start] with the camera's task_id to begin polling.
/// Requirements: 13.3
class CameraPollController extends StateNotifier<CameraPollState> {
  final DetectRepo _repo;
  Timer? _timer;

  CameraPollController(this._repo) : super(const CameraPollState());

  void start(String taskId) {
    _stopTimer();
    _timer = Timer.periodic(const Duration(milliseconds: 1000), (_) {
      _poll(taskId);
    });
  }

  void _stopTimer() {
    _timer?.cancel();
    _timer = null;
  }

  Future<void> _poll(String taskId) async {
    try {
      final status = await _repo.pollRtsp(taskId);
      // Retain last annotated frame (Req 13.4, 13.7)
      final annotated = status.annotated?.isNotEmpty == true
          ? status.annotated
          : state.lastAnnotated;
      final terminal = status.hasError ||
          status.status == 'done' ||
          status.status == 'stopped';
      if (terminal) {
        // Req 13.4 — stop polling on terminal state, retain last frame
        _stopTimer();
      }
      state = state.copyWith(
        status: status,
        lastAnnotated: annotated,
        terminal: terminal,
      );
    } catch (_) {
      // Transient error — keep polling
    }
  }

  @override
  void dispose() {
    _stopTimer();
    super.dispose();
  }
}

// Family provider: one controller per (cameraId, taskId) pair
final _cameraPollRepoProvider = Provider((_) => DetectRepo());

final cameraPollProvider = StateNotifierProvider.family.autoDispose<
    CameraPollController, CameraPollState, String>(
  (ref, taskId) {
    final controller =
        CameraPollController(ref.read(_cameraPollRepoProvider));
    controller.start(taskId);
    return controller;
  },
);
