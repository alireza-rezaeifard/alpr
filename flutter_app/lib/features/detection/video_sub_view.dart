// lib/features/detection/video_sub_view.dart
// Modern video detection sub-view with clean layout.

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import '../../shared/app_icons.dart';
import '../../shared/playback/playback_controller.dart';
import '../../shared/widgets/plate_detail_card.dart';
import '../../data/models/enhanced_plate_log_entry.dart';
import 'video_task_controller.dart';

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

    setState(() { _pickError = null; _picking = true; });

    try {
      FilePickerResult? result;
      try {
        result = await FilePicker.platform.pickFiles(type: FileType.video, withData: true);
      } catch (_) {
        result = await FilePicker.platform.pickFiles(type: FileType.any, withData: true);
      }

      if (result == null || result.files.isEmpty) {
        setState(() => _picking = false);
        return;
      }

      final file = result.files.first;
      final bytes = file.bytes;
      final name = file.name;

      if (bytes == null) {
        setState(() { _picking = false; _pickError = 'Could not read file bytes.'; });
        return;
      }

      final controller = PlaybackController();
      await controller.openBytes(bytes, 'video/mp4');
      controller.play();

      _playback?.dispose();
      setState(() { _pickedFileName = name; _playback = controller; _picking = false; });

      await ref.read(videoTaskControllerProvider.notifier).submit(
            bytes, name, skipFrames: skip);
    } catch (e) {
      setState(() { _picking = false; _pickError = 'Failed to load video: $e'; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final taskState = ref.watch(videoTaskControllerProvider);
    final taskCtrl = ref.read(videoTaskControllerProvider.notifier);
    final isActive = taskState.phase == VideoTaskPhase.uploading ||
        taskState.phase == VideoTaskPhase.polling;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Controls
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF111113),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white.withOpacity(0.06)),
          ),
          child: Row(
            children: [
              SizedBox(
                width: 100,
                child: TextField(
                  controller: _skipFramesCtrl,
                  style: const TextStyle(fontSize: 13, color: Colors.white),
                  decoration: InputDecoration(
                    labelText: 'Skip frames',
                    labelStyle: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.4)),
                    errorText: _skipError,
                    isDense: true,
                    filled: true,
                    fillColor: Colors.white.withOpacity(0.04),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8),
                        borderSide: BorderSide(color: Colors.white.withOpacity(0.08))),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8),
                        borderSide: BorderSide(color: Colors.white.withOpacity(0.08))),
                  ),
                  keyboardType: TextInputType.number,
                  enabled: !isActive,
                ),
              ),
              const SizedBox(width: 12),
              _ModernButton(
                icon: _picking ? AppIcons.loader2 : AppIcons.upload,
                label: _picking ? 'Loading…' : 'Select Video',
                onTap: (isActive || _picking) ? null : _pickAndSubmit,
              ),
              const SizedBox(width: 8),
              if (isActive)
                _ModernButton(icon: AppIcons.square, label: 'Stop', danger: true, onTap: taskCtrl.stop),
              if (taskState.isTerminal)
                _ModernButton(icon: AppIcons.refreshCw, label: 'Reset', onTap: taskCtrl.reset),
              if (_pickedFileName != null) ...[
                const SizedBox(width: 16),
                Icon(AppIcons.file, size: 14, color: Colors.white.withOpacity(0.4)),
                const SizedBox(width: 4),
                Text(_pickedFileName!, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.5))),
              ],
            ],
          ),
        ),

        // Errors
        if (_pickError != null) ...[
          const SizedBox(height: 8),
          _ErrorBanner(message: _pickError!),
        ],
        if (taskState.phase == VideoTaskPhase.error) ...[
          const SizedBox(height: 8),
          _ErrorBanner(message: taskState.errorDetail ?? 'Error occurred'),
        ],

        // Progress
        if (taskState.phase != VideoTaskPhase.idle) ...[
          const SizedBox(height: 12),
          _StatusBar(taskState: taskState),
        ],

        const SizedBox(height: 12),

        // Video + plates side by side
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                flex: 2,
                child: Container(
                  decoration: BoxDecoration(
                    color: Colors.black,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.white.withOpacity(0.06)),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: _VideoPreviewPanel(taskState: taskState, playback: _playback),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 1,
                child: _PlateLogPanel(taskState: taskState),
              ),
            ],
          ),
        ),
      ],
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
      VideoTaskPhase.polling => 'Processing…',
      VideoTaskPhase.done => '✓ Done — ${taskState.status?.plateLog.length ?? 0} plates found',
      VideoTaskPhase.error => 'Error',
      VideoTaskPhase.cancelled => 'Cancelled',
      _ => '',
    };

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.7))),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: progress == null
                ? LinearProgressIndicator(minHeight: 3, backgroundColor: Colors.white.withOpacity(0.05),
                    valueColor: const AlwaysStoppedAnimation(Color(0xFF3B82F6)))
                : LinearProgressIndicator(value: progress / 100, minHeight: 3,
                    backgroundColor: Colors.white.withOpacity(0.05),
                    valueColor: const AlwaysStoppedAnimation(Color(0xFF3B82F6))),
          ),
          if (progress != null) ...[
            const SizedBox(height: 4),
            Text('$progress%', style: TextStyle(fontSize: 10, color: Colors.white.withOpacity(0.4))),
          ],
        ],
      ),
    );
  }
}

