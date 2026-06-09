// lib/features/cameras/cameras_view.dart
// Camera management view. The camera list is a PlutoGrid data grid (sorting +
// column controls, Requirement 17.5); management controls are gated by the
// manage_cameras permission (Requirement 18.4). Live monitor and scanner are
// kept as additional tabs.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pluto_grid/pluto_grid.dart';

import '../../core/api_client.dart';
import '../../core/persian_format.dart';
import '../../data/models/camera_model.dart';
import '../../data/repositories/camera_repo.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/app_data_grid.dart';
import '../../shared/widgets/permission_gate.dart' show Permissions;
import '../../shared/widgets/screen_shell.dart';
import 'camera_live_monitor.dart' show CameraLiveMonitor, SingleCameraMonitor;
import 'scanner_view.dart';

final _cameraRepoProvider = Provider((_) => CameraRepo());

final cameraListProvider = FutureProvider<List<CameraModel>>((ref) =>
    ref.read(_cameraRepoProvider).listCameras());

class CamerasView extends ConsumerStatefulWidget {
  const CamerasView({super.key});

  @override
  ConsumerState<CamerasView> createState() => _CamerasViewState();
}

class _CamerasViewState extends ConsumerState<CamerasView> {
  int _tab = 0; // 0 = list, 1 = monitor, 2 = scanner

