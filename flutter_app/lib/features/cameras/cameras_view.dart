// lib/features/cameras/cameras_view.dart
// Modern multi-camera management view.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../shared/app_icons.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../../data/models/camera_model.dart';
import '../../data/repositories/camera_repo.dart';
import '../../core/api_client.dart';
import 'camera_panel.dart';
import 'camera_live_monitor.dart' show CameraLiveMonitor, SingleCameraMonitor;
import 'scanner_view.dart';

// ── Providers ──────────────────────────────────────────────────────────────

final _cameraRepoProvider = Provider((_) => CameraRepo());

final cameraListProvider = FutureProvider<List<CameraModel>>((ref) =>
    ref.read(_cameraRepoProvider).listCameras());

final concurrencyLimitProvider = StateProvider<int>((_) => 4);

// ── Main view ──────────────────────────────────────────────────────────────

class CamerasView extends ConsumerStatefulWidget {
  const CamerasView({super.key});

  @override
  ConsumerState<CamerasView> createState() => _CamerasViewState();
}

class _CamerasViewState extends ConsumerState<CamerasView>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _tabController.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final camerasAsync = ref.watch(cameraListProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            _buildHeader(context),
            const SizedBox(height: 20),
            // Tabs
            _buildTabs(),
            const SizedBox(height: 20),
            // Content
            Expanded(
              child: TabBarView(
                controller: _tabController,
                physics: const NeverScrollableScrollPhysics(),
                children: [
                  _CamerasTab(camerasAsync: camerasAsync, ref: ref),
                  const CameraLiveMonitor(),
                  const ScannerView(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Row(
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Cameras',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Manage and monitor RTSP cameras',
              style: TextStyle(fontSize: 14, color: Colors.white.withOpacity(0.5)),
            ),
          ],
        ),
        const Spacer(),
        _ActionButton(
          icon: AppIcons.refreshCw,
          label: 'Refresh',
          onTap: () => ref.invalidate(cameraListProvider),
        ),
        const SizedBox(width: 8),
        _ActionButton(
          icon: AppIcons.plus,
          label: 'Add Camera',
          primary: true,
          onTap: () => _showAddCameraDialog(context, ref),
        ),
      ],
    ).animate().fadeIn(duration: 400.ms);
  }

  Widget _buildTabs() {
    final tabs = [
      (AppIcons.camera, 'My Cameras'),
      (AppIcons.monitor, 'Monitor'),
      (AppIcons.radar, 'Scanner'),
    ];

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.04),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: tabs.asMap().entries.map((e) {
          final isSelected = _tabController.index == e.key;
          return GestureDetector(
            onTap: () => _tabController.animateTo(e.key),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                color: isSelected ? const Color(0xFF3B82F6).withOpacity(0.15) : Colors.transparent,
                borderRadius: BorderRadius.circular(7),
                border: isSelected
                    ? Border.all(color: const Color(0xFF3B82F6).withOpacity(0.3))
                    : null,
              ),
              child: Row(
                children: [
                  Icon(e.value.$1, size: 16,
                    color: isSelected ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.4)),
                  const SizedBox(width: 8),
                  Text(e.value.$2, style: TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w500,
                    color: isSelected ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.5),
                  )),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    ).animate().fadeIn(duration: 400.ms, delay: 100.ms);
  }

  static Future<void> _showAddCameraDialog(BuildContext context, WidgetRef ref) async {
    final nameCtrl = TextEditingController();
    final urlCtrl = TextEditingController();
    final skipCtrl = TextEditingController(text: '15');
    String? error;

    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => Dialog(
          backgroundColor: const Color(0xFF18181B),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Container(
            padding: const EdgeInsets.all(24),
            width: 400,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Add Camera', style: TextStyle(
                  fontSize: 18, fontWeight: FontWeight.w600, color: Colors.white)),
                const SizedBox(height: 4),
                Text('Configure a new RTSP camera',
                    style: TextStyle(fontSize: 13, color: Colors.white.withOpacity(0.5))),
                const SizedBox(height: 20),
                _DialogInput(controller: nameCtrl, label: 'Camera Name', hint: 'e.g. Front Gate'),
                const SizedBox(height: 12),
                _DialogInput(controller: urlCtrl, label: 'RTSP URL', hint: 'rtsp://...'),
                const SizedBox(height: 12),
                _DialogInput(controller: skipCtrl, label: 'Skip Frames', hint: '15'),
                if (error != null) ...[
                  const SizedBox(height: 12),
                  Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
                ],
                const SizedBox(height: 20),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: Text('Cancel', style: TextStyle(color: Colors.white.withOpacity(0.5))),
                    ),
                    const SizedBox(width: 8),
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF3B82F6),
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                      ),
                      onPressed: () async {
                        final url = urlCtrl.text.trim();
                        if (url.isEmpty) { setState(() => error = 'URL is required'); return; }
                        final skipRaw = int.tryParse(skipCtrl.text.trim());
                        if (skipRaw == null || skipRaw < 1 || skipRaw > 1000) {
                          setState(() => error = 'Skip frames must be 1–1000'); return;
                        }
                        try {
                          final repo = ref.read(_cameraRepoProvider);
                          await repo.createCamera(nameCtrl.text, url, skipRaw);
                          ref.invalidate(cameraListProvider);
                          if (ctx.mounted) Navigator.pop(ctx);
                        } catch (e) { setState(() => error = _errMsg(e)); }
                      },
                      child: const Text('Add Camera'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _DialogInput extends StatelessWidget {
  final TextEditingController controller;
  final String label;
  final String hint;
  const _DialogInput({required this.controller, required this.label, required this.hint});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.6))),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          style: const TextStyle(fontSize: 13, color: Colors.white),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: TextStyle(color: Colors.white.withOpacity(0.3)),
            filled: true,
            fillColor: Colors.white.withOpacity(0.04),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: Colors.white.withOpacity(0.08)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: Colors.white.withOpacity(0.08)),
            ),
            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          ),
        ),
      ],
    );
  }
}

