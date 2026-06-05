// lib/features/cameras/cameras_view.dart
// Multi-camera management view: add/remove/rename cameras, concurrency config,
// responsive scrollable grid, and start/stop-all controls.
// Requirements: 11.2–11.7, 12.1–12.3, 12.6, 12.8, 13.1–13.8

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/camera_model.dart';
import '../../data/repositories/camera_repo.dart';
import '../../core/api_client.dart';
import 'camera_panel.dart';

// ── Providers ──────────────────────────────────────────────────────────────

final _cameraRepoProvider = Provider((_) => CameraRepo());

final cameraListProvider = FutureProvider<List<CameraModel>>((ref) =>
    ref.read(_cameraRepoProvider).listCameras());

final concurrencyLimitProvider = StateProvider<int>((_) => 4);

// ── Main view ──────────────────────────────────────────────────────────────

class CamerasView extends ConsumerWidget {
  const CamerasView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final camerasAsync = ref.watch(cameraListProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Cameras'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(cameraListProvider),
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: Column(
        children: [
          // ── Top toolbar: concurrency + start/stop-all ─────────────────
          _TopToolbar(),
          // ── Camera list ───────────────────────────────────────────────
          Expanded(
            flex: 1,
            child: camerasAsync.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text('Failed to load cameras: ${_errMsg(e)}'),
                    const SizedBox(height: 8),
                    ElevatedButton(
                      onPressed: () => ref.invalidate(cameraListProvider),
                      child: const Text('Retry'),
                    ),
                  ],
                ),
              ),
              data: (cameras) => _CameraList(cameras: cameras),
            ),
          ),
          const Divider(height: 1),
          // ── Live grid ────────────────────────────────────────────────
          Expanded(
            flex: 2,
            child: camerasAsync.when(
              loading: () => const SizedBox.shrink(),
              error: (_, __) => const SizedBox.shrink(),
              data: (cameras) {
                final running = cameras
                    .where((c) =>
                        c.status == 'connecting' ||
                        c.status == 'connected' ||
                        c.status == 'streaming')
                    .toList();
                if (running.isEmpty) {
                  return const Center(
                    child: Text('No cameras running',
                        style: TextStyle(color: Colors.grey)),
                  );
                }
                return _CameraGrid(cameras: running);
              },
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('Add Camera'),
        onPressed: () => _showAddCameraDialog(context, ref),
      ),
    );
  }

  static Future<void> _showAddCameraDialog(
      BuildContext context, WidgetRef ref) async {
    final nameCtrl = TextEditingController();
    final urlCtrl = TextEditingController();
    final skipCtrl = TextEditingController(text: '15');
    String? error;

    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          title: const Text('Add Camera'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(labelText: 'Camera name'),
              ),
              TextField(
                controller: urlCtrl,
                decoration: const InputDecoration(
                  labelText: 'RTSP URL',
                  hintText: 'rtsp://...',
                ),
              ),
              TextField(
                controller: skipCtrl,
                decoration: const InputDecoration(labelText: 'Skip frames'),
                keyboardType: TextInputType.number,
              ),
              if (error != null)
                Text(error!, style: const TextStyle(color: Colors.red)),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel')),
            ElevatedButton(
              onPressed: () async {
                // Req 11.6 — duplicate-name check is done server-side; URL validated
                final url = urlCtrl.text.trim();
                if (url.isEmpty) {
                  setState(() => error = 'URL is required');
                  return;
                }
                final skipRaw = int.tryParse(skipCtrl.text.trim());
                if (skipRaw == null || skipRaw < 1 || skipRaw > 1000) {
                  setState(() => error = 'Skip frames must be 1–1000');
                  return;
                }
                try {
                  final repo = ref.read(_cameraRepoProvider);
                  await repo.createCamera(nameCtrl.text, url, skipRaw);
                  ref.invalidate(cameraListProvider);
                  if (ctx.mounted) Navigator.pop(ctx);
                } catch (e) {
                  setState(() => error = _errMsg(e));
                }
              },
              child: const Text('Add'),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Top toolbar ───────────────────────────────────────────────────────────

class _TopToolbar extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final limitState = ref.watch(concurrencyLimitProvider);
    final repo = ref.read(_cameraRepoProvider);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          const Text('Concurrency limit:'),
          const SizedBox(width: 8),
          SizedBox(
            width: 60,
            child: TextFormField(
              initialValue: '$limitState',
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(isDense: true),
              onChanged: (v) async {
                final val = int.tryParse(v);
                if (val == null || val < 1 || val > 64) return; // Req 12.8
                try {
                  await repo.setConcurrencyLimit(val);
                  ref.read(concurrencyLimitProvider.notifier).state = val;
                } catch (_) {}
              },
            ),
          ),
          const Spacer(),
          OutlinedButton.icon(
            icon: const Icon(Icons.play_circle_outline),
            label: const Text('Start All'),
            onPressed: () async {
              try {
                await repo.startAll();
                ref.invalidate(cameraListProvider);
              } catch (_) {}
            },
          ),
          const SizedBox(width: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.stop_circle_outlined),
            label: const Text('Stop All'),
            style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
            onPressed: () async {
              try {
                await repo.stopAll();
                ref.invalidate(cameraListProvider);
              } catch (_) {}
            },
          ),
        ],
      ),
    );
  }
}

