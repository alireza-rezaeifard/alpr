// lib/features/detection/rtsp_sub_view.dart
// Single RTSP stream detection sub-view.
// Requirements: 10.1–10.7

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/rtsp_task_model.dart';
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

class _LiveDetectionsWidget extends StatelessWidget {
  final RtspTaskStatus? status;
  const _LiveDetectionsWidget({this.status});

  @override
  Widget build(BuildContext context) {
    final lines = status?.liveDetections ?? <String>[];
    final history = status?.history ?? <PlateHistoryEntry>[];

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
              child: lines.isEmpty
                  ? const Center(
                      child: Text('No detections yet',
                          style: TextStyle(color: Colors.grey)))
                  : ListView.builder(
                      reverse: true,
                      itemCount: lines.length,
                      itemBuilder: (_, i) => Text(
                        lines[lines.length - 1 - i],
                        style: const TextStyle(fontSize: 11),
                      ),
                    ),
            ),
            if (history.isNotEmpty) ...[
              const Divider(),
              Text('History (${history.length})',
                  style: Theme.of(context).textTheme.labelSmall),
              ...history.take(5).map<Widget>((h) => Text(
                    '${h.dtrbText}  ×${h.count}',
                    style: const TextStyle(fontSize: 11),
                  )),
            ],
          ],
        ),
      ),
    );
  }
}