// ── Cameras tab ────────────────────────────────────────────────────────────

class _CamerasTab extends StatelessWidget {
  final AsyncValue<List<CameraModel>> camerasAsync;
  final WidgetRef ref;
  const _CamerasTab({required this.camerasAsync, required this.ref});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _TopToolbar(),
        const SizedBox(height: 16),
        Expanded(
          child: camerasAsync.when(
            loading: () => const Center(child: CircularProgressIndicator(strokeWidth: 2)),
            error: (e, _) => Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text('Failed to load cameras: ${_errMsg(e)}',
                      style: TextStyle(color: Colors.white.withOpacity(0.5))),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () => ref.invalidate(cameraListProvider),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
            data: (cameras) {
              if (cameras.isEmpty) {
                return Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(AppIcons.camera, size: 48, color: Colors.white.withOpacity(0.2)),
                      const SizedBox(height: 12),
                      Text('No cameras added yet',
                          style: TextStyle(color: Colors.white.withOpacity(0.4))),
                    ],
                  ),
                );
              }
              return _CameraGrid(cameras: cameras);
            },
          ),
        ),
      ],
    );
  }
}

// ── Top toolbar ────────────────────────────────────────────────────────────

class _TopToolbar extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(_cameraRepoProvider);

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Row(
        children: [
          Icon(AppIcons.settings2, size: 14, color: Colors.white.withOpacity(0.4)),
          const SizedBox(width: 8),
          Text('Controls', style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.5))),
          const Spacer(),
          _ActionButton(
            icon: AppIcons.play,
            label: 'Start All',
            onTap: () async {
              try {
                await repo.startAll();
                ref.invalidate(cameraListProvider);
              } catch (_) {}
            },
          ),
          const SizedBox(width: 8),
          _ActionButton(
            icon: AppIcons.square,
            label: 'Stop All',
            danger: true,
            onTap: () async {
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

// ── Camera grid ────────────────────────────────────────────────────────────

class _CameraGrid extends ConsumerWidget {
  final List<CameraModel> cameras;
  const _CameraGrid({required this.cameras});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return LayoutBuilder(
      builder: (ctx, constraints) {
        final cols = (constraints.maxWidth / 320).floor().clamp(1, 4);
        return GridView.builder(
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: cols,
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 1.6,
          ),
          itemCount: cameras.length,
          itemBuilder: (_, i) => _CameraCard(camera: cameras[i])
              .animate()
              .fadeIn(duration: 300.ms, delay: (i * 60).ms)
              .scale(begin: const Offset(0.98, 0.98)),
        );
      },
    );
  }
}