// ── Video preview panel ────────────────────────────────────────────────────

class _VideoPreviewPanel extends StatefulWidget {
  final VideoTaskState taskState;
  final PlaybackController? playback;
  const _VideoPreviewPanel({required this.taskState, required this.playback});

  @override
  State<_VideoPreviewPanel> createState() => _VideoPreviewPanelState();
}

class _VideoPreviewPanelState extends State<_VideoPreviewPanel> {
  Timer? _ticker;
  double _t = 0.0;

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(const Duration(milliseconds: 33), (_) {
      final pb = widget.playback;
      if (pb == null) return;
      final now = pb.currentTime;
      if ((now - _t).abs() > 0.001 && mounted) setState(() => _t = now);
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  List<EnhancedPlateLogEntry> _activeBoxes() {
    final log = widget.taskState.status?.plateLog ?? const [];
    if (log.isEmpty) return const [];

    double? bestTime;
    for (final e in log) {
      if (e.timeSec <= _t + 0.1) {
        if (bestTime == null || e.timeSec > bestTime) bestTime = e.timeSec;
      }
    }
    if (bestTime == null) {
      for (final e in log) {
        if (bestTime == null || e.timeSec > bestTime) bestTime = e.timeSec;
      }
    }
    if (bestTime == null) return const [];
    return log.where((e) => (e.timeSec - bestTime!).abs() < 0.5).toList();
  }

  @override
  Widget build(BuildContext context) {
    final playback = widget.playback;

    if (playback == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(AppIcons.video, size: 48, color: Colors.white.withOpacity(0.15)),
            const SizedBox(height: 12),
            Text('Select a video to start', style: TextStyle(color: Colors.white.withOpacity(0.3))),
          ],
        ),
      );
    }

    final boxes = _activeBoxes();

    return Stack(
      fit: StackFit.expand,
      children: [
        platform_video.buildVideoWidget(playback),
        if (boxes.isNotEmpty)
          IgnorePointer(child: CustomPaint(painter: _BoxOverlayPainter(boxes))),
        if (widget.taskState.phase == VideoTaskPhase.polling)
          Positioned(top: 8, left: 8, child: _LiveBadge()),
      ],
    );
  }
}

class _BoxOverlayPainter extends CustomPainter {
  final List<EnhancedPlateLogEntry> boxes;
  _BoxOverlayPainter(this.boxes);

