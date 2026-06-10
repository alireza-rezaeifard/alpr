// lib/features/cameras/camera_live_monitor.dart
// Dynamic multi-camera live monitoring page.
// User selects which cameras to display in a configurable grid.
// Shows live annotated frames (with plate box overlays) + detected plates
// rendered in colored Iranian plate templates below each camera.

import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../data/models/camera_model.dart';
import '../../data/models/enhanced_rtsp_history_entry.dart';
import '../../data/models/plate_metadata_model.dart';
import 'camera_poll_controller.dart';
import 'cameras_view.dart' show cameraListProvider;

// ── Entry point: opens camera selector then monitor ──
class CameraLiveMonitor extends ConsumerStatefulWidget {
  const CameraLiveMonitor({super.key});

  @override
  ConsumerState<CameraLiveMonitor> createState() => _CameraLiveMonitorState();
}

class _CameraLiveMonitorState extends ConsumerState<CameraLiveMonitor> {
  List<CameraModel> _selectedCameras = [];
  int _columns = 2;

  @override
  Widget build(BuildContext context) {
    final camerasAsync = ref.watch(cameraListProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(_selectedCameras.isEmpty
            ? 'Live Monitor'
            : 'Monitoring ${_selectedCameras.length} Cameras'),
        actions: [
          // Column count selector
          IconButton(
            icon: const Icon(Icons.grid_view),
            tooltip: 'Grid layout',
            onPressed: _showLayoutPicker,
          ),
          // Camera selector
          IconButton(
            icon: const Icon(Icons.video_library),
            tooltip: 'Select cameras',
            onPressed: () => _showCameraSelector(camerasAsync),
          ),
          // Refresh
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh',
            onPressed: () => ref.invalidate(cameraListProvider),
          ),
        ],
      ),
      body: _selectedCameras.isEmpty
          ? _EmptyState(
              camerasAsync: camerasAsync,
              onSelect: (cameras) => setState(() => _selectedCameras = cameras),
            )
          : _MonitorGrid(
              cameras: _selectedCameras,
              columns: _columns,
            ),
    );
  }

  void _showLayoutPicker() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Grid Layout'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Columns per row:'),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [1, 2, 3, 4].map((n) {
                return ChoiceChip(
                  label: Text('$n'),
                  selected: _columns == n,
                  onSelected: (_) {
                    setState(() => _columns = n);
                    Navigator.pop(ctx);
                  },
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }

  void _showCameraSelector(AsyncValue<List<CameraModel>> camerasAsync) {
    camerasAsync.whenData((cameras) {
      final running = cameras.where((c) =>
          c.taskId != null &&
          c.taskId!.isNotEmpty &&
          (c.status == 'streaming' || c.status == 'connected' || c.status == 'connecting'));
      final available = running.toList();

      if (available.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No running cameras. Start cameras first.')),
        );
        return;
      }

      // Track which are currently selected
      final selected = Set<int>.from(_selectedCameras.map((c) => c.id));

      showDialog(
        context: context,
        builder: (ctx) => StatefulBuilder(
          builder: (ctx, setDialogState) => AlertDialog(
            title: Text('Select Cameras (${selected.length})'),
            content: SizedBox(
              width: 300,
              height: 400,
              child: ListView.builder(
                itemCount: available.length,
                itemBuilder: (_, i) {
                  final cam = available[i];
                  final isSelected = selected.contains(cam.id);
                  return CheckboxListTile(
                    title: Text(cam.name.isNotEmpty ? cam.name : 'Camera ${cam.id}'),
                    subtitle: Text(cam.status, style: const TextStyle(fontSize: 11)),
                    value: isSelected,
                    onChanged: (v) {
                      setDialogState(() {
                        if (v == true) {
                          selected.add(cam.id);
                        } else {
                          selected.remove(cam.id);
                        }
                      });
                    },
                  );
                },
              ),
            ),
            actions: [
              TextButton(
                onPressed: () {
                  setDialogState(() => selected.addAll(available.map((c) => c.id)));
                },
                child: const Text('Select All'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel'),
              ),
              ElevatedButton(
                onPressed: () {
                  setState(() {
                    _selectedCameras = available
                        .where((c) => selected.contains(c.id))
                        .toList();
                  });
                  Navigator.pop(ctx);
                },
                child: const Text('Apply'),
              ),
            ],
          ),
        ),
      );
    });
  }
}

// ── Empty state — prompt to select cameras ──

class _EmptyState extends StatelessWidget {
  final AsyncValue<List<CameraModel>> camerasAsync;
  final void Function(List<CameraModel>) onSelect;

  const _EmptyState({required this.camerasAsync, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.monitor, size: 64, color: Colors.grey),
          const SizedBox(height: 16),
          const Text(
            'Select cameras to start monitoring',
            style: TextStyle(fontSize: 16, color: Colors.grey),
          ),
          const SizedBox(height: 24),
          camerasAsync.when(
            loading: () => const CircularProgressIndicator(),
            error: (e, _) => Text('Error: $e'),
            data: (cameras) {
              final running = cameras
                  .where((c) =>
                      c.taskId != null &&
                      c.taskId!.isNotEmpty &&
                      (c.status == 'streaming' ||
                          c.status == 'connected' ||
                          c.status == 'connecting'))
                  .toList();
              if (running.isEmpty) {
                return const Text(
                  'No running cameras.\nStart cameras from the Cameras tab first.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.orange),
                );
              }
              return ElevatedButton.icon(
                icon: const Icon(Icons.video_library),
                label: Text('Select from ${running.length} running cameras'),
                onPressed: () => onSelect(running),
              );
            },
          ),
        ],
      ),
    );
  }
}