  @override
  Widget build(BuildContext context) {
    final canManage = sessionHasPermission(ref, Permissions.manageCameras);

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ScreenHeader(
            title: 'دوربین‌ها',
            subtitle: 'مدیریت و پایش دوربین‌های شبکه (RTSP)',
            actions: [
              ToolbarButton(
                icon: AppIcons.refreshCw,
                label: 'بازخوانی',
                onTap: () => ref.invalidate(cameraListProvider),
              ),
              if (canManage && _tab == 0) ...[
                const SizedBox(width: 8),
                ToolbarButton(
                  icon: AppIcons.plus,
                  label: 'افزودن دوربین',
                  primary: true,
                  onTap: _showAddCameraDialog,
                ),
              ],
            ],
          ),
          const SizedBox(height: 16),
          _Tabs(index: _tab, onChanged: (i) => setState(() => _tab = i)),
          const SizedBox(height: 16),
          Expanded(child: _buildTab(canManage)),
        ],
      ),
    );
  }

  Widget _buildTab(bool canManage) {
    switch (_tab) {
      case 1:
        return const CameraLiveMonitor();
      case 2:
        return const ScannerView();
      default:
        return _buildList(canManage);
    }
  }

  Widget _buildList(bool canManage) {
    final camerasAsync = ref.watch(cameraListProvider);
    return Column(
      children: [
        if (canManage) ...[
          _Toolbar(repo: ref.read(_cameraRepoProvider), onChanged: () => ref.invalidate(cameraListProvider)),
          const SizedBox(height: 12),
        ],
        Expanded(
          child: camerasAsync.when(
            loading: () => const Center(child: CircularProgressIndicator(strokeWidth: 2)),
            error: (e, _) => GridStatePlaceholder(
              icon: AppIcons.alertCircle,
              message: 'بارگیری دوربین‌ها ممکن نشد\n${_errMsg(e)}',
              onRetry: () => ref.invalidate(cameraListProvider),
            ),
            data: (cameras) {
              if (cameras.isEmpty) {
                return const GridStatePlaceholder(
                  icon: AppIcons.camera,
                  message: 'هنوز دوربینی اضافه نشده است.',
                );
              }
              return AppDataGrid(
                key: ValueKey('cameras_${cameras.length}_$canManage'),
                columns: _columns(canManage),
                rows: cameras.map(_rowFor).toList(),
              );
            },
          ),
        ),
      ],
    );
  }

  List<PlutoColumn> _columns(bool canManage) => [
        PlutoColumn(
          title: 'وضعیت',
          field: 'status',
          type: PlutoColumnType.text(),
          width: 130,
          renderer: (ctx) => _StatusBadge(status: ctx.cell.value as String),
        ),
        PlutoColumn(title: 'نام', field: 'name', type: PlutoColumnType.text(), minWidth: 150),
        PlutoColumn(title: 'آدرس', field: 'url', type: PlutoColumnType.text(), minWidth: 220),
        PlutoColumn(
          title: 'پرش فریم',
          field: 'skip',
          type: PlutoColumnType.number(),
          width: 110,
          renderer: (ctx) => Text(
            PersianFormat.number(ctx.cell.value as num),
            style: const TextStyle(color: Color(0xFFFAFAFA), fontSize: 13),
          ),
        ),
        PlutoColumn(
          title: 'عملیات',
          field: 'actions',
          type: PlutoColumnType.text(),
          width: 210,
          enableSorting: false,
          enableContextMenu: false,
          renderer: (ctx) {
            final cells = ctx.row.cells;
            final cam = CameraModel(
              id: cells['id']!.value as int,
              name: cells['name']!.value as String,
              url: cells['url']!.value as String,
              skipFrames: cells['skip']!.value as int,
              status: cells['status']!.value as String,
              taskId: cells['task']!.value as String?,
            );
            final running = cam.status != 'stopped' && cam.status != 'error';
            return Align(
              alignment: Alignment.centerRight,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (canManage) ...[
                    if (running)
                      _IconBtn(icon: AppIcons.square, color: const Color(0xFFEF4444), tooltip: 'توقف', onTap: () => _stop(cam.id))
                    else
                      _IconBtn(
                        icon: AppIcons.play,
                        color: const Color(0xFF10B981),
                        tooltip: 'شروع',
                        onTap: cam.name.trim().isEmpty ? null : () => _start(cam.id),
                      ),
                    const SizedBox(width: 6),
                    _IconBtn(icon: AppIcons.edit2, color: const Color(0xFF3B82F6), tooltip: 'ویرایش', onTap: () => _showEditDialog(cam)),
                    const SizedBox(width: 6),
                    _IconBtn(icon: AppIcons.trash2, color: const Color(0xFFEF4444), tooltip: 'حذف', onTap: () => _confirmDelete(cam)),
                    const SizedBox(width: 6),
                  ],
                  if (cam.taskId != null && cam.taskId!.isNotEmpty)
                    _IconBtn(
                      icon: AppIcons.monitor,
                      color: const Color(0xFF8B5CF6),
                      tooltip: 'پایش',
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => SingleCameraMonitor(camera: cam)),
                      ),
                    ),
                ],
              ),
            );
          },
        ),
      ];

  PlutoRow _rowFor(CameraModel c) => PlutoRow(cells: {
        'status': PlutoCell(value: c.status),
        'name': PlutoCell(value: c.name.isNotEmpty ? c.name : '(بدون نام)'),
        'url': PlutoCell(value: c.url),
        'skip': PlutoCell(value: c.skipFrames),
        'id': PlutoCell(value: c.id),
        'task': PlutoCell(value: c.taskId),
        'actions': PlutoCell(value: c.id),
      });

  // ── Actions ───────────────────────────────────────────────────────────────

  Future<void> _start(int id) async {
    try {
      await ref.read(_cameraRepoProvider).startCamera(id);
    } catch (e) {
      _toast('شروع ناموفق بود: ${_errMsg(e)}');
    }
    ref.invalidate(cameraListProvider);
  }

  Future<void> _stop(int id) async {
    try {
      await ref.read(_cameraRepoProvider).stopCamera(id);
    } catch (e) {
      _toast('توقف ناموفق بود: ${_errMsg(e)}');
    }
    ref.invalidate(cameraListProvider);
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: const Color(0xFF7F1D1D)),
    );
  }

  Future<void> _showAddCameraDialog() async {
    final nameCtrl = TextEditingController();
    final urlCtrl = TextEditingController();
    final skipCtrl = TextEditingController(text: '15');
    String? error;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => _CameraDialog(
          title: 'افزودن دوربین',
          children: [
            _LabeledField(label: 'نام دوربین', controller: nameCtrl, hint: 'مثلاً درب ورودی'),
            const SizedBox(height: 12),
            _LabeledField(label: 'آدرس RTSP', controller: urlCtrl, hint: 'rtsp://...'),
            const SizedBox(height: 12),
            _LabeledField(label: 'پرش فریم (۱ تا ۱۰۰۰)', controller: skipCtrl, hint: '15'),
            if (error != null) ...[
              const SizedBox(height: 10),
              Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
            ],
          ],
          onConfirm: () async {
            final url = urlCtrl.text.trim();
            if (url.isEmpty) {
              setLocal(() => error = 'آدرس الزامی است');
              return;
            }
            final skip = int.tryParse(skipCtrl.text.trim());
            if (skip == null || skip < 1 || skip > 1000) {
              setLocal(() => error = 'پرش فریم باید بین ۱ تا ۱۰۰۰ باشد');
              return;
            }
            try {
              await ref.read(_cameraRepoProvider).createCamera(nameCtrl.text.trim(), url, skip);
              ref.invalidate(cameraListProvider);
              if (ctx.mounted) Navigator.pop(ctx);
            } catch (e) {
              setLocal(() => error = _errMsg(e));
            }
          },
        ),
      ),
    );
  }

  Future<void> _showEditDialog(CameraModel cam) async {
    final nameCtrl = TextEditingController(text: cam.name);
    final urlCtrl = TextEditingController(text: cam.url);
    final skipCtrl = TextEditingController(text: cam.skipFrames.toString());
    String? error;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => _CameraDialog(
          title: 'ویرایش دوربین',
          children: [
            _LabeledField(label: 'نام دوربین', controller: nameCtrl, hint: 'نام'),
            const SizedBox(height: 12),
            _LabeledField(label: 'آدرس RTSP', controller: urlCtrl, hint: 'rtsp://...'),
            const SizedBox(height: 12),
            _LabeledField(label: 'پرش فریم (۱ تا ۱۰۰۰)', controller: skipCtrl, hint: '15'),
            if (error != null) ...[
              const SizedBox(height: 10),
              Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
            ],
          ],
          onConfirm: () async {
            final skip = int.tryParse(skipCtrl.text.trim());
            if (skip == null || skip < 1 || skip > 1000) {
              setLocal(() => error = 'پرش فریم باید بین ۱ تا ۱۰۰۰ باشد');
              return;
            }
            try {
              await ref.read(_cameraRepoProvider).updateCamera(
                    cam.id,
                    name: nameCtrl.text.trim(),
                    url: urlCtrl.text.trim(),
                    skipFrames: skip,
                  );
              ref.invalidate(cameraListProvider);
              if (ctx.mounted) Navigator.pop(ctx);
            } catch (e) {
              setLocal(() => error = _errMsg(e));
            }
          },
        ),
      ),
    );
  }

  Future<void> _confirmDelete(CameraModel cam) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => _CameraDialog(
        title: 'حذف دوربین',
        confirmLabel: 'حذف',
        danger: true,
        children: [
          Text('آیا از حذف «${cam.name.isEmpty ? cam.url : cam.name}» مطمئن هستید؟',
              style: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 13)),
        ],
        onConfirm: () => Navigator.pop(ctx, true),
      ),
    );
    if (ok == true) {
      try {
        await ref.read(_cameraRepoProvider).deleteCamera(cam.id);
      } catch (e) {
        _toast('حذف ناموفق بود: ${_errMsg(e)}');
      }
      ref.invalidate(cameraListProvider);
    }
  }
}