  @override
  void paint(Canvas canvas, Size size) {
    final plateStroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5
      ..color = const Color(0xFF10B981);

    final carStroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5
      ..color = const Color(0xFF3B82F6);

    for (final e in boxes) {
      // Car bounding box (blue)
      if (e.carBbox != null && e.carBbox!.length >= 4) {
        final carRect = Rect.fromLTRB(
          e.carBbox![0] * size.width, e.carBbox![1] * size.height,
          e.carBbox![2] * size.width, e.carBbox![3] * size.height);
        canvas.drawRRect(RRect.fromRectAndRadius(carRect, const Radius.circular(3)), carStroke);
      }

      // Plate bounding box (green)
      if (e.bbox.length < 4) continue;
      final rect = Rect.fromLTRB(
        e.bbox[0] * size.width, e.bbox[1] * size.height,
        e.bbox[2] * size.width, e.bbox[3] * size.height);
      canvas.drawRRect(RRect.fromRectAndRadius(rect, const Radius.circular(3)), plateStroke);

      final label = e.persianDisplay.isNotEmpty ? e.persianDisplay : e.dtrbText;
      final tp = TextPainter(
        text: TextSpan(text: label, style: const TextStyle(
          color: Color(0xFF10B981), fontSize: 12, fontWeight: FontWeight.bold)),
        textDirection: TextDirection.rtl,
      )..layout();
      final labelY = (rect.top - tp.height - 4).clamp(0.0, size.height);
      canvas.drawRRect(
        RRect.fromRectAndRadius(Rect.fromLTWH(rect.left, labelY, tp.width + 8, tp.height + 4), const Radius.circular(3)),
        Paint()..color = const Color(0xDD000000));
      tp.paint(canvas, Offset(rect.left + 4, labelY + 2));
    }
  }

  @override
  bool shouldRepaint(covariant _BoxOverlayPainter old) => old.boxes != boxes;
}

class _LiveBadge extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFFEF4444).withOpacity(0.9),
        borderRadius: BorderRadius.circular(4),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(AppIcons.radio, size: 10, color: Colors.white),
          SizedBox(width: 4),
          Text('LIVE', style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }
}

// ── Plate log panel ────────────────────────────────────────────────────────

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
    _userScrolledAway = (_scrollCtrl.position.maxScrollExtent - _scrollCtrl.offset) > 50;
  }

  @override
  void didUpdateWidget(covariant _PlateLogPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    final log = widget.taskState.status?.plateLog ?? [];
    if (log.length > _lastLogLength) {
      _lastLogLength = log.length;
      if (!_userScrolledAway) _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(_scrollCtrl.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final log = widget.taskState.status?.plateLog ?? [];

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Icon(AppIcons.creditCard, size: 14, color: Colors.white.withOpacity(0.4)),
                const SizedBox(width: 6),
                Text('Plates (${log.length})', style: TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w500, color: Colors.white.withOpacity(0.7))),
              ],
            ),
          ),
          Divider(height: 1, color: Colors.white.withOpacity(0.04)),
          Expanded(
            child: log.isEmpty
                ? Center(child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(AppIcons.clock, size: 24, color: Colors.white.withOpacity(0.15)),
                      const SizedBox(height: 8),
                      Text('Waiting for detections…',
                          style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.3))),
                    ],
                  ))
                : ListView.builder(
                    controller: _scrollCtrl,
                    padding: const EdgeInsets.all(8),
                    itemCount: log.length,
                    itemBuilder: (_, i) => PlateDetailCard(entry: log[i]),
                  ),
          ),
        ],
      ),
    );
  }
}

// ── Shared widgets ─────────────────────────────────────────────────────────

class _ModernButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool danger;
  const _ModernButton({required this.icon, required this.label, this.onTap, this.danger = false});

  @override
  Widget build(BuildContext context) {
    final color = danger ? const Color(0xFFEF4444) : const Color(0xFF3B82F6);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: onTap != null ? color.withOpacity(0.1) : Colors.white.withOpacity(0.02),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: onTap != null ? color.withOpacity(0.2) : Colors.white.withOpacity(0.04)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: onTap != null ? color : Colors.white.withOpacity(0.3)),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500,
                color: onTap != null ? color : Colors.white.withOpacity(0.3))),
          ],
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;
  const _ErrorBanner({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFEF4444).withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.2)),
      ),
      child: Row(
        children: [
          const Icon(AppIcons.alertCircle, size: 14, color: Color(0xFFEF4444)),
          const SizedBox(width: 8),
          Expanded(child: Text(message, style: const TextStyle(fontSize: 12, color: Color(0xFFEF4444)))),
        ],
      ),
    );
  }
}
