// lib/features/detection/rtsp_sub_view.dart
// Single RTSP stream detection sub-view.
// Requirements: 10.1–10.7, 3.2, 3.3

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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
      setState(() => _skipError = 'Must be an integer between 1 and 1000');
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

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Input row ────────────────────────────────────────────────
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 3,
                child: TextField(
                  controller: _urlCtrl,
                  decoration: InputDecoration(
                    labelText: 'RTSP URL',
                    hintText: 'rtsp://192.168.1.1:554/stream',
                    errorText: _urlError,
                  ),
                  enabled: !state.isActive,
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: 100,
                child: TextField(
                  controller: _skipFramesCtrl,
                  decoration: InputDecoration(
                    labelText: 'Skip frames',
                    errorText: _skipError,
                  ),
                  keyboardType: TextInputType.number,
                  enabled: !state.isActive,
                ),
              ),
              const SizedBox(width: 12),
              if (!state.isActive)
                ElevatedButton.icon(
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Start'),
                  onPressed: () {
                    if (!_validateInputs()) return;
                    final url = _urlCtrl.text.trim();
                    final skip = int.parse(_skipFramesCtrl.text.trim());
                    controller.start(url, skip);
                  },
                )
              else
                ElevatedButton.icon(
                  icon: const Icon(Icons.stop),
                  label: const Text('Stop'),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                  onPressed: controller.stop,
                ),
            ],
          ),

          const SizedBox(height: 16),

          // ── Error display ────────────────────────────────────────────
          if (state.phase == RtspPhase.error)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    const Icon(Icons.error_outline),
                    const SizedBox(width: 8),
                    Expanded(child: Text(state.errorMessage ?? 'Stream error')),
                    TextButton(
                        onPressed: controller.reset, child: const Text('Reset')),
                  ],
                ),
              ),
            ),

          // ── Annotated frame ──────────────────────────────────────────
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Left: annotated frame
                Expanded(
                  flex: 2,
                  child: Card(
                    child: _AnnotatedFrameWidget(
                      annotated: state.status?.annotated,
                      isLoading: state.phase == RtspPhase.starting,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                // Right: live detection lines + history
                Expanded(
                  flex: 1,
                  child: _LiveDetectionsWidget(status: state.status),
                ),
              ],
            ),
          ),
        ],
      ),
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
      return const Center(child: CircularProgressIndicator());
    }
    if (annotated == null || annotated!.isEmpty) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.videocam_off, size: 48, color: Colors.grey),
            SizedBox(height: 8),
            Text('Waiting for stream…', style: TextStyle(color: Colors.grey)),
          ],
        ),
      );
    }
    try {
      // Decode base64 data URL: "data:image/jpeg;base64,<data>"
      final comma = annotated!.indexOf(',');
      final b64 = comma >= 0 ? annotated!.substring(comma + 1) : annotated!;
      final bytes = base64Decode(b64);
      return Image.memory(bytes, fit: BoxFit.contain);
    } catch (_) {
      return const Center(
        child: Icon(Icons.broken_image, size: 48, color: Colors.grey),
      );
    }
  }
}

// ── Live detections panel ────────────────────────────────────────────────
// Requirements: 3.2, 3.3

class _LiveDetectionsWidget extends StatefulWidget {
  final RtspTaskStatus? status;
  const _LiveDetectionsWidget({this.status});

  @override
  State<_LiveDetectionsWidget> createState() => _LiveDetectionsWidgetState();
}

class _LiveDetectionsWidgetState extends State<_LiveDetectionsWidget> {
  final ScrollController _liveScrollCtrl = ScrollController();
  final ScrollController _historyScrollCtrl = ScrollController();
  int _lastLiveCount = 0;
  int _lastHistoryCount = 0;
  bool _liveUserScrolledAway = false;
  bool _historyUserScrolledAway = false;

  @override
  void initState() {
    super.initState();
    _liveScrollCtrl.addListener(_onLiveScroll);
    _historyScrollCtrl.addListener(_onHistoryScroll);
  }

  @override
  void dispose() {
    _liveScrollCtrl.removeListener(_onLiveScroll);
    _historyScrollCtrl.removeListener(_onHistoryScroll);
    _liveScrollCtrl.dispose();
    _historyScrollCtrl.dispose();
    super.dispose();
  }

  void _onLiveScroll() {
    if (!_liveScrollCtrl.hasClients) return;
    final maxScroll = _liveScrollCtrl.position.maxScrollExtent;
    final currentScroll = _liveScrollCtrl.offset;
    _liveUserScrolledAway = (maxScroll - currentScroll) > 50;
  }

