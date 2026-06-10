// lib/features/cameras/camera_poll_controller.dart
// Independent per-camera polling controller. One instance per running camera.
// Uses fast frame-only endpoint for smooth ~4-5 FPS playback.
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

/// Polls /api/detect/rtsp/{taskId}/frame at ~500ms for smooth video.
/// Falls back to full status poll every 3 seconds for complete history.
/// Requirements: 13.3
class CameraPollController extends StateNotifier<CameraPollState> {
  final DetectRepo _repo;
  Timer? _frameTimer;
  Timer? _fullTimer;
  bool _polling = false;

  CameraPollController(this._repo) : super(const CameraPollState());

  void start(String taskId) {
    _stopTimers();
    // Frame polling at ~100ms (~10 FPS) for smooth playback. The backend
    // reader thread + pre-encoded JPEG means each poll returns a fresh frame.
    _frameTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      _pollFrame(taskId);
    });
    // Full status poll every 3 seconds (for complete history)
    _fullTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      _pollFull(taskId);
    });
    // Immediate first poll
    _pollFrame(taskId);
  }

  void _stopTimers() {
    _frameTimer?.cancel();
    _frameTimer = null;
    _fullTimer?.cancel();
    _fullTimer = null;
  }

  Future<void> _pollFrame(String taskId) async {
    if (_polling) return; // Skip if previous poll still in flight
    _polling = true;
    try {
      final status = await _repo.pollRtspFrame(taskId);
      final annotated = status.annotated?.isNotEmpty == true
          ? status.annotated
          : state.lastAnnotated;
      final terminal = status.hasError ||
          status.status == 'done' ||
          status.status == 'stopped';
      if (terminal) {
        _stopTimers();
      }
      state = state.copyWith(
        status: status,
        lastAnnotated: annotated,
        terminal: terminal,
      );
    } catch (_) {
      // Transient error — keep polling
    } finally {
      _polling = false;
    }
  }

  Future<void> _pollFull(String taskId) async {
    try {
      final status = await _repo.pollRtsp(taskId);
      final annotated = status.annotated?.isNotEmpty == true
          ? status.annotated
          : state.lastAnnotated;
      final terminal = status.hasError ||
          status.status == 'done' ||
          status.status == 'stopped';
      if (terminal) {
        _stopTimers();
      }
      state = state.copyWith(
        status: status,
        lastAnnotated: annotated,
        terminal: terminal,
      );
    } catch (_) {}
  }

  @override
  void dispose() {
    _stopTimers();
    super.dispose();
  }
}

// Family provider: one controller per taskId
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
