// lib/features/cameras/camera_panel.dart
// Per-camera live panel and enlarged single-camera view.
// Renders annotated frame, live detection lines, and plate history.
// Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/camera_model.dart';
import 'camera_poll_controller.dart';

// ── Live panel (used in grid) ─────────────────────────────────────────────

/// A single camera tile rendered in the multi-camera grid.
/// Shows name, latest annotated frame, live detection lines, and status badge.
/// Requirements: 13.1, 13.3, 13.4, 13.7
class CameraLivePanel extends ConsumerWidget {
  final CameraModel camera;
  final VoidCallback? onTap;

  const CameraLivePanel({
    super.key,
    required this.camera,
    this.onTap,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final taskId = camera.taskId;

    // If no taskId is available yet, show a waiting placeholder
    if (taskId == null || taskId.isEmpty) {
      return _PanelShell(
        camera: camera,
        onTap: onTap,
        child: const _FramePlaceholder(message: 'Waiting for stream...'),
      );
    }

    final pollState = ref.watch(cameraPollProvider(taskId));

    return _PanelShell(
      camera: camera,
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Annotated frame — takes most of the panel
          Expanded(
            child: _AnnotatedFrame(annotated: pollState.lastAnnotated),
          ),
          // Live detection lines (Req 13.2)
          if (pollState.status?.liveDetections.isNotEmpty == true)
            _LiveDetectionBar(
                detections: pollState.status!.liveDetections),
        ],
      ),
    );
  }
}

/// Outer shell: camera name header + tap gesture.
class _PanelShell extends StatelessWidget {
  final CameraModel camera;
  final VoidCallback? onTap;
  final Widget child;

  const _PanelShell({
    required this.camera,
    required this.child,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Name + status bar
            Container(
              color: Theme.of(context).colorScheme.surface,
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      camera.name.isNotEmpty ? camera.name : '(no name)',
                      style: const TextStyle(
                          fontWeight: FontWeight.w600, fontSize: 12),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  _StatusBadge(status: camera.status),
                ],
              ),
            ),
            Expanded(child: child),
          ],
        ),
      ),
    );
  }
}

// ── Annotated frame ───────────────────────────────────────────────────────

/// Renders a base64 annotated JPEG, or a placeholder when unavailable.
/// Req 13.7 — missing/undecodable frame → frame-unavailable placeholder.
class _AnnotatedFrame extends StatelessWidget {
  final String? annotated;
  const _AnnotatedFrame({this.annotated});

  @override
  Widget build(BuildContext context) {
    if (annotated == null || annotated!.isEmpty) {
      return const _FramePlaceholder(message: 'Frame unavailable');
    }
    try {
      // Strip optional data-URL prefix ("data:image/jpeg;base64,")
      final base64Str = annotated!.contains(',')
          ? annotated!.split(',').last
          : annotated!;
      final bytes = base64Decode(base64Str);
      return Image.memory(
        bytes,
        fit: BoxFit.cover,
        gaplessPlayback: true,
        errorBuilder: (_, __, ___) =>
            const _FramePlaceholder(message: 'Frame unavailable'),
      );
    } catch (_) {
      return const _FramePlaceholder(message: 'Frame unavailable');
    }
  }
}

class _FramePlaceholder extends StatelessWidget {
  final String message;
  const _FramePlaceholder({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black87,
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.videocam_off, color: Colors.grey, size: 32),
            const SizedBox(height: 4),
            Text(message,
                style: const TextStyle(color: Colors.grey, fontSize: 11)),
          ],
        ),
      ),
    );
  }
}

// ── Live detection bar ────────────────────────────────────────────────────

/// Shows the latest live detection lines in a compact bar (Req 13.2).
class _LiveDetectionBar extends StatelessWidget {
  final List<String> detections;
  const _LiveDetectionBar({required this.detections});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black54,
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
      child: Text(
        detections.join('  •  '),
        style: const TextStyle(color: Colors.white, fontSize: 10),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
    );
  }
}

// ── Status badge ──────────────────────────────────────────────────────────

class _StatusBadge extends StatelessWidget {
  final String status;
  const _StatusBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (status) {
      case 'streaming':
      case 'connected':
        color = Colors.green;
        break;
      case 'connecting':
        color = Colors.orange;
        break;
      case 'error':
        color = Colors.red;
        break;
      case 'queued':
        color = Colors.blue;
        break;
      default:
        color = Colors.grey;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.2),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color, width: 0.8),
      ),
      child: Text(
        status,
        style: TextStyle(color: color, fontSize: 9, fontWeight: FontWeight.w600),
      ),
    );
  }
}

// ── Enlarged single-camera view ───────────────────────────────────────────

/// Full-screen enlarged view for a single camera.
/// Shows enlarged annotated frame + full plate history.
/// Req 13.5, 13.6 — tap from grid opens this; history failure shows message and
/// retains the live view.
class CameraEnlargedView extends ConsumerWidget {
  final CameraModel camera;
  const CameraEnlargedView({super.key, required this.camera});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final taskId = camera.taskId;

    return Scaffold(
      appBar: AppBar(
        title: Text(camera.name.isNotEmpty ? camera.name : '(no name)'),
        actions: [
          _StatusBadge(status: camera.status),
          const SizedBox(width: 12),
        ],
      ),
      body: taskId == null || taskId.isEmpty
          ? const Center(
              child: Text('No active stream task',
                  style: TextStyle(color: Colors.grey)))
          : _EnlargedContent(camera: camera, taskId: taskId),
    );
  }
}

class _EnlargedContent extends ConsumerWidget {
  final CameraModel camera;
  final String taskId;
  const _EnlargedContent({required this.camera, required this.taskId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pollState = ref.watch(cameraPollProvider(taskId));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // ── Enlarged frame (top half) ──────────────────────────────────
        Expanded(
          flex: 3,
          child: Stack(
            fit: StackFit.expand,
            children: [
              _AnnotatedFrame(annotated: pollState.lastAnnotated),
              // Live detections overlay at bottom of frame
              if (pollState.status?.liveDetections.isNotEmpty == true)
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: _LiveDetectionBar(
                      detections: pollState.status!.liveDetections),
                ),
            ],
          ),
        ),
        // ── Full plate history (bottom half) ──────────────────────────
        Expanded(
          flex: 2,
          child: _PlateHistory(pollState: pollState),
        ),
      ],
    );
  }
}

/// Renders the full plate history from the latest poll state.
/// Req 13.6 — if history fails to load show history-unavailable message.
class _PlateHistory extends StatelessWidget {
  final CameraPollState pollState;
  const _PlateHistory({required this.pollState});

  @override
  Widget build(BuildContext context) {
    final history = pollState.status?.history;

    if (history == null) {
      // Loading or unavailable
      return const Center(
        child: Text('History unavailable',
            style: TextStyle(color: Colors.grey)),
      );
    }

    if (history.isEmpty) {
      return const Center(
        child: Text('No detections yet',
            style: TextStyle(color: Colors.grey)),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
          child: Text(
            'Plate History (${history.length})',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
        Expanded(
          child: ListView.builder(
            itemCount: history.length,
            itemBuilder: (ctx, i) {
              final entry = history[i];
              return ListTile(
                dense: true,
                title: Directionality(
                  textDirection: TextDirection.rtl,
                  child: Text(entry.yoloText,
                      style: const TextStyle(fontSize: 13)),
                ),
                subtitle: Text(
                  '${(entry.confidence * 100).toStringAsFixed(1)}% • ×${entry.count} • ${entry.firstSeen}',
                  style: const TextStyle(fontSize: 11),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}
