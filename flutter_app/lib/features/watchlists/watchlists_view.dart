// lib/features/watchlists/watchlists_view.dart
// Watchlists & Alerts screen. Watchlist entries and alerts are rendered with
// PlutoGrid (Requirement 17.5); management controls are gated by the
// manage_watchlists permission (Requirement 18.4).

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pluto_grid/pluto_grid.dart';

import '../../core/persian_format.dart';
import '../../data/controllers/alerts_controller.dart';
import '../../data/controllers/watchlists_controller.dart';
import '../../data/models/watchlist.dart';
import '../../data/models/watchlist_entry.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/app_data_grid.dart';
import '../../shared/widgets/permission_gate.dart' show Permissions;
import '../../shared/widgets/screen_shell.dart';

class WatchlistsView extends ConsumerStatefulWidget {
  const WatchlistsView({super.key});

  @override
  ConsumerState<WatchlistsView> createState() => _WatchlistsViewState();
}

class _WatchlistsViewState extends ConsumerState<WatchlistsView> {
  int _tab = 0; // 0 = watchlists, 1 = alerts
  int? _selectedWatchlistId;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(watchlistsControllerProvider.notifier).loadWatchlists();
      ref.read(alertsControllerProvider.notifier).loadAlerts(limit: 200);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ScreenHeader(
            title: 'فهرست‌های نظارت و هشدارها',
            subtitle: 'مدیریت فهرست پلاک‌ها و مشاهده هشدارهای تطبیق',
            actions: [
              ToolbarButton(
                icon: AppIcons.refreshCw,
                label: 'بازخوانی',
                onTap: () {
                  ref.read(watchlistsControllerProvider.notifier).loadWatchlists();
                  ref.read(alertsControllerProvider.notifier).loadAlerts(limit: 200);
                },
              ),
            ],
          ),
          const SizedBox(height: 16),
          _Tabs(
            index: _tab,
            onChanged: (i) => setState(() => _tab = i),
          ),
          const SizedBox(height: 16),
          Expanded(child: _tab == 0 ? _buildWatchlists() : _buildAlerts()),
        ],
      ),
    );
  }

  // ── Watchlists tab ────────────────────────────────────────────────────────

  Widget _buildWatchlists() {
    final state = ref.watch(watchlistsControllerProvider);
    if (state.loading && state.watchlists.isEmpty) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }
    if (state.error != null && state.watchlists.isEmpty) {
      return GridStatePlaceholder(
        icon: AppIcons.alertCircle,
        message: 'بارگیری فهرست‌ها ممکن نشد\n${state.error}',
        onRetry: () => ref.read(watchlistsControllerProvider.notifier).loadWatchlists(),
      );
    }

    final watchlists = state.watchlists;
    final selectedId = _selectedWatchlistId ??
        (watchlists.isNotEmpty ? watchlists.first.id : null);
    final selected = watchlists.where((w) => w.id == selectedId).cast<Watchlist?>().firstWhere(
          (w) => true,
          orElse: () => null,
        );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final w in watchlists)
                    _WatchlistChip(
                      watchlist: w,
                      selected: w.id == selectedId,
                      onTap: () => setState(() => _selectedWatchlistId = w.id),
                    ),
                ],
              ),
            ),
            SessionPermissionGate(
              permission: Permissions.manageWatchlists,
              child: ToolbarButton(
                icon: AppIcons.plus,
                label: 'فهرست جدید',
                primary: true,
                onTap: _showCreateWatchlistDialog,
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (watchlists.isEmpty)
          const Expanded(
            child: GridStatePlaceholder(
              icon: AppIcons.layers,
              message: 'هنوز فهرستی ایجاد نشده است.',
            ),
          )
        else ...[
          Row(
            children: [
              Text(
                'مدخل‌های «${selected?.name ?? ''}»',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Color(0xFFFAFAFA)),
              ),
              const Spacer(),
              if (selected != null)
                SessionPermissionGate(
                  permission: Permissions.manageWatchlists,
                  child: ToolbarButton(
                    icon: AppIcons.plus,
                    label: 'افزودن پلاک',
                    onTap: () => _showAddEntryDialog(selected.id),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(
            child: (selected == null || selected.entries.isEmpty)
                ? const GridStatePlaceholder(
                    icon: AppIcons.creditCard,
                    message: 'این فهرست مدخلی ندارد.',
                  )
                : AppDataGrid(
                    key: ValueKey('wl_${selected.id}_${selected.entries.length}'),
                    columns: _entryColumns(),
                    rows: selected.entries.map(_entryRow).toList(),
                  ),
          ),
        ],
      ],
    );
  }

  List<PlutoColumn> _entryColumns() {
    final canManage = sessionHasPermission(ref, Permissions.manageWatchlists);
    return [
      PlutoColumn(title: 'پلاک', field: 'plate', type: PlutoColumnType.text(), minWidth: 160),
      PlutoColumn(title: 'برچسب', field: 'label', type: PlutoColumnType.text(), minWidth: 140),
      PlutoColumn(title: 'دلیل', field: 'reason', type: PlutoColumnType.text(), minWidth: 180),
      PlutoColumn(title: 'تاریخ افزودن', field: 'created', type: PlutoColumnType.text(), minWidth: 160),
      PlutoColumn(
        title: 'عملیات',
        field: 'actions',
        type: PlutoColumnType.text(),
        width: 110,
        enableSorting: false,
        enableContextMenu: false,
        renderer: (ctx) {
          final id = ctx.cell.value as int;
          if (!canManage) {
            return Text('—', style: TextStyle(color: Colors.white.withValues(alpha: 0.3)));
          }
          return Align(
            alignment: Alignment.centerRight,
            child: _IconBtn(
              icon: AppIcons.trash2,
              color: const Color(0xFFEF4444),
              onTap: () => _confirmDeleteEntry(id),
            ),
          );
        },
      ),
    ];
  }

  PlutoRow _entryRow(WatchlistEntry e) => PlutoRow(cells: {
        'plate': PlutoCell(value: e.plateValue),
        'label': PlutoCell(value: e.label ?? '—'),
        'reason': PlutoCell(value: e.reason ?? '—'),
        'created': PlutoCell(value: _formatTs(e.createdAt)),
        'actions': PlutoCell(value: e.id),
      });

  // ── Alerts tab ───────────────────────────────────────────────────────────

  Widget _buildAlerts() {
    final state = ref.watch(alertsControllerProvider);
    if (state.loading && state.alerts.isEmpty) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }
    if (state.error != null && state.alerts.isEmpty) {
      return GridStatePlaceholder(
        icon: AppIcons.alertCircle,
        message: 'بارگیری هشدارها ممکن نشد\n${state.error}',
        onRetry: () => ref.read(alertsControllerProvider.notifier).loadAlerts(limit: 200),
      );
    }
    if (state.alerts.isEmpty) {
      return const GridStatePlaceholder(
        icon: AppIcons.checkCircle,
        message: 'هیچ هشداری ثبت نشده است.',
      );
    }
    return AppDataGrid(
      key: ValueKey('alerts_${state.alerts.length}'),
      columns: [
        PlutoColumn(
          title: 'شناسه',
          field: 'id',
          type: PlutoColumnType.number(),
          width: 90,
          renderer: (ctx) => Text(
            PersianFormat.number(ctx.cell.value as num),
            style: const TextStyle(color: Color(0xFFFAFAFA), fontSize: 13),
          ),
        ),
        PlutoColumn(title: 'پلاک', field: 'plate', type: PlutoColumnType.text(), minWidth: 160),
        PlutoColumn(
          title: 'شناسه تشخیص',
          field: 'detection',
          type: PlutoColumnType.number(),
          width: 130,
          renderer: (ctx) => Text(
            PersianFormat.number(ctx.cell.value as num),
            style: const TextStyle(color: Color(0xFFFAFAFA), fontSize: 13),
          ),
        ),
        PlutoColumn(title: 'زمان', field: 'time', type: PlutoColumnType.text(), minWidth: 170),
      ],
      rows: state.alerts
          .map((a) => PlutoRow(cells: {
                'id': PlutoCell(value: a.id),
                'plate': PlutoCell(value: a.plateValue),
                'detection': PlutoCell(value: a.detectionId),
                'time': PlutoCell(value: _formatTs(a.createdAt)),
              }))
          .toList(),
    );
  }

  // ── Dialogs ────────────────────────────────────────────────────────────────

  Future<void> _showCreateWatchlistDialog() async {
    final nameCtrl = TextEditingController();
    String listType = 'blocklist';
    String? error;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => _DialogShell(
          title: 'ایجاد فهرست نظارت',
          children: [
            _LabeledField(label: 'نام فهرست', controller: nameCtrl, hint: 'مثلاً خودروهای مشکوک'),
            const SizedBox(height: 12),
            Text('نوع فهرست', style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.6))),
            const SizedBox(height: 6),
            Row(
              children: [
                _TypeOption(label: 'فهرست مسدود', selected: listType == 'blocklist', onTap: () => setLocal(() => listType = 'blocklist')),
                const SizedBox(width: 8),
                _TypeOption(label: 'فهرست مجاز', selected: listType == 'allowlist', onTap: () => setLocal(() => listType = 'allowlist')),
              ],
            ),
            if (error != null) ...[
              const SizedBox(height: 10),
              Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
            ],
          ],
          onConfirm: () async {
            if (nameCtrl.text.trim().isEmpty) {
              setLocal(() => error = 'نام فهرست الزامی است');
              return;
            }
            try {
              await ref.read(watchlistsControllerProvider.notifier).createWatchlist(
                    name: nameCtrl.text.trim(),
                    listType: listType,
                  );
              if (ctx.mounted) Navigator.pop(ctx);
            } catch (e) {
              setLocal(() => error = e.toString());
            }
          },
        ),
      ),
    );
  }

  Future<void> _showAddEntryDialog(int watchlistId) async {
    final plateCtrl = TextEditingController();
    final labelCtrl = TextEditingController();
    final reasonCtrl = TextEditingController();
    String? error;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => _DialogShell(
          title: 'افزودن پلاک به فهرست',
          children: [
            _LabeledField(label: 'مقدار پلاک', controller: plateCtrl, hint: 'پلاک را وارد کنید'),
            const SizedBox(height: 12),
            _LabeledField(label: 'برچسب (اختیاری)', controller: labelCtrl, hint: 'مثلاً خودروی سرقتی'),
            const SizedBox(height: 12),
            _LabeledField(label: 'دلیل (اختیاری)', controller: reasonCtrl, hint: 'توضیح'),
            if (error != null) ...[
              const SizedBox(height: 10),
              Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
            ],
          ],
          onConfirm: () async {
            if (plateCtrl.text.trim().isEmpty) {
              setLocal(() => error = 'مقدار پلاک الزامی است');
              return;
            }
            try {
              await ref.read(watchlistsControllerProvider.notifier).addEntry(
                    watchlistId: watchlistId,
                    plateValue: plateCtrl.text.trim(),
                    label: labelCtrl.text.trim().isEmpty ? null : labelCtrl.text.trim(),
                    reason: reasonCtrl.text.trim().isEmpty ? null : reasonCtrl.text.trim(),
                  );
              if (ctx.mounted) Navigator.pop(ctx);
            } catch (e) {
              setLocal(() => error = e.toString());
            }
          },
        ),
      ),
    );
  }

  Future<void> _confirmDeleteEntry(int entryId) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => _DialogShell(
        title: 'حذف مدخل',
        confirmLabel: 'حذف',
        danger: true,
        children: [
          Text(
            'آیا از حذف این پلاک از فهرست مطمئن هستید؟',
            style: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 13),
          ),
        ],
        onConfirm: () => Navigator.pop(ctx, true),
      ),
    );
    if (ok == true) {
      await ref.read(watchlistsControllerProvider.notifier).deleteEntry(entryId);
    }
  }
}