// ── Toolbar (start/stop all) ─────────────────────────────────────────────────

class _Toolbar extends StatelessWidget {
  final CameraRepo repo;
  final VoidCallback onChanged;
  const _Toolbar({required this.repo, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Row(
        children: [
          Icon(AppIcons.settings2, size: 14, color: Colors.white.withValues(alpha: 0.4)),
          const SizedBox(width: 8),
          Text('کنترل‌ها', style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.5))),
          const Spacer(),
          ToolbarButton(
            icon: AppIcons.play,
            label: 'شروع همه',
            onTap: () async {
              try {
                await repo.startAll();
              } catch (_) {}
              onChanged();
            },
          ),
          const SizedBox(width: 8),
          ToolbarButton(
            icon: AppIcons.square,
            label: 'توقف همه',
            danger: true,
            onTap: () async {
              try {
                await repo.stopAll();
              } catch (_) {}
              onChanged();
            },
          ),
        ],
      ),
    );
  }
}

// ── Status badge ─────────────────────────────────────────────────────────────

class _StatusBadge extends StatelessWidget {
  final String status;
  const _StatusBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    Color color;
    String label;
    switch (status) {
      case 'streaming':
      case 'connected':
        color = const Color(0xFF10B981);
        label = 'فعال';
        break;
      case 'connecting':
        color = const Color(0xFFF59E0B);
        label = 'درحال اتصال';
        break;
      case 'queued':
        color = const Color(0xFF3B82F6);
        label = 'در صف';
        break;
      case 'error':
        color = const Color(0xFFEF4444);
        label = 'خطا';
        break;
      default:
        color = const Color(0xFF6B7280);
        label = 'متوقف';
    }
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: 0.3)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(width: 7, height: 7, decoration: BoxDecoration(shape: BoxShape.circle, color: color)),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color)),
          ],
        ),
      ),
    );
  }
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

