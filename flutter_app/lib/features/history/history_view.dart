// lib/features/history/history_view.dart
// Detection history as a PlutoGrid data grid (sorting + column controls,
// Requirement 17.5) with search/source filters and a CSV export button
// (Requirements 14.1-14.4).

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pluto_grid/pluto_grid.dart';

import '../../core/api_client.dart';
import '../../core/persian_format.dart';
import '../../data/controllers/reports_controller.dart';
import '../../data/models/detection_model.dart';
import '../../data/repositories/detections_repo.dart';
import '../../shared/app_icons.dart';
import '../../shared/download/file_saver.dart';
import '../../shared/widgets/app_data_grid.dart';
import '../../shared/widgets/screen_shell.dart';

// ── State + controller ───────────────────────────────────────────────────

class _HistoryState {
  final DetectionsResponse? data;
  final bool loading;
  final String? error;
  final String sourceType;
  final String search;
  final int offset;
  final int limit;

  const _HistoryState({
    this.data,
    this.loading = false,
    this.error,
    this.sourceType = 'all',
    this.search = '',
    this.offset = 0,
    this.limit = 50,
  });

  _HistoryState copyWith({
    DetectionsResponse? data,
    bool? loading,
    String? error,
    String? sourceType,
    String? search,
    int? offset,
    int? limit,
    bool clearError = false,
  }) =>
      _HistoryState(
        data: data ?? this.data,
        loading: loading ?? this.loading,
        error: clearError ? null : (error ?? this.error),
        sourceType: sourceType ?? this.sourceType,
        search: search ?? this.search,
        offset: offset ?? this.offset,
        limit: limit ?? this.limit,
      );
}

class _HistoryController extends StateNotifier<_HistoryState> {
  final DetectionsRepo _repo;
  Timer? _debounce;

  _HistoryController(this._repo) : super(const _HistoryState()) {
    fetch();
  }

  Future<void> fetch() async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final result = await _repo.getDetections(
        limit: state.limit,
        offset: state.offset,
        sourceType: state.sourceType,
        search: state.search,
      );
      state = state.copyWith(data: result, loading: false);
    } catch (e) {
      state = state.copyWith(loading: false, error: _errorMessage(e));
    }
  }

  void setSourceType(String type) {
    state = state.copyWith(sourceType: type, offset: 0);
    fetch();
  }

  void setSearch(String query) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      state = state.copyWith(search: query, offset: 0);
      fetch();
    });
  }

  void nextPage() {
    state = state.copyWith(offset: state.offset + state.limit);
    fetch();
  }

  void prevPage() {
    final newOffset = (state.offset - state.limit).clamp(0, state.offset);
    state = state.copyWith(offset: newOffset);
    fetch();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }
}

final _historyRepoProvider = Provider((_) => DetectionsRepo());
final _historyControllerProvider =
    StateNotifierProvider<_HistoryController, _HistoryState>(
        (ref) => _HistoryController(ref.read(_historyRepoProvider)));

// ── View ───────────────────────────────────────────────────────────────────

class HistoryView extends ConsumerWidget {
  const HistoryView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(_historyControllerProvider);
    final controller = ref.read(_historyControllerProvider.notifier);

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ScreenHeader(
            title: 'تاریخچه تشخیص‌ها',
            subtitle: 'مرور و خروجی‌گیری از پلاک‌های ثبت‌شده',
            actions: [
              ToolbarButton(
                icon: AppIcons.refreshCw,
                label: 'بازخوانی',
                onTap: controller.fetch,
              ),
              const SizedBox(width: 8),
              const _ExportButton(),
            ],
          ),
          const SizedBox(height: 20),
          _FilterBar(
            sourceType: state.sourceType,
            onSearch: controller.setSearch,
            onSource: controller.setSourceType,
          ),
          const SizedBox(height: 16),
          Expanded(child: _HistoryBody(state: state, controller: controller)),
        ],
      ),
    );
  }
}

