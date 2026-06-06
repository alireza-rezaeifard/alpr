// lib/features/detection/video_sub_view.dart
// Video detection: smooth local HTML5 playback + detection results overlay.
// The video plays natively at full speed. Detection results (plate log) update
// periodically from the backend based on skip_frames setting.

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import '../../shared/playback/playback_controller.dart';
import '../../shared/widgets/plate_detail_card.dart';
import '../../data/models/enhanced_plate_log_entry.dart';
import 'video_task_controller.dart';

// Web-specific video widget
import '../../shared/playback/video_widget_web.dart'
    if (dart.library.io) '../../shared/playback/video_widget_stub.dart'
    as platform_video;

class VideoSubView extends ConsumerStatefulWidget {
  const VideoSubView({super.key});

  @override
  ConsumerState<VideoSubView> createState() => _VideoSubViewState();
}

class _VideoSubViewState extends ConsumerState<VideoSubView> {
  final _skipFramesCtrl = TextEditingController(text: '30');
  String? _skipError;
  String? _pickError;
  bool _picking = false;
  PlaybackController? _playback;
  String? _pickedFileName;

  @override
  void dispose() {
    _skipFramesCtrl.dispose();
    _playback?.dispose();
    super.dispose();
  }

  bool _validateSkip() {
    final v = int.tryParse(_skipFramesCtrl.text.trim());
    if (v == null || v < 1 || v > 1000) {
      setState(() => _skipError = 'Must be 1–1000');
      return false;
    }
    setState(() => _skipError = null);
    return true;
  }