String _formatTs(String ts) {
  final dt = DateTime.tryParse(ts);
  if (dt == null) return ts;
  return PersianFormat.dateTime(dt);
}

// ── Small widgets ─────────────────────────────────────────────────────────────

class _Tabs extends StatelessWidget {
  final int index;
  final ValueChanged<int> onChanged;
  const _Tabs({required this.index, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    const items = [
      (AppIcons.layers, 'فهرست‌ها'),
      (AppIcons.alertCircle, 'هشدارها'),
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

class _WatchlistChip extends StatelessWidget {
  final Watchlist watchlist;
  final bool selected;
  final VoidCallback onTap;
  const _WatchlistChip({required this.watchlist, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final accent = watchlist.isBlocklist ? const Color(0xFFEF4444) : const Color(0xFF10B981);
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: selected ? accent.withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.04),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: selected ? accent.withValues(alpha: 0.4) : Colors.white.withValues(alpha: 0.08)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(shape: BoxShape.circle, color: accent)),
              const SizedBox(width: 8),
              Text(watchlist.name, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: selected ? Colors.white : Colors.white.withValues(alpha: 0.7))),
              const SizedBox(width: 6),
              Text('(${PersianFormat.number(watchlist.entryCount)})', style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.4))),
            ],
          ),
        ),
      ),
    );
  }
}

class _IconBtn extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback onTap;
  const _IconBtn({required this.icon, required this.color, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Icon(icon, size: 15, color: color),
        ),
      ),
    );
  }
}

class _TypeOption extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;
  const _TypeOption({required this.label, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFF3B82F6);
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
          decoration: BoxDecoration(
            color: selected ? accent.withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.04),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: selected ? accent.withValues(alpha: 0.3) : Colors.white.withValues(alpha: 0.08)),
          ),
          child: Text(label, style: TextStyle(fontSize: 12.5, color: selected ? accent : Colors.white.withValues(alpha: 0.6))),
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

class _DialogShell extends StatelessWidget {
  final String title;
  final List<Widget> children;
  final VoidCallback onConfirm;
  final String confirmLabel;
  final bool danger;
  const _DialogShell({
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
              mainAxisAlignment: MainAxisAlignment.start,
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