// ── Monitor grid ──

class _MonitorGrid extends StatelessWidget {
  final List<CameraModel> cameras;
  final int columns;

  const _MonitorGrid({required this.cameras, required this.columns});

  @override
  Widget build(BuildContext context) {
    return GridView.builder(
      padding: const EdgeInsets.all(4),
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: columns,
        mainAxisSpacing: 4,
        crossAxisSpacing: 4,
        childAspectRatio: columns == 1 ? 16 / 12 : 4 / 4,
      ),
      itemCount: cameras.length,
      itemBuilder: (_, i) => _CameraMonitorTile(camera: cameras[i]),
    );
  }
}

// ── Single camera tile in the monitor grid ──

class _CameraMonitorTile extends ConsumerWidget {
  final CameraModel camera;
  const _CameraMonitorTile({required this.camera});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final taskId = camera.taskId;

    if (taskId == null || taskId.isEmpty) {
      return Card(
        color: Colors.black87,
        child: Center(
          child: Text(
            '${camera.name}\nNo task',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.grey),
          ),
        ),
      );
    }

    final pollState = ref.watch(cameraPollProvider(taskId));

    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Header
          Container(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    camera.name.isNotEmpty ? camera.name : 'Camera ${camera.id}',
                    style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 11),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                _StatusDot(status: pollState.status?.status ?? camera.status),
              ],
            ),
          ),
          // Live frame — takes most space
          Expanded(
            flex: 3,
            child: GestureDetector(
              onTap: () => _openFullScreen(context, ref),
              child: _SmoothFrame(taskId: taskId),
            ),
          ),
          // Latest plates strip
          if (pollState.status?.history.isNotEmpty == true)
            SizedBox(
              height: 52,
              child: _PlateStrip(
                plates: pollState.status!.history.take(5).toList(),
              ),
            ),
        ],
      ),
    );
  }

  void _openFullScreen(BuildContext context, WidgetRef ref) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => _FullScreenMonitor(camera: camera),
      ),
    );
  }
}

