// lib/features/detection/video_sub_view.dart
// Video detection: local playback at 1.0x + independent backend polling.
// Requirements: 8.3, 9.2, 9.3

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import '../../shared/playback/playback_controller.dart';
import '../../shared/playback/video_widget.dart';
import 'video_task_controller.dart';

class VideoSubView extends ConsumerStatefulWidget {
  const VideoSubView({super.key});

  @override
  ConsumerState<VideoSubView> createState() => _VideoSubViewState();
}

class _VideoSubViewState extends ConsumerState<VideoSubView> {
  final _skipFramesCtrl = TextEditingController(text: '30');
  String? _skipError;
  PlaybackController? _playback;
  String? _pickedFileName;
  String? _pickError;
  bool _picking = false;

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
          withData: true, // ensures bytes are loaded on web
        );
      } catch (_) {
        // Some browsers reject custom/video filters — fall back to any file
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

      // On web, accessing file.path throws — only use bytes
      String? path;
      try {
        path = file.path;
      } catch (_) {
        path = null; // web: path is not available
      }

      if (bytes == null && (path == null || path.isEmpty)) {
        setState(() {
          _picking = false;
          _pickError = 'Could not read the selected file bytes.';
        });
        return;
      }

      // Build the playback controller and load the source BEFORE rebuilding,
      // so the video widget has its bytes/path ready on first render.
      final controller = PlaybackController();
      if (path != null && path.isNotEmpty) {
        await controller.open(path);
      }
      if (bytes != null) {
        await controller.openBytes(bytes, 'video/mp4');
      }
      controller.play();

      // Now swap in the ready controller and trigger a rebuild (Req 8.3)
      _playback?.dispose();
      setState(() {
        _pickedFileName = name;
        _playback = controller;
        _picking = false;
      });

      // Submit to backend for processing (independent of playback)
      if (bytes != null) {
        await ref.read(videoTaskControllerProvider.notifier).submit(
              bytes.toList(),
              name,
              skipFrames: skip,
            );
      } else {
        setState(() => _pickError =
            'On Windows desktop the file path is used; backend upload needs file bytes. Use the web build for full upload support.');
      }
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
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
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
                TextButton(
                  onPressed: taskCtrl.reset,
                  child: const Text('Reset'),
                ),
              ],
            ],
          ),

          // ── Pick error / filename ─────────────────────────────────────
          if (_pickError != null) ...[
            const SizedBox(height: 8),
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    const Icon(Icons.warning_amber),
                    const SizedBox(width: 8),
                    Expanded(child: Text(_pickError!)),
                  ],
                ),
              ),
            ),
          ],
          if (_pickedFileName != null) ...[
            const SizedBox(height: 8),
            Text('Selected: $_pickedFileName',
                style: Theme.of(context).textTheme.bodySmall),
          ],

          // ── Status + progress ─────────────────────────────────────────
          if (taskState.phase != VideoTaskPhase.idle) ...[
            const SizedBox(height: 12),
            _StatusBar(taskState: taskState),
          ],

          // ── Error banner (persists until success per Req 8.10) ────────
          if (taskState.phase == VideoTaskPhase.error) ...[
            const SizedBox(height: 8),
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Error: ${taskState.errorDetail}',
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error),
                    ),
                    if (taskState.hasPartialOutput &&
                        taskState.outputMediaPath != null) ...[
                      const SizedBox(height: 4),
                      const Text('Partial output available below.',
                          style: TextStyle(fontSize: 12)),
                    ],
                  ],
                ),
              ),
            ),
          ],

          const SizedBox(height: 12),

          // ── Video + plate log ────────────────────────────────────────
          Expanded(
            child: Row(
              children: [
                // Left: local video player (Req 8.3 — 1.0x, independent)
                Expanded(
                  flex: 2,
                  child: _playback != null
                      ? Card(
                          clipBehavior: Clip.hardEdge,
                          child: VideoWidget(controller: _playback!),
                        )
                      : const Card(
                          child: Center(
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.video_library_outlined,
                                    size: 64, color: Colors.grey),
                                SizedBox(height: 8),
                                Text('No video selected',
                                    style: TextStyle(color: Colors.grey)),
                              ],
                            ),
                          ),
                        ),
                ),
                const SizedBox(width: 12),
                // Right: running plate log
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
      VideoTaskPhase.polling => taskState.status?.status ?? 'Processing…',
      VideoTaskPhase.done => 'Done',
      VideoTaskPhase.error => 'Error',
      VideoTaskPhase.cancelled => 'Cancelled',
      _ => '',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 4),
        // Req 8.11 — indeterminate when total_frames==0 or queued/opening
        if (progress == null)
          const LinearProgressIndicator()
        else
          LinearProgressIndicator(value: progress / 100),
        if (progress != null)
          Text(
            '$progress%',
            style: Theme.of(context).textTheme.bodySmall,
          ),
      ],
    );
  }
}

// ── Plate log panel ────────────────────────────────────────────────────────

class _PlateLogPanel extends StatelessWidget {
  final VideoTaskState taskState;
  const _PlateLogPanel({required this.taskState});

  @override
  Widget build(BuildContext context) {
    final log = taskState.status?.plateLog ?? [];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Plate Log (${log.length})',
                style: Theme.of(context).textTheme.labelLarge),
            const Divider(),
            Expanded(
              child: log.isEmpty
                  ? const Center(
                      child: Text('No plates yet',
                          style: TextStyle(color: Colors.grey)))
                  : ListView.builder(
                      reverse: true,
                      itemCount: log.length,
                      itemBuilder: (_, i) {
                        final entry = log[log.length - 1 - i];
                        return ListTile(
                          dense: true,
                          title: Text(entry.dtrbText,
                              style: const TextStyle(fontSize: 12)),
                          subtitle: Text(
                              'f${entry.frame} @ ${entry.time}',
                              style: const TextStyle(fontSize: 10)),
                          trailing: Text(
                              '${(entry.confidence * 100).toStringAsFixed(0)}%',
                              style: const TextStyle(fontSize: 11)),
                        );
                      },
                    ),
            ),
            // Done: output link
            if (taskState.phase == VideoTaskPhase.done &&
                taskState.outputMediaPath != null) ...[
              const Divider(),
              TextButton.icon(
                icon: const Icon(Icons.download),
                label: const Text('View Output'),
                onPressed: () {/* open outputMediaPath via backend /media */},
              ),
            ],
          ],
        ),
      ),
    );
  }
}