class _CameraCard extends ConsumerWidget {
  final CameraModel camera;
  const _CameraCard({required this.camera});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(_cameraRepoProvider);

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                _CameraStatusDot(status: camera.status),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    camera.name.isNotEmpty ? camera.name : '(unnamed)',
                    style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w500, color: Colors.white),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                // Actions
                _IconAction(icon: AppIcons.edit2, onTap: () => _showRenameDialog(context, ref, camera)),
                _IconAction(icon: AppIcons.trash2, onTap: () async {
                  await repo.deleteCamera(camera.id);
                  ref.invalidate(cameraListProvider);
                }),
              ],
            ),
          ),
          // URL info
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    camera.url,
                    style: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.4)),
                    maxLines: 1, overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Skip: ${camera.skipFrames} frames',
                    style: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.3)),
                  ),
                ],
              ),
            ),
          ),
          // Actions bar
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: Colors.white.withOpacity(0.04))),
            ),
            child: Row(
              children: [
                if (camera.status == 'stopped' || camera.status == 'error')
                  _SmallButton(
                    icon: AppIcons.play, label: 'Start',
                    onTap: camera.name.trim().isEmpty ? null : () async {
                      await repo.startCamera(camera.id);
                      ref.invalidate(cameraListProvider);
                    },
                  )
                else
                  _SmallButton(
                    icon: AppIcons.square, label: 'Stop', danger: true,
                    onTap: () async {
                      await repo.stopCamera(camera.id);
                      ref.invalidate(cameraListProvider);
                    },
                  ),
                const Spacer(),
                if (camera.taskId != null && camera.taskId!.isNotEmpty)
                  _SmallButton(
                    icon: AppIcons.monitor, label: 'Monitor',
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => SingleCameraMonitor(camera: camera)),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static Future<void> _showRenameDialog(BuildContext context, WidgetRef ref, CameraModel cam) async {
    final ctrl = TextEditingController(text: cam.name);
    String? error;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => Dialog(
          backgroundColor: const Color(0xFF18181B),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Container(
            padding: const EdgeInsets.all(24),
            width: 360,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Rename Camera', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: Colors.white)),
                const SizedBox(height: 16),
                _DialogInput(controller: ctrl, label: 'Camera Name', hint: 'Enter name'),
                if (error != null) ...[
                  const SizedBox(height: 8),
                  Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
                ],
                const SizedBox(height: 16),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(onPressed: () => Navigator.pop(ctx),
                        child: Text('Cancel', style: TextStyle(color: Colors.white.withOpacity(0.5)))),
                    const SizedBox(width: 8),
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF3B82F6),
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                      ),
                      onPressed: () async {
                        try {
                          await ref.read(_cameraRepoProvider).updateCamera(cam.id, name: ctrl.text);
                          ref.invalidate(cameraListProvider);
                          if (ctx.mounted) Navigator.pop(ctx);
                        } catch (e) { setState(() => error = _errMsg(e)); }
                      },
                      child: const Text('Save'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ── Small widgets ──────────────────────────────────────────────────────────

class _CameraStatusDot extends StatelessWidget {
  final String status;
  const _CameraStatusDot({required this.status});

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (status) {
      case 'streaming': case 'connected': color = const Color(0xFF10B981); break;
      case 'connecting': color = const Color(0xFFF59E0B); break;
      case 'error': color = const Color(0xFFEF4444); break;
      case 'queued': color = const Color(0xFF3B82F6); break;
      default: color = const Color(0xFF6B7280);
    }
    return Container(width: 8, height: 8, decoration: BoxDecoration(shape: BoxShape.circle, color: color));
  }
}

class _IconAction extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;
  const _IconAction({required this.icon, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.all(4),
        child: Icon(icon, size: 14, color: Colors.white.withOpacity(0.4)),
      ),
    );
  }
}

class _SmallButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool danger;
  const _SmallButton({required this.icon, required this.label, this.onTap, this.danger = false});

  @override
  Widget build(BuildContext context) {
    final color = danger ? const Color(0xFFEF4444) : const Color(0xFF3B82F6);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withOpacity(0.2)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 12, color: color),
            const SizedBox(width: 4),
            Text(label, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w500, color: color)),
          ],
        ),
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool primary;
  final bool danger;
  const _ActionButton({required this.icon, required this.label, required this.onTap, this.primary = false, this.danger = false});

  @override
  Widget build(BuildContext context) {
    final color = danger ? const Color(0xFFEF4444) : primary ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.6);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: primary ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.04),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: primary ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.08)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: primary ? Colors.white : color),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: 12, color: primary ? Colors.white : color)),
          ],
        ),
      ),
    );
  }
}

String _errMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
