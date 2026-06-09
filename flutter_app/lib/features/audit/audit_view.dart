// lib/features/audit/audit_view.dart
// Audit log (Admin) screen rendered with PlutoGrid (Requirement 17.5),
// most-recent-first. Access is gated by the view_audit permission.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pluto_grid/pluto_grid.dart';

import '../../core/persian_format.dart';
import '../../data/controllers/audit_controller.dart';
import '../../data/models/audit_entry.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/app_data_grid.dart';
import '../../shared/widgets/permission_gate.dart' show Permissions, PermissionDeniedView;
import '../../shared/widgets/screen_shell.dart';

class AuditView extends ConsumerStatefulWidget {
  const AuditView({super.key});

  @override
  ConsumerState<AuditView> createState() => _AuditViewState();
}

class _AuditViewState extends ConsumerState<AuditView> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(auditControllerProvider.notifier).loadAuditLog(limit: 200);
    });
  }

  @override
  Widget build(BuildContext context) {
    final canView = sessionHasPermission(ref, Permissions.viewAudit);
    final state = ref.watch(auditControllerProvider);

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ScreenHeader(
            title: 'گزارش رخدادها',
            subtitle: 'رخدادهای امنیتی ثبت‌شده (تنها‌افزودنی)',
            actions: [
              ToolbarButton(
                icon: AppIcons.refreshCw,
                label: 'بازخوانی',
                onTap: () => ref.read(auditControllerProvider.notifier).loadAuditLog(limit: 200),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Expanded(
            child: !canView
                ? const PermissionDeniedView(
                    message: 'تنها مدیر می‌تواند گزارش رخدادها را مشاهده کند.',
                  )
                : _buildBody(state),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(AuditState state) {
    if (state.loading && state.entries.isEmpty) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }
    if (state.error != null && state.entries.isEmpty) {
      return GridStatePlaceholder(
        icon: AppIcons.alertCircle,
        message: 'بارگیری گزارش‌ها ممکن نشد\n${state.error}',
        onRetry: () => ref.read(auditControllerProvider.notifier).loadAuditLog(limit: 200),
      );
    }
    if (state.entries.isEmpty) {
      return const GridStatePlaceholder(
        icon: AppIcons.history,
        message: 'رخدادی ثبت نشده است.',
      );
    }
    return AppDataGrid(
      key: ValueKey('audit_${state.entries.length}'),
      columns: _columns(),
      rows: state.entries.map(_rowFor).toList(),
    );
  }

  List<PlutoColumn> _columns() => [
        PlutoColumn(title: 'زمان', field: 'time', type: PlutoColumnType.text(), minWidth: 170),
        PlutoColumn(title: 'کاربر', field: 'user', type: PlutoColumnType.text(), minWidth: 130),
        PlutoColumn(title: 'اقدام', field: 'action', type: PlutoColumnType.text(), minWidth: 150),
        PlutoColumn(title: 'منبع', field: 'resource', type: PlutoColumnType.text(), minWidth: 150),
        PlutoColumn(
          title: 'نتیجه',
          field: 'outcome',
          type: PlutoColumnType.text(),
          width: 120,
          renderer: (ctx) {
            final ok = ctx.cell.value == 'success';
            final color = ok ? const Color(0xFF10B981) : const Color(0xFFEF4444);
            return Align(
              alignment: Alignment.centerRight,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: color.withValues(alpha: 0.3)),
                ),
                child: Text(
                  ok ? 'موفق' : 'ناموفق',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color),
                ),
              ),
            );
          },
        ),
      ];

  PlutoRow _rowFor(AuditEntry e) => PlutoRow(cells: {
        'time': PlutoCell(value: _formatTs(e.timestamp)),
        'user': PlutoCell(value: e.username ?? '—'),
        'action': PlutoCell(value: e.action),
        'resource': PlutoCell(value: e.resource ?? '—'),
        'outcome': PlutoCell(value: e.wasSuccessful ? 'success' : 'failure'),
      });
}

String _formatTs(String ts) {
  final dt = DateTime.tryParse(ts);
  if (dt == null) return ts;
  return PersianFormat.dateTime(dt);
}