  Future<void> _pickAndSubmit() async {
    if (!_validateSkip()) return;
    final skip = int.parse(_skipFramesCtrl.text.trim());

    setState(() {
      _pickError = null;
      _picking = true;
    });

    try {
      FilePickerResult? result;
      try {
        result = await FilePicker.platform.pickFiles(
          type: FileType.video,
          withData: true,
        );
      } catch (_) {
        result = await FilePicker.platform.pickFiles(
          type: FileType.any,
          withData: true,
        );
      }

      if (result == null || result.files.isEmpty) {
        setState(() => _picking = false);
        return;
      }

      final file = result.files.first;
      final bytes = file.bytes;
      final name = file.name;

      if (bytes == null) {
        setState(() {
          _picking = false;
          _pickError = 'Could not read file bytes.';
        });
        return;
      }

      // Set up local playback controller with the bytes
      final controller = PlaybackController();
      await controller.openBytes(bytes, 'video/mp4');
      controller.play();

      _playback?.dispose();
      setState(() {
        _pickedFileName = name;
        _playback = controller;
        _picking = false;
      });

      // Submit to backend for plate recognition processing
      await ref.read(videoTaskControllerProvider.notifier).submit(
            bytes.toList(),
            name,
            skipFrames: skip,
          );
    } catch (e) {
      setState(() {
        _picking = false;
        _pickError = 'Failed to load video: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final taskState = ref.watch(videoTaskControllerProvider);
    final taskCtrl = ref.read(videoTaskControllerProvider.notifier);
    final isActive = taskState.phase == VideoTaskPhase.uploading ||
        taskState.phase == VideoTaskPhase.polling;

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Controls ─────────────────────────────────────────────────
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 100,
                child: TextField(
                  controller: _skipFramesCtrl,
                  decoration: InputDecoration(
                    labelText: 'Skip frames',
                    errorText: _skipError,
                    isDense: true,
                  ),
                  keyboardType: TextInputType.number,
                  enabled: !isActive,
                ),
              ),
              const SizedBox(width: 12),
              ElevatedButton.icon(
                icon: _picking
                    ? const SizedBox(
                        width: 16, height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.upload_file),
                label: Text(_picking ? 'Loading…' : 'Select Video'),
                onPressed: (isActive || _picking) ? null : _pickAndSubmit,
              ),
              const SizedBox(width: 8),
              if (isActive)
                ElevatedButton.icon(
                  icon: const Icon(Icons.stop),
                  label: const Text('Stop'),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                  onPressed: taskCtrl.stop,
                ),
              if (taskState.isTerminal) ...[
                const SizedBox(width: 8),
                TextButton(onPressed: taskCtrl.reset, child: const Text('Reset')),
              ],
            ],
          ),

          // ── Errors ───────────────────────────────────────────────────
          if (_pickError != null) ...[
            const SizedBox(height: 8),
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(children: [
                  const Icon(Icons.warning_amber),
                  const SizedBox(width: 8),
                  Expanded(child: Text(_pickError!)),
                ]),
              ),
            ),
          ],
          if (taskState.phase == VideoTaskPhase.error) ...[
            const SizedBox(height: 8),
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text('Error: ${taskState.errorDetail}',
                    style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            ),
          ],

          // ── Progress + info ──────────────────────────────────────────
          if (_pickedFileName != null) ...[
            const SizedBox(height: 8),
            Text('File: $_pickedFileName', style: Theme.of(context).textTheme.bodySmall),
          ],
          if (taskState.phase != VideoTaskPhase.idle) ...[
            const SizedBox(height: 8),
            _StatusBar(taskState: taskState),
          ],

          const SizedBox(height: 12),

          // ── Video player + plate log side by side ────────────────────
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Left: live annotated preview (boxes burned in) while
                // processing; falls back to raw playback otherwise.
                Expanded(
                  flex: 2,
                  child: Card(
                    clipBehavior: Clip.hardEdge,
                    color: Colors.black,
                    child: _VideoPreviewPanel(
                      taskState: taskState,
                      playback: _playback,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                // Right: live plate detection results
                Expanded(
                  flex: 1,
                  child: _PlateLogPanel(taskState: taskState),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Status bar ─────────────────────────────────────────────────────────────

class _StatusBar extends StatelessWidget {
  final VideoTaskState taskState;
  const _StatusBar({required this.taskState});

  @override
  Widget build(BuildContext context) {
    final progress = taskState.progressPercent;
    final label = switch (taskState.phase) {
      VideoTaskPhase.uploading => 'Uploading…',
      VideoTaskPhase.polling => 'Processing (plates detected every ${taskState.status?.status ?? "N"} frames)…',
      VideoTaskPhase.done => '✓ Done — ${taskState.status?.plateLog.length ?? 0} plates found',
      VideoTaskPhase.error => 'Error',
      VideoTaskPhase.cancelled => 'Cancelled',
      _ => '',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 4),
        if (progress == null)
          const LinearProgressIndicator()
        else
          LinearProgressIndicator(value: progress / 100),
        if (progress != null)
          Text('$progress%', style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}

// ── Video preview panel ──────────────────────────────────────────────────
// Plays the raw video smoothly (HTML5, native frame rate, single pass) and
// draws detection boxes as a Flutter overlay synced to playback time, so the
// overlay is live without making the video choppy.

class _VideoPreviewPanel extends StatefulWidget {
  final VideoTaskState taskState;
  final PlaybackController? playback;

  const _VideoPreviewPanel({required this.taskState, required this.playback});

  @override
  State<_VideoPreviewPanel> createState() => _VideoPreviewPanelState();
}

class _VideoPreviewPanelState extends State<_VideoPreviewPanel> {
  Timer? _ticker;
  double _t = 0.0; // current playback time (seconds)

  @override
  void initState() {
    super.initState();
    // Refresh the overlay ~30x/sec by reading the video's currentTime.
    // This does NOT touch the video itself, so playback stays smooth.
    _ticker = Timer.periodic(const Duration(milliseconds: 33), (_) {
      final pb = widget.playback;
      if (pb == null) return;
      final now = pb.currentTime;
      if ((now - _t).abs() > 0.001 && mounted) {
        setState(() => _t = now);
      }
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  /// Pick the most recent detections whose timestamp is at/just before the
  /// current playback position, within a short visibility window.
  List<EnhancedPlateLogEntry> _activeBoxes() {
    final log = widget.taskState.status?.plateLog ?? const [];
    if (log.isEmpty) return const [];

    // Find the largest frame-group time <= current time.
    const window = 1.5; // seconds a box stays visible after its timestamp
    final matches = <EnhancedPlateLogEntry>[];
    double? latestTime;
    for (final e in log) {
      if (e.timeSec <= _t + 0.05 && e.timeSec >= _t - window) {
        if (latestTime == null || e.timeSec > latestTime) {
          latestTime = e.timeSec;
        }
      }
    }
    if (latestTime == null) return const [];
    for (final e in log) {
      if ((e.timeSec - latestTime).abs() < 0.001) {
        matches.add(e);
      }
    }
    return matches;
  }

  @override
  Widget build(BuildContext context) {
    final playback = widget.playback;

    if (playback == null) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.video_library_outlined, size: 64, color: Colors.grey),
            SizedBox(height: 8),
            Text('Select a video to start',
                style: TextStyle(color: Colors.grey)),
          ],
        ),
      );
    }

    final boxes = _activeBoxes();

    return LayoutBuilder(
      builder: (context, constraints) {
        return Stack(
          fit: StackFit.expand,
          children: [
            platform_video.buildVideoWidget(playback),
            // Synced bounding-box overlay (boxes are normalized 0..1).
            if (boxes.isNotEmpty)
              IgnorePointer(
                child: CustomPaint(
                  painter: _BoxOverlayPainter(boxes),
                ),
              ),
            if (widget.taskState.phase == VideoTaskPhase.polling)
              const Positioned(top: 8, left: 8, child: _LiveBadge()),
          ],
        );
      },
    );
  }
}

/// Paints normalized detection boxes + plate labels over the video.
/// Note: assumes the video fills the paint area (objectFit: contain may letter-
/// box; boxes still track horizontally/vertically within the painted region).
class _BoxOverlayPainter extends CustomPainter {
  final List<EnhancedPlateLogEntry> boxes;
  _BoxOverlayPainter(this.boxes);

  @override
  void paint(Canvas canvas, Size size) {
    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..color = const Color(0xFF32FF64);

    for (final e in boxes) {
      if (e.bbox.length < 4) continue;
      final x1 = e.bbox[0] * size.width;
      final y1 = e.bbox[1] * size.height;
      final x2 = e.bbox[2] * size.width;
      final y2 = e.bbox[3] * size.height;
      final rect = Rect.fromLTRB(x1, y1, x2, y2);
      canvas.drawRect(rect, stroke);

      // Label background + text
      final label = e.persianDisplay.isNotEmpty ? e.persianDisplay : e.dtrbText;
      final tp = TextPainter(
        text: TextSpan(
          text: label,
          style: const TextStyle(
            color: Color(0xFF32FF64),
            fontSize: 14,
            fontWeight: FontWeight.bold,
          ),
        ),
        textDirection: TextDirection.rtl,
      )..layout();

      final labelY = (y1 - tp.height - 6).clamp(0.0, size.height);
      final bg = Paint()..color = const Color(0xCC000000);
      canvas.drawRect(
        Rect.fromLTWH(x1, labelY, tp.width + 10, tp.height + 4),
        bg,
      );
      tp.paint(canvas, Offset(x1 + 5, labelY + 2));
    }
  }

  @override
  bool shouldRepaint(covariant _BoxOverlayPainter old) =>
      old.boxes != boxes;
}

class _LiveBadge extends StatelessWidget {
  const _LiveBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: Colors.red.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(4),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.fiber_manual_record, size: 10, color: Colors.white),
          SizedBox(width: 4),
          Text('LIVE',
              style: TextStyle(
                  color: Colors.white,
                  fontSize: 11,
                  fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }
}

// ── Plate log panel ────────────────────────────────────────────────────────
// Requirements: 2.2, 2.3, 2.4

class _PlateLogPanel extends StatefulWidget {
  final VideoTaskState taskState;
  const _PlateLogPanel({required this.taskState});

  @override
  State<_PlateLogPanel> createState() => _PlateLogPanelState();
}

class _PlateLogPanelState extends State<_PlateLogPanel> {
  final ScrollController _scrollCtrl = ScrollController();
  int _lastLogLength = 0;
  bool _userScrolledAway = false;

  @override
  void initState() {
    super.initState();
    _scrollCtrl.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollCtrl.removeListener(_onScroll);
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scrollCtrl.hasClients) return;
    final maxScroll = _scrollCtrl.position.maxScrollExtent;
    final currentScroll = _scrollCtrl.offset;
    // User is "at bottom" if within 50 pixels of the end
    _userScrolledAway = (maxScroll - currentScroll) > 50;
  }

  @override
  void didUpdateWidget(covariant _PlateLogPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    final log = widget.taskState.status?.plateLog ?? [];
    if (log.length > _lastLogLength) {
      _lastLogLength = log.length;
      // Auto-scroll to bottom when new plates arrive (Req 2.3)
      // Only if user hasn't scrolled away
      if (!_userScrolledAway) {
        _scrollToBottom();
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final log = widget.taskState.status?.plateLog ?? [];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.credit_card, size: 18),
                const SizedBox(width: 6),
                Text('Plates Detected (${log.length})',
                    style: Theme.of(context).textTheme.labelLarge),
              ],
            ),
            const Divider(),
            Expanded(
              child: log.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.hourglass_empty,
                              size: 32, color: Colors.grey.shade400),
                          const SizedBox(height: 8),
                          const Text('Waiting for detections…',
                              style: TextStyle(color: Colors.grey)),
                          const SizedBox(height: 4),
                          Text(
                            'Plates will appear here as they are recognized',
                            style: TextStyle(
                                color: Colors.grey.shade500, fontSize: 11),
                            textAlign: TextAlign.center,
                          ),
                        ],
                      ),
                    )
                  : Stack(
                      children: [
                        ListView.builder(
                          controller: _scrollCtrl,
                          itemCount: log.length,
                          itemBuilder: (_, i) {
                            final entry = log[i];
                            return PlateDetailCard(entry: entry);
                          },
                        ),
                        // "Scroll to bottom" button when user has scrolled away
                        if (_userScrolledAway && log.isNotEmpty)
                          Positioned(
                            bottom: 8,
                            right: 8,
                            child: FloatingActionButton.small(
                              onPressed: () {
                                _userScrolledAway = false;
                                _scrollToBottom();
                              },
                              child: const Icon(Icons.arrow_downward, size: 18),
                            ),
                          ),
                      ],
                    ),
            ),
            if (widget.taskState.phase == VideoTaskPhase.done &&
                widget.taskState.outputMediaPath != null) ...[
              const Divider(),
              TextButton.icon(
                icon: const Icon(Icons.download),
                label: const Text('Download Processed Video'),
                onPressed: () {/* TODO: open /media/outputPath */},
              ),
            ],
          ],
        ),
      ),
    );
  }
}