// ── Smooth frame rendering ──
//
// Smooth live frame: uses Image.network pointing at the backend MJPEG endpoint.
// On Flutter web, Image.network delegates to the browser's native <img> which
// handles multipart/x-mixed-replace (MJPEG) at full frame rate natively — no
// Dart polling, no base64 decode, no widget rebuilds per frame.
//
// The MJPEG endpoint has dependencies=[] so no Bearer token is needed.
// If the MJPEG stream fails, errorBuilder falls back to the poll-based approach.

class _SmoothFrame extends ConsumerWidget {
  final String? taskId;
  const _SmoothFrame({this.taskId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (taskId == null || taskId!.isEmpty) {
      return _placeholder(icon: Icons.videocam, label: 'No stream available');
    }

    final baseUrl = ApiClient.instance.options.baseUrl;
    final root = baseUrl.endsWith('/api')
        ? baseUrl.substring(0, baseUrl.length - 4)
        : baseUrl;
    final mjpegUrl = '$root/api/detect/rtsp/$taskId/mjpeg';

    return Image.network(
      mjpegUrl,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      filterQuality: FilterQuality.low,
      loadingBuilder: (context, child, progress) {
        if (progress == null) return child; // loaded / streaming
        return _placeholder(
          icon: Icons.videocam, label: 'Connecting...', spinner: true);
      },
      errorBuilder: (context, error, stack) {
        // Fallback: poll-based frame rendering
        final pollState = ref.watch(cameraPollProvider(taskId!));
        final bytes = _decodePollFrame(pollState.lastAnnotated);
        if (bytes != null) {
          return Image.memory(bytes, fit: BoxFit.contain, gaplessPlayback: true);
        }
        return _placeholder(icon: Icons.warning, label: 'Stream unavailable');
      },
    );
  }

  static Uint8List? _decodePollFrame(String? dataUrl) {
    if (dataUrl == null || dataUrl.isEmpty) return null;
    try {
      final comma = dataUrl.indexOf(',');
      final b64 = comma >= 0 ? dataUrl.substring(comma + 1) : dataUrl;
      return base64Decode(b64);
    } catch (_) {
      return null;
    }
  }

  static Widget _placeholder({
    required IconData icon,
    required String label,
    bool spinner = false,
  }) {
    return Container(
      color: Colors.black87,
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (spinner)
              const CircularProgressIndicator(strokeWidth: 2)
            else
              Icon(icon, color: Colors.grey, size: 28),
            const SizedBox(height: 4),
            Text(label, style: const TextStyle(color: Colors.grey, fontSize: 10)),
          ],
        ),
      ),
    );
  }
}

// ── Plate strip (compact horizontal list of recent plates) ──

class _PlateStrip extends StatelessWidget {
  final List<EnhancedRtspHistoryEntry> plates;
  const _PlateStrip({required this.plates});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: ListView.builder(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
        itemCount: plates.length,
        itemBuilder: (_, i) => Padding(
          padding: const EdgeInsets.only(right: 4),
          child: _MiniPlateTemplate(entry: plates[i]),
        ),
      ),
    );
  }
}

// ── Mini plate template for the strip ──

class _MiniPlateTemplate extends StatelessWidget {
  final EnhancedRtspHistoryEntry entry;
  const _MiniPlateTemplate({required this.entry});