// ── Export button ───────────────────────────────────────────────────────────

class _ExportButton extends ConsumerStatefulWidget {
  const _ExportButton();

  @override
  ConsumerState<_ExportButton> createState() => _ExportButtonState();
}

class _ExportButtonState extends ConsumerState<_ExportButton> {
  bool _busy = false;

  Future<void> _export() async {
    if (_busy) return;
    setState(() => _busy = true);
    final state = ref.read(_historyControllerProvider);
    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      final bytes = await ref.read(reportsControllerProvider.notifier).exportDetections(
            sourceType: state.sourceType == 'all' ? null : state.sourceType,
            search: state.search.isEmpty ? null : state.search,
          );
      final stamp = DateTime.now().toIso8601String().substring(0, 19).replaceAll(':', '-');
      final saved = await saveBytes('detections_$stamp.csv', bytes);
      messenger?.showSnackBar(
        SnackBar(
          content: Text(saved == null ? 'خروجی لغو شد' : 'خروجی ذخیره شد'),
          backgroundColor: const Color(0xFF18181B),
        ),
      );
    } catch (e) {
      messenger?.showSnackBar(
        SnackBar(
          content: Text('خطا در خروجی‌گیری: ${_errorMessage(e)}'),
          backgroundColor: const Color(0xFF7F1D1D),
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ToolbarButton(
      icon: _busy ? AppIcons.loader2 : AppIcons.upload,
      label: _busy ? 'در حال خروجی...' : 'خروجی CSV',
      primary: true,
      onTap: _busy ? null : _export,
    );
  }
}

// ── Filter bar ───────────────────────────────────────────────────────────────

class _FilterBar extends StatelessWidget {
  final String sourceType;
  final ValueChanged<String> onSearch;
  final ValueChanged<String> onSource;

  const _FilterBar({
    required this.sourceType,
    required this.onSearch,
    required this.onSource,
  });

  @override
  Widget build(BuildContext context) {
    const sources = <String, String>{
      'all': 'همه',
      'image': 'تصویر',
      'video': 'ویدیو',
      'rtsp': 'دوربین',
    };
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Row(
        children: [
          Expanded(
            child: SizedBox(
              height: 38,
              child: TextField(
                style: const TextStyle(fontSize: 13, color: Colors.white),
                textDirection: TextDirection.rtl,
                decoration: InputDecoration(
                  hintText: 'جستجوی پلاک...',
                  hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.3)),
                  prefixIcon: Icon(AppIcons.search, size: 16, color: Colors.white.withValues(alpha: 0.4)),
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
                  contentPadding: const EdgeInsets.symmetric(vertical: 4),
                ),
                onChanged: onSearch,
              ),
            ),
          ),
          const SizedBox(width: 12),
          ...sources.entries.map((e) => Padding(
                padding: const EdgeInsets.only(left: 6),
                child: _Chip(
                  label: e.value,
                  selected: sourceType == e.key,
                  onTap: () => onSource(e.key),
                ),
              )),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;
  const _Chip({required this.label, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFF3B82F6);
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: selected ? accent.withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.04),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(
              color: selected ? accent.withValues(alpha: 0.3) : Colors.white.withValues(alpha: 0.08),
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: selected ? accent : Colors.white.withValues(alpha: 0.6),
            ),
          ),
        ),
      ),
    );
  }
}

// ── Body ─────────────────────────────────────────────────────────────────────

class _HistoryBody extends StatelessWidget {
  final _HistoryState state;
  final _HistoryController controller;
  const _HistoryBody({required this.state, required this.controller});

  @override
  Widget build(BuildContext context) {
    if (state.loading && state.data == null) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }
    if (state.error != null && state.data == null) {
      return GridStatePlaceholder(
        icon: AppIcons.alertCircle,
        message: 'بارگیری تاریخچه ممکن نشد\n${state.error}',
        onRetry: controller.fetch,
      );
    }
    final resp = state.data;
    if (resp == null) return const SizedBox.shrink();

