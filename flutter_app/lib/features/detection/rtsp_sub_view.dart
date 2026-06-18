// lib/features/detection/rtsp_sub_view.dart
// Modern single RTSP stream detection sub-view.

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../shared/app_icons.dart';
import '../../data/models/rtsp_task_model.dart';
import '../../data/models/enhanced_rtsp_history_entry.dart';
import '../../data/models/enhanced_plate_log_entry.dart';
import '../../shared/widgets/plate_detail_card.dart';
import 'rtsp_poll_controller.dart';

class RtspSubView extends ConsumerStatefulWidget {
  const RtspSubView({super.key});

  @override
  ConsumerState<RtspSubView> createState() => _RtspSubViewState();
}

class _RtspSubViewState extends ConsumerState<RtspSubView> {
  final _urlCtrl = TextEditingController();
  final _skipFramesCtrl = TextEditingController(text: '15');
  String? _urlError;
  String? _skipError;

  @override
  void dispose() {
    _urlCtrl.dispose();
    _skipFramesCtrl.dispose();
    super.dispose();
  }

  bool _validateInputs() {
    bool ok = true;
    final url = _urlCtrl.text.trim();
    if (url.isEmpty || !url.startsWith('rtsp://')) {
      setState(() => _urlError = 'URL must start with rtsp://');
      ok = false;
    } else {
      setState(() => _urlError = null);
    }
    final skipRaw = int.tryParse(_skipFramesCtrl.text.trim());
    if (skipRaw == null || skipRaw < 1 || skipRaw > 1000) {
      setState(() => _skipError = 'Must be 1–1000');
      ok = false;
    } else {
      setState(() => _skipError = null);
    }
    return ok;
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(rtspPollControllerProvider);
    final controller = ref.read(rtspPollControllerProvider.notifier);

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
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 3,
                child: TextField(
                  controller: _urlCtrl,
                  style: const TextStyle(fontSize: 13, color: Colors.white),
                  decoration: InputDecoration(
                    labelText: 'RTSP URL',
                    hintText: 'rtsp://192.168.1.1:554/stream',
                    errorText: _urlError,
                    prefixIcon: Icon(AppIcons.radio, size: 16, color: Colors.white.withOpacity(0.4)),
                  ),
                  enabled: !state.isActive,
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: 100,
                child: TextField(
                  controller: _skipFramesCtrl,
                  style: const TextStyle(fontSize: 13, color: Colors.white),
                  decoration: InputDecoration(
                    labelText: 'Skip frames',
                    errorText: _skipError,
                  ),
                  keyboardType: TextInputType.number,
                  enabled: !state.isActive,
                ),
              ),
              const SizedBox(width: 12),
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: !state.isActive
                    ? _ModernButton(
                        icon: AppIcons.play, label: 'Start',
                        onTap: () {
                          if (!_validateInputs()) return;
                          controller.start(_urlCtrl.text.trim(), int.parse(_skipFramesCtrl.text.trim()));
                        })
                    : _ModernButton(icon: AppIcons.square, label: 'Stop', danger: true, onTap: controller.stop),
              ),
            ],
          ),
        ),

        const SizedBox(height: 12),

        // Error
        if (state.phase == RtspPhase.error)
          Container(
            padding: const EdgeInsets.all(10),
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              color: const Color(0xFFEF4444).withOpacity(0.1),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.2)),
            ),
            child: Row(
              children: [
                const Icon(AppIcons.alertCircle, size: 14, color: Color(0xFFEF4444)),
                const SizedBox(width: 8),
                Expanded(child: Text(state.errorMessage ?? 'Stream error',
                    style: const TextStyle(fontSize: 12, color: Color(0xFFEF4444)))),
                TextButton(onPressed: controller.reset, child: const Text('Reset', style: TextStyle(fontSize: 11))),
              ],
            ),
          ),

        // Content
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Annotated frame
              Expanded(
                flex: 2,
                child: Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFF111113),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.white.withOpacity(0.06)),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: _AnnotatedFrameWidget(
                    annotated: state.status?.annotated,
                    isLoading: state.phase == RtspPhase.starting,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              // Live detections
              Expanded(
                flex: 1,
                child: _LiveDetectionsWidget(status: state.status),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// ── Annotated frame ─────────────────────────────────────────────────────

class _AnnotatedFrameWidget extends StatelessWidget {
  final String? annotated;
  final bool isLoading;
  const _AnnotatedFrameWidget({this.annotated, this.isLoading = false});

  @override
  Widget build(BuildContext context) {
    if (isLoading) {
      return Center(child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white.withOpacity(0.3)));
    }
    if (annotated == null || annotated!.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(AppIcons.camera, size: 48, color: Colors.white.withOpacity(0.12)),
            const SizedBox(height: 12),
            Text('Waiting for stream…', style: TextStyle(color: Colors.white.withOpacity(0.3))),
          ],
        ),
      );
    }
    try {
      final comma = annotated!.indexOf(',');
      final b64 = comma >= 0 ? annotated!.substring(comma + 1) : annotated!;
      final bytes = base64Decode(b64);
      return Image.memory(bytes, fit: BoxFit.contain, gaplessPlayback: true);
    } catch (_) {
      return Center(child: Icon(AppIcons.imageOff, size: 48, color: Colors.white.withOpacity(0.2)));
    }
  }
}