class _Tabs extends StatelessWidget {
  final int index;
  final ValueChanged<int> onChanged;
  const _Tabs({required this.index, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    const items = [
      (AppIcons.camera, 'دوربین‌های من'),
      (AppIcons.monitor, 'پایش زنده'),
      (AppIcons.radar, 'پویشگر شبکه'),
    ];
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < items.length; i++)
            MouseRegion(
              cursor: SystemMouseCursors.click,
              child: GestureDetector(
                onTap: () => onChanged(i),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  decoration: BoxDecoration(
                    color: index == i ? const Color(0xFF3B82F6).withValues(alpha: 0.15) : Colors.transparent,
                    borderRadius: BorderRadius.circular(7),
                    border: index == i ? Border.all(color: const Color(0xFF3B82F6).withValues(alpha: 0.3)) : null,
                  ),
                  child: Row(
                    children: [
                      Icon(items[i].$1, size: 15, color: index == i ? const Color(0xFF3B82F6) : Colors.white.withValues(alpha: 0.4)),
                      const SizedBox(width: 8),
                      Text(items[i].$2, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: index == i ? const Color(0xFF3B82F6) : Colors.white.withValues(alpha: 0.5))),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

// ── Shared dialog widgets ──────────────────────────────────────────────────────

class _IconBtn extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String tooltip;
  final VoidCallback? onTap;
  const _IconBtn({required this.icon, required this.color, required this.tooltip, this.onTap});

  @override
  Widget build(BuildContext context) {
    final disabled = onTap == null;
    return Tooltip(
      message: tooltip,
      child: MouseRegion(
        cursor: disabled ? SystemMouseCursors.basic : SystemMouseCursors.click,
        child: GestureDetector(
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: color.withValues(alpha: disabled ? 0.04 : 0.12),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Icon(icon, size: 15, color: color.withValues(alpha: disabled ? 0.3 : 1)),
          ),
        ),
      ),
    );
  }
}

class _LabeledField extends StatelessWidget {
  final String label;
  final TextEditingController controller;
  final String hint;
  const _LabeledField({required this.label, required this.controller, required this.hint});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.6))),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          textDirection: TextDirection.rtl,
          style: const TextStyle(fontSize: 13, color: Colors.white),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.3)),
            filled: true,
            fillColor: Colors.white.withValues(alpha: 0.04),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
            ),
            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          ),
        ),
      ],
    );
  }
}

class _CameraDialog extends StatelessWidget {
  final String title;
  final List<Widget> children;
  final VoidCallback onConfirm;
  final String confirmLabel;
  final bool danger;
  const _CameraDialog({
    required this.title,
    required this.children,
    required this.onConfirm,
    this.confirmLabel = 'تأیید',
    this.danger = false,
  });

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: const Color(0xFF18181B),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Container(
        padding: const EdgeInsets.all(24),
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: Colors.white)),
            const SizedBox(height: 18),
            ...children,
            const SizedBox(height: 20),
            Row(
              children: [
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: danger ? const Color(0xFFEF4444) : const Color(0xFF3B82F6),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  onPressed: onConfirm,
                  child: Text(confirmLabel),
                ),
                const SizedBox(width: 8),
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text('انصراف', style: TextStyle(color: Colors.white.withValues(alpha: 0.5))),
                ),
              ],
            ),
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
