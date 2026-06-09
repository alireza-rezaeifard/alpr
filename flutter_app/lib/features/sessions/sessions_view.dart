// lib/features/sessions/sessions_view.dart
// Session history rendered as a PlutoGrid data grid (sorting + column controls,
// Requirement 17.5), most-recent-first.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pluto_grid/pluto_grid.dart';

import '../../core/api_client.dart';
import '../../core/persian_format.dart';
import '../../data/models/session_model.dart';
import '../../data/repositories/sessions_repo.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/app_data_grid.dart';
import '../../shared/widgets/screen_shell.dart';

final _sessionsRepoProvider = Provider((_) => SessionsRepo());

final sessionsProvider = FutureProvider<List<SessionModel>>((ref) =>
    ref.read(_sessionsRepoProvider).getSessions(limit: 100));

class SessionsView extends ConsumerWidget {
  const SessionsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sessionsAsync = ref.watch(sessionsProvider);

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ScreenHeader(
            title: 'جلسات',
            subtitle: 'تاریخچه جلسات پردازش',
            actions: [
              ToolbarButton(
                icon: AppIcons.refreshCw,
                label: 'بازخوانی',
                onTap: () => ref.invalidate(sessionsProvider),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Expanded(
            child: sessionsAsync.when(
              loading: () => const Center(child: CircularProgressIndicator(strokeWidth: 2)),
              error: (e, _) => GridStatePlaceholder(
                icon: AppIcons.alertCircle,
                message: 'بارگیری جلسات ممکن نشد\n${_errorMsg(e)}',
                onRetry: () => ref.invalidate(sessionsProvider),
              ),
              data: (sessions) {
                if (sessions.isEmpty) {
                  return const GridStatePlaceholder(
                    icon: AppIcons.layers,
                    message: 'هنوز جلسه‌ای ثبت نشده است.',
                  );
                }
                return AppDataGrid(
                  key: ValueKey('sessions_${sessions.length}'),
                  columns: _columns(),
                  rows: sessions.map(_rowFor).toList(),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  List<PlutoColumn> _columns() => [
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
        PlutoColumn(title: 'نوع منبع', field: 'source', type: PlutoColumnType.text(), width: 120),
        PlutoColumn(title: 'فایل/منبع', field: 'file', type: PlutoColumnType.text(), minWidth: 180),
        PlutoColumn(title: 'شروع', field: 'started', type: PlutoColumnType.text(), minWidth: 170),
        PlutoColumn(
          title: 'مدت',
          field: 'duration',
          type: PlutoColumnType.text(),
          width: 120,
        ),
        PlutoColumn(
          title: 'پلاک‌ها',
          field: 'plates',
          type: PlutoColumnType.number(),
          width: 100,
          renderer: (ctx) => Text(
            PersianFormat.number(ctx.cell.value as num),
            style: const TextStyle(color: Color(0xFFFAFAFA), fontSize: 13),
          ),
        ),
        PlutoColumn(
          title: 'یکتا',
          field: 'unique',
          type: PlutoColumnType.number(),
          width: 90,
          renderer: (ctx) => Text(
            PersianFormat.number(ctx.cell.value as num),
            style: const TextStyle(color: Color(0xFFFAFAFA), fontSize: 13),
          ),
        ),
        PlutoColumn(
          title: 'وضعیت',
          field: 'status',
          type: PlutoColumnType.text(),
          width: 120,
          renderer: (ctx) => _StatusBadge(status: ctx.cell.value as String),
        ),
      ];

  PlutoRow _rowFor(SessionModel s) {
    final dur = s.durationSeconds;
    return PlutoRow(cells: {
      'id': PlutoCell(value: s.id),
      'source': PlutoCell(value: _sourceLabel(s.sourceType)),
      'file': PlutoCell(value: s.sourceFile ?? '—'),
      'started': PlutoCell(value: _formatTs(s.startedAt)),
      'duration': PlutoCell(value: dur == null ? 'در حال اجرا' : PersianFormat.duration(Duration(seconds: dur))),
      'plates': PlutoCell(value: s.totalPlates),
      'unique': PlutoCell(value: s.uniquePlates),
      'status': PlutoCell(value: s.status),
    });
  }
}

String _sourceLabel(String type) {
  switch (type) {
    case 'image':
      return 'تصویر';
    case 'video':
      return 'ویدیو';
    case 'rtsp':
      return 'دوربین';
    default:
      return type;
  }
}

String _formatTs(String ts) {
  final dt = DateTime.tryParse(ts);
  if (dt == null) return ts;
  return PersianFormat.dateTime(dt);
}

class _StatusBadge extends StatelessWidget {
  final String status;
  const _StatusBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    Color color;
    String label;
    switch (status) {
      case 'done':
        color = const Color(0xFF10B981);
        label = 'پایان‌یافته';
        break;
      case 'error':
        color = const Color(0xFFEF4444);
        label = 'خطا';
        break;
      case 'running':
        color = const Color(0xFFF59E0B);
        label = 'در حال اجرا';
        break;
      default:
        color = const Color(0xFF6B7280);
        label = status;
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
        child: Text(
          label,
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color),
        ),
      ),
    );
  }
}

String _errorMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