// ── Live detections ──────────────────────────────────────────────────────

class _LiveDetectionsWidget extends StatefulWidget {
  final RtspTaskStatus? status;
  const _LiveDetectionsWidget({this.status});

  @override
  State<_LiveDetectionsWidget> createState() => _LiveDetectionsWidgetState();
}

class _LiveDetectionsWidgetState extends State<_LiveDetectionsWidget> {
  final ScrollController _historyScrollCtrl = ScrollController();
  int _lastHistoryCount = 0;
  bool _userScrolledAway = false;

  @override
  void initState() {
    super.initState();
    _historyScrollCtrl.addListener(_onScroll);
  }

  @override
  void dispose() {
    _historyScrollCtrl.removeListener(_onScroll);
    _historyScrollCtrl.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_historyScrollCtrl.hasClients) return;
    _userScrolledAway = (_historyScrollCtrl.position.maxScrollExtent - _historyScrollCtrl.offset) > 50;
  }

  @override
  void didUpdateWidget(covariant _LiveDetectionsWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    final history = widget.status?.history ?? <EnhancedRtspHistoryEntry>[];
    if (history.length > _lastHistoryCount && !_userScrolledAway) {
      _lastHistoryCount = history.length;
      _scrollToBottom();
    } else {
      _lastHistoryCount = history.length;
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_historyScrollCtrl.hasClients) {
        _historyScrollCtrl.animateTo(_historyScrollCtrl.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
      }
    });
  }

  EnhancedPlateLogEntry _adaptRtspEntry(EnhancedRtspHistoryEntry h) {
    return EnhancedPlateLogEntry(
      frame: 0, time: h.lastSeen, timeSec: 0.0,
      plateText: h.yoloText, dtrbText: h.dtrbText,
      confidence: h.confidence, bbox: const [0, 0, 0, 0],
      persianDisplay: h.persianDisplay,
      isValidIranian: h.isValidIranian, metadata: h.metadata,
      carColor: h.carColor, carType: h.carType, city: h.city,
    );
  }

  @override
  Widget build(BuildContext context) {
    final lines = widget.status?.liveDetections ?? <String>[];
    final history = widget.status?.history ?? <EnhancedRtspHistoryEntry>[];

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
                Icon(AppIcons.radio, size: 14, color: Colors.white.withOpacity(0.4)),
                const SizedBox(width: 6),
                Text('Live Detections', style: TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w500, color: Colors.white.withOpacity(0.7))),
              ],
            ),
          ),
          Divider(height: 1, color: Colors.white.withOpacity(0.04)),
          // Live lines
          if (lines.isNotEmpty)
            Container(
              height: 60,
              padding: const EdgeInsets.all(8),
              child: ListView.builder(
                itemCount: lines.length,
                itemBuilder: (_, i) => Text(lines[i],
                    style: TextStyle(fontSize: 10, color: Colors.white.withOpacity(0.5), fontFamily: 'monospace')),
              ),
            ),
          if (lines.isNotEmpty) Divider(height: 1, color: Colors.white.withOpacity(0.04)),
          // History
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: Text('History (${history.length})', style: TextStyle(
              fontSize: 12, fontWeight: FontWeight.w500, color: Colors.white.withOpacity(0.5))),
          ),
          Expanded(
            child: history.isEmpty
                ? Center(child: Text('No detections yet',
                    style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.3))))
                : ListView.builder(
                    controller: _historyScrollCtrl,
                    padding: const EdgeInsets.all(8),
                    itemCount: history.length,
                    itemBuilder: (_, i) {
                      final adapted = _adaptRtspEntry(history[i]);
                      return PlateDetailCard(entry: adapted);
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

// ── Shared button ──────────────────────────────────────────────────────────

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
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withOpacity(0.3)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: color),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500, color: color)),
          ],
        ),
      ),
    );
  }
}