    return Column(
      children: [
        Expanded(
          child: resp.data.isEmpty
              ? const GridStatePlaceholder(
                  icon: AppIcons.history,
                  message: 'تشخیصی مطابق فیلتر فعلی یافت نشد.',
                )
              : AppDataGrid(
                  key: ValueKey('history_${state.offset}_${state.sourceType}_${state.search}'),
                  columns: _columns(),
                  rows: resp.data.map(_rowFor).toList(),
                ),
        ),
        const SizedBox(height: 12),
        _Pager(state: state, controller: controller, total: resp.total),
      ],
    );
  }

  List<PlutoColumn> _columns() => [
        PlutoColumn(
          title: 'پلاک',
          field: 'plate',
          type: PlutoColumnType.text(),
          minWidth: 160,
        ),
        PlutoColumn(
          title: 'متن خام',
          field: 'dtrb',
          type: PlutoColumnType.text(),
          minWidth: 120,
        ),
        PlutoColumn(
          title: 'منبع',
          field: 'source',
          type: PlutoColumnType.text(),
          width: 110,
        ),
        PlutoColumn(
          title: 'دوربین',
          field: 'camera',
          type: PlutoColumnType.text(),
          minWidth: 120,
        ),
        PlutoColumn(
          title: 'زمان',
          field: 'time',
          type: PlutoColumnType.text(),
          minWidth: 170,
        ),
        PlutoColumn(
          title: 'اطمینان',
          field: 'confidence',
          type: PlutoColumnType.number(),
          width: 110,
          renderer: (ctx) {
            final pct = (ctx.cell.value as num).toDouble();
            final color = pct >= 80
                ? const Color(0xFF10B981)
                : pct >= 60
                    ? const Color(0xFFF59E0B)
                    : const Color(0xFFEF4444);
            return Text(
              PersianFormat.percentage(pct / 100),
              style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 13),
            );
          },
        ),
      ];

  PlutoRow _rowFor(DetectionModel d) {
    final plate = (d.platePersian?.isNotEmpty ?? false) ? d.platePersian! : d.plateDtrb;
    return PlutoRow(cells: {
      'plate': PlutoCell(value: plate),
      'dtrb': PlutoCell(value: d.plateDtrb),
      'source': PlutoCell(value: _sourceLabel(d.sourceType)),
      'camera': PlutoCell(value: d.cameraName ?? '—'),
      'time': PlutoCell(value: _formatTs(d.timestamp)),
      'confidence': PlutoCell(value: double.parse((d.confidence * 100).toStringAsFixed(1))),
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

class _Pager extends StatelessWidget {
  final _HistoryState state;
  final _HistoryController controller;
  final int total;
  const _Pager({required this.state, required this.controller, required this.total});

  @override
  Widget build(BuildContext context) {
    final shown = state.data?.data.length ?? 0;
    final from = total == 0 ? 0 : state.offset + 1;
    final to = state.offset + shown;
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _PagerBtn(
          icon: AppIcons.chevronRight,
          onTap: state.offset > 0 ? controller.prevPage : null,
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Text(
            '${PersianFormat.number(from)}–${PersianFormat.number(to)} از ${PersianFormat.number(total)}',
            style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.5)),
          ),
        ),
        _PagerBtn(
          icon: AppIcons.chevronLeft,
          onTap: (state.offset + state.limit) < total ? controller.nextPage : null,
        ),
      ],
    );
  }
}

class _PagerBtn extends StatelessWidget {
  final IconData icon;
  final VoidCallback? onTap;
  const _PagerBtn({required this.icon, this.onTap});

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: onTap == null ? SystemMouseCursors.basic : SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.04),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
          ),
          child: Icon(
            icon,
            size: 16,
            color: onTap != null ? Colors.white.withValues(alpha: 0.7) : Colors.white.withValues(alpha: 0.2),
          ),
        ),
      ),
    );
  }
}

String _errorMessage(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