  @override
  Widget build(BuildContext context) {
    final meta = entry.metadata;
    final colorScheme = meta?.colorScheme ?? 'white';
    final bgColor = _plateColor(colorScheme);
    final textColor = _plateTextColor(colorScheme);
    final displayText = entry.persianDisplay.isNotEmpty
        ? entry.persianDisplay
        : entry.dtrbText;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: Colors.black87, width: 1.5),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            displayText,
            style: TextStyle(
              color: textColor,
              fontWeight: FontWeight.bold,
              fontSize: 12,
            ),
            textDirection: TextDirection.rtl,
          ),
          if (meta?.categoryDisplay != null)
            Text(
              meta!.category ?? '',
              style: TextStyle(color: textColor, fontSize: 8),
            ),
        ],
      ),
    );
  }

  Color _plateColor(String scheme) {
    switch (scheme) {
      case 'white':  return Colors.white;
      case 'yellow': return const Color(0xFFFFC107);
      case 'green':  return const Color(0xFF1B5E20);
      case 'red':    return const Color(0xFFC62828);
      case 'blue':   return const Color(0xFF1565C0);
      case 'black':  return const Color(0xFF212121);
      default:       return Colors.white;
    }
  }

  Color _plateTextColor(String scheme) {
    switch (scheme) {
      case 'white':  return Colors.black;
      case 'yellow': return Colors.black;
      case 'green':  return Colors.white;
      case 'red':    return Colors.white;
      case 'blue':   return Colors.white;
      case 'black':  return Colors.white;
      default:       return Colors.black;
    }
  }
}

// ── Full screen monitor for a single camera (tap to open) ──

class _FullScreenMonitor extends ConsumerWidget {
  final CameraModel camera;
  const _FullScreenMonitor({required this.camera});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final taskId = camera.taskId;

    return Scaffold(
      appBar: AppBar(
        title: Text(camera.name.isNotEmpty ? camera.name : 'Camera ${camera.id}'),
      ),
      body: taskId == null || taskId.isEmpty
          ? const Center(child: Text('No active task'))
          : _FullScreenBody(taskId: taskId),
    );
  }
}

class _FullScreenBody extends ConsumerWidget {
  final String taskId;
  const _FullScreenBody({required this.taskId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pollState = ref.watch(cameraPollProvider(taskId));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Large frame
        Expanded(
          flex: 3,
          child: _SmoothFrame(taskId: taskId),
        ),
        const Divider(height: 1),
        // Plate history with templates
        Expanded(
          flex: 2,
          child: _FullPlateList(history: pollState.status?.history ?? []),
        ),
      ],
    );
  }
}

// ── Full plate list with large templates ──

class _FullPlateList extends StatelessWidget {
  final List<EnhancedRtspHistoryEntry> history;
  const _FullPlateList({required this.history});

  @override
  Widget build(BuildContext context) {
    if (history.isEmpty) {
      return const Center(
        child: Text('No plates detected yet', style: TextStyle(color: Colors.grey)),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Text(
            'Detected Plates (${history.length})',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            itemCount: history.length,
            itemBuilder: (_, i) => Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: _PlateCard(entry: history[i]),
            ),
          ),
        ),
      ],
    );
  }
}

// ── Plate card with full Iranian template ──

class _PlateCard extends StatelessWidget {
  final EnhancedRtspHistoryEntry entry;
  const _PlateCard({required this.entry});

