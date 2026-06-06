// lib/features/detection/rtsp_poll_controller.dart
// RTSPPollController: manages RTSP start, polling, and terminal state.
// Requirements: 10.1–10.6

import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/rtsp_task_model.dart';
import '../../data/models/enhanced_rtsp_history_entry.dart';
import '../../data/repositories/detect_repo.dart';
import '../../core/api_client.dart';

enum RtspPhase { idle, starting, streaming, error, stopped }

class RtspState {
  final RtspPhase phase;
  final String? taskId;
  final RtspTaskStatus? status;
  final String? errorMessage;

  const RtspState({
    this.phase = RtspPhase.idle,
    this.taskId,
    this.status,
    this.errorMessage,
  });

  RtspState copyWith({
    RtspPhase? phase,
    String? taskId,
    RtspTaskStatus? status,
    String? errorMessage,
  }) =>
      RtspState(
        phase: phase ?? this.phase,
        taskId: taskId ?? this.taskId,
        status: status ?? this.status,
        errorMessage: errorMessage ?? this.errorMessage,
      );

  bool get isActive =>
      phase == RtspPhase.starting || phase == RtspPhase.streaming;

  /// The list of enhanced RTSP history entries parsed from the latest poll response.
  /// These include iranian validation info, metadata, and deduplication count (Req 3.1, 3.2).
  List<EnhancedRtspHistoryEntry> get historyEntries =>
      status?.history ?? const [];
}

class RTSPPollController extends StateNotifier<RtspState> {
  final DetectRepo _repo;
  Timer? _pollTimer;

  RTSPPollController(this._repo) : super(const RtspState());

  /// Start an RTSP stream. URL must begin with rtsp:// (caller validates).
  /// skipFrames must be 1–1000 (caller validates, default 15).
  Future<void> start(String url, int skipFrames) async {
    _stopPolling();
    state = const RtspState(phase: RtspPhase.starting);
    try {
      final data = await _repo.startRtsp(url, skipFrames);
      final taskId = data['task_id'] as String;
      state = state.copyWith(phase: RtspPhase.streaming, taskId: taskId);
      _startPolling(taskId);
    } catch (e) {
      state = state.copyWith(
        phase: RtspPhase.error,
        errorMessage: _errMsg(e),
      );
    }
  }

  /// Stop the running RTSP task (Req 10.5).
  Future<void> stop() async {
    final taskId = state.taskId;
    _stopPolling();
    if (taskId != null) {
      try {
        await _repo.stopRtsp(taskId);
      } catch (_) {}
    }
    state = state.copyWith(phase: RtspPhase.stopped);
  }

  void reset() {
    _stopPolling();
    state = const RtspState();
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
      final status = await _repo.pollRtsp(taskId);
      // Req 10.6 — stop polling within one cycle when status starts with 'error'
      if (status.hasError) {
        _stopPolling();
        state = state.copyWith(
          phase: RtspPhase.error,
          status: status,
          errorMessage: status.status,
        );
        return;
      }
      state = state.copyWith(
        phase: RtspPhase.streaming,
        status: status,
      );
    } catch (_) {
      // Transient network error — keep polling
    }
  }

  @override
  void dispose() {
    _stopPolling();
    super.dispose();
  }
}

final _rtspDetectRepoProvider = Provider((_) => DetectRepo());

final rtspPollControllerProvider =
    StateNotifierProvider.autoDispose<RTSPPollController, RtspState>(
        (ref) => RTSPPollController(ref.read(_rtspDetectRepoProvider)));

String _errMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