  void _onHistoryScroll() {
    if (!_historyScrollCtrl.hasClients) return;
    final maxScroll = _historyScrollCtrl.position.maxScrollExtent;
    final currentScroll = _historyScrollCtrl.offset;
    _historyUserScrolledAway = (maxScroll - currentScroll) > 50;
  }

  @override
  void didUpdateWidget(covariant _LiveDetectionsWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    final lines = widget.status?.liveDetections ?? <String>[];
    final history = widget.status?.history ?? <EnhancedRtspHistoryEntry>[];

    // Auto-scroll live detections (Req 3.2)
    if (lines.length > _lastLiveCount && !_liveUserScrolledAway) {
      _lastLiveCount = lines.length;
      _scrollToBottom(_liveScrollCtrl);
    } else {
      _lastLiveCount = lines.length;
    }

    // Auto-scroll history when new entries arrive
    if (history.length > _lastHistoryCount && !_historyUserScrolledAway) {
      _lastHistoryCount = history.length;
      _scrollToBottom(_historyScrollCtrl);
    } else {
      _lastHistoryCount = history.length;
    }
  }

  void _scrollToBottom(ScrollController ctrl) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (ctrl.hasClients) {
        ctrl.animateTo(
          ctrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  /// Converts an EnhancedRtspHistoryEntry to an EnhancedPlateLogEntry
  /// so it can be displayed with PlateDetailCard.
  EnhancedPlateLogEntry _adaptRtspEntry(EnhancedRtspHistoryEntry h) {
    return EnhancedPlateLogEntry(
      frame: 0,
      time: h.lastSeen,
      timeSec: 0.0,
      plateText: h.yoloText,
      dtrbText: h.dtrbText,
      confidence: h.confidence,
      bbox: const [0, 0, 0, 0],
      persianDisplay: h.persianDisplay,
      isValidIranian: h.isValidIranian,
      metadata: h.metadata,
    );
  }

  @override
  Widget build(BuildContext context) {
    final lines = widget.status?.liveDetections ?? <String>[];
    final history = widget.status?.history ?? <EnhancedRtspHistoryEntry>[];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Live Detections',
                style: Theme.of(context).textTheme.labelLarge),
            const Divider(),
            Expanded(
              flex: 1,
              child: lines.isEmpty
                  ? const Center(
                      child: Text('No detections yet',
                          style: TextStyle(color: Colors.grey)))
                  : Stack(
                      children: [
                        ListView.builder(
                          controller: _liveScrollCtrl,
                          itemCount: lines.length,
                          itemBuilder: (_, i) => Text(
                            lines[i],
                            style: const TextStyle(fontSize: 11),
                          ),
                        ),
                        if (_liveUserScrolledAway)
                          Positioned(
                            bottom: 4,
                            right: 4,
                            child: FloatingActionButton.small(
                              heroTag: 'live_scroll_btn',
                              onPressed: () {
                                _liveUserScrolledAway = false;
                                _scrollToBottom(_liveScrollCtrl);
                              },
                              child:
                                  const Icon(Icons.arrow_downward, size: 16),
                            ),
                          ),
                      ],
                    ),
            ),
            if (history.isNotEmpty) ...[
              const Divider(),
              Text('History (${history.length})',
                  style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 4),
              Expanded(
                flex: 2,
                child: Stack(
                  children: [
                    ListView.builder(
                      controller: _historyScrollCtrl,
                      itemCount: history.length,
                      itemBuilder: (_, i) {
                        final h = history[i];
                        final adapted = _adaptRtspEntry(h);
                        return _RtspPlateCardWithBadge(
                          entry: adapted,
                          count: h.count,
                        );
                      },
                    ),
                    if (_historyUserScrolledAway)
                      Positioned(
                        bottom: 4,
                        right: 4,
                        child: FloatingActionButton.small(
                          heroTag: 'history_scroll_btn',
                          onPressed: () {
                            _historyUserScrolledAway = false;
                            _scrollToBottom(_historyScrollCtrl);
                          },
                          child: const Icon(Icons.arrow_downward, size: 16),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Wraps PlateDetailCard with a count badge overlay for repeated RTSP detections (Req 3.3).
class _RtspPlateCardWithBadge extends StatelessWidget {
  final EnhancedPlateLogEntry entry;
  final int count;

  const _RtspPlateCardWithBadge({
    required this.entry,
    required this.count,
  });

  @override
  Widget build(BuildContext context) {
    final card = PlateDetailCard(entry: entry);

    if (count <= 1) return card;

    // Show count badge for repeated detections
    return Stack(
      children: [
        card,
        Positioned(
          top: 4,
          right: 4,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primary,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              '×$count',
              style: TextStyle(
                color: Theme.of(context).colorScheme.onPrimary,
                fontSize: 11,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ),
      ],
    );
  }
}