// ── Camera list ───────────────────────────────────────────────────────────

class _CameraList extends ConsumerWidget {
  final List<CameraModel> cameras;
  const _CameraList({required this.cameras});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (cameras.isEmpty) {
      return const Center(
        child: Text('No cameras added yet. Tap + to add one.',
            style: TextStyle(color: Colors.grey)),
      );
    }

    return ListView.builder(
      itemCount: cameras.length,
      itemBuilder: (ctx, i) {
        final cam = cameras[i];
        return ListTile(
          leading: _StatusIcon(status: cam.status),
          // Req 11.7 — show name, status, skip_frames
          title: Text(cam.name.isNotEmpty ? cam.name : '(no name)'),
          subtitle: Text(
              '${cam.status} • skip_frames=${cam.skipFrames} • ${cam.url}',
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11)),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Start/Stop per camera
              if (cam.status == 'stopped' || cam.status == 'error')
                IconButton(
                  icon: const Icon(Icons.play_arrow),
                  tooltip: 'Start',
                  onPressed: cam.name.trim().isEmpty
                      ? null // Req 11.3 — block start if no name
                      : () async {
                          try {
                            await ref.read(_cameraRepoProvider).startCamera(cam.id);
                            ref.invalidate(cameraListProvider);
                          } catch (_) {}
                        },
                )
              else if (cam.status != 'stopped')
                IconButton(
                  icon: const Icon(Icons.stop),
                  tooltip: 'Stop',
                  onPressed: () async {
                    try {
                      await ref.read(_cameraRepoProvider).stopCamera(cam.id);
                      ref.invalidate(cameraListProvider);
                    } catch (_) {}
                  },
                ),
              // Rename
              IconButton(
                icon: const Icon(Icons.edit),
                tooltip: 'Rename',
                onPressed: () => _showRenameDialog(context, ref, cam),
              ),
              // Delete
              IconButton(
                icon: const Icon(Icons.delete_outline),
                tooltip: 'Remove',
                onPressed: () async {
                  try {
                    await ref.read(_cameraRepoProvider).deleteCamera(cam.id);
                    ref.invalidate(cameraListProvider);
                  } catch (_) {}
                },
              ),
            ],
          ),
        );
      },
    );
  }

  static Future<void> _showRenameDialog(
      BuildContext context, WidgetRef ref, CameraModel cam) async {
    final ctrl = TextEditingController(text: cam.name);
    String? error;

    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          title: const Text('Rename Camera'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: ctrl,
                decoration:
                    const InputDecoration(labelText: 'Camera name'),
              ),
              if (error != null)
                Text(error!, style: const TextStyle(color: Colors.red)),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel')),
            ElevatedButton(
              onPressed: () async {
                final newName = ctrl.text;
                // Req 11.6 — client-side duplicate check: handled by server 409/422
                try {
                  await ref
                      .read(_cameraRepoProvider)
                      .updateCamera(cam.id, name: newName);
                  ref.invalidate(cameraListProvider);
                  if (ctx.mounted) Navigator.pop(ctx);
                } catch (e) {
                  setState(() => error = _errMsg(e));
                }
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Responsive camera grid ─────────────────────────────────────────────────

class _CameraGrid extends ConsumerWidget {
  final List<CameraModel> cameras;
  const _CameraGrid({required this.cameras});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return LayoutBuilder(
      builder: (ctx, constraints) {
        // Responsive column count: ~280px per panel
        final cols = (constraints.maxWidth / 280).floor().clamp(1, 4);
        return GridView.builder(
          padding: const EdgeInsets.all(8),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: cols,
            mainAxisSpacing: 8,
            crossAxisSpacing: 8,
            childAspectRatio: 4 / 3,
          ),
          itemCount: cameras.length,
          itemBuilder: (_, i) {
            final cam = cameras[i];
            return CameraLivePanel(
              camera: cam,
              // Req 13.5 — tap opens enlarged view
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(
                    builder: (_) => CameraEnlargedView(camera: cam)),
              ),
            );
          },
        );
      },
    );
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────

class _StatusIcon extends StatelessWidget {
  final String status;
  const _StatusIcon({required this.status});

  @override
  Widget build(BuildContext context) {
    IconData icon;
    Color color;
    switch (status) {
      case 'streaming':
      case 'connected':
        icon = Icons.videocam;
        color = Colors.green;
        break;
      case 'connecting':
        icon = Icons.autorenew;
        color = Colors.orange;
        break;
      case 'error':
        icon = Icons.error_outline;
        color = Colors.red;
        break;
      case 'queued':
        icon = Icons.queue;
        color = Colors.blue;
        break;
      default:
        icon = Icons.videocam_off;
        color = Colors.grey;
    }
    return Icon(icon, color: color);
  }
}

String _errMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