  @override
  Widget build(BuildContext context) {
    final meta = entry.metadata;

    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Row(
          children: [
            _IranianPlateTemplate(
              plateText: entry.persianDisplay.isNotEmpty
                  ? entry.persianDisplay
                  : entry.dtrbText,
              metadata: meta,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (meta?.categoryDisplay != null)
                    Text(
                      meta!.categoryDisplay!,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 11),
                    ),
                  if (meta?.regionName != null)
                    Text(meta!.regionName!, style: const TextStyle(fontSize: 10, color: Colors.grey)),
                  Text(
                    '${(entry.confidence * 100).toStringAsFixed(1)}%  •  ×${entry.count}',
                    style: const TextStyle(fontSize: 10),
                  ),
                  Text(entry.lastSeen, style: const TextStyle(fontSize: 9, color: Colors.grey)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Iranian plate template widget ──

class _IranianPlateTemplate extends StatelessWidget {
  final String plateText;
  final PlateMetadataModel? metadata;

  const _IranianPlateTemplate({required this.plateText, this.metadata});

  @override
  Widget build(BuildContext context) {
    final colorScheme = metadata?.colorScheme ?? 'white';
    final bgColor = _bgColor(colorScheme);
    final textColor = _textColor(colorScheme);
    final regionCode = metadata?.regionCode;
    final parts = _parsePlate(plateText, regionCode);

    return Container(
      width: 160,
      height: 44,
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(5),
        border: Border.all(color: Colors.black, width: 2),
        boxShadow: [
          BoxShadow(color: Colors.black.withAlpha(30), blurRadius: 3, offset: const Offset(0, 1)),
        ],
      ),
      child: Row(
        children: [
          // Iran flag strip
          Container(
            width: 18,
            decoration: const BoxDecoration(
              color: Color(0xFF1B3A6B),
              borderRadius: BorderRadius.only(
                topLeft: Radius.circular(3),
                bottomLeft: Radius.circular(3),
              ),
            ),
            child: const Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text('🇮🇷', style: TextStyle(fontSize: 7)),
                Text('I.R.\nIRAN', textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white, fontSize: 4, height: 1.1)),
              ],
            ),
          ),
          // Main plate number
          Expanded(
            child: Center(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: Text(
                    parts['main'] ?? plateText,
                    style: TextStyle(
                      color: textColor,
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                      letterSpacing: 0.5,
                    ),
                    textDirection: TextDirection.rtl,
                  ),
                ),
              ),
            ),
          ),
          // Region code
          if (parts['region'] != null)
            Container(
              width: 24,
              decoration: BoxDecoration(
                border: Border(left: BorderSide(color: Colors.black.withAlpha(60))),
              ),
              child: Center(
                child: Text(
                  parts['region']!,
                  style: TextStyle(color: textColor, fontWeight: FontWeight.bold, fontSize: 12),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Map<String, String?> _parsePlate(String text, String? regionCode) {
    if (regionCode != null && text.length >= 8) {
      return {'main': text.substring(0, text.length - 2), 'region': regionCode};
    }
    if (text.length >= 7) {
      final region = text.substring(text.length - 2);
      if (RegExp(r'^\d{2}$').hasMatch(region)) {
        return {'main': text.substring(0, text.length - 2), 'region': region};
      }
    }
    return {'main': text, 'region': null};
  }

  Color _bgColor(String scheme) {
    switch (scheme) {
      case 'white':  return Colors.white;
      case 'yellow': return const Color(0xFFFFC107);
      case 'green':  return const Color(0xFF1B5E20);
      case 'red':    return const Color(0xFFC62828);
      case 'blue':   return const Color(0xFF1565C0);
      case 'black':  return const Color(0xFF212121);
      default:       return Colors.white;
    }
  }

  Color _textColor(String scheme) {
    switch (scheme) {
      case 'white':  return Colors.black;
      case 'yellow': return Colors.black;
      default:       return Colors.white;
    }
  }
}

// ── Status dot ──

class _StatusDot extends StatelessWidget {
  final String status;
  const _StatusDot({required this.status});

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (status) {
      case 'streaming':
        color = Colors.green;
        break;
      case 'connected':
        color = Colors.lightGreen;
        break;
      case 'connecting':
        color = Colors.orange;
        break;
      case 'error':
        color = Colors.red;
        break;
      default:
        color = Colors.grey;
    }
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(shape: BoxShape.circle, color: color),
    );
  }
}


// ── Public single-camera monitor (used from camera list) ──

class SingleCameraMonitor extends ConsumerWidget {
  final CameraModel camera;
  const SingleCameraMonitor({super.key, required this.camera});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final taskId = camera.taskId;

    return Scaffold(
      appBar: AppBar(
        title: Text(camera.name.isNotEmpty ? camera.name : 'Camera ${camera.id}'),
        actions: [
          _StatusDot(status: camera.status),
          const SizedBox(width: 16),
        ],
      ),
      body: taskId == null || taskId.isEmpty
          ? const Center(child: Text('No active task — start the camera first.'))
          : _FullScreenBody(taskId: taskId),
    );
  }
}
