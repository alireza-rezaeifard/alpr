// lib/features/history/history_view.dart
// Modern searchable, filterable detection history with clean data table.

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../shared/app_icons.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../../data/models/detection_model.dart';
import '../../data/repositories/detections_repo.dart';
import '../../core/api_client.dart';

// ── State ──────────────────────────────────────────────────────────────────

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

// ── Controller ─────────────────────────────────────────────────────────────

class _HistoryController extends StateNotifier<_HistoryState> {
  final DetectionsRepo _repo;
  Timer? _debounce;

  _HistoryController(this._repo) : super(const _HistoryState()) {
    _fetch();
  }

  Future<void> _fetch() async {
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
    _fetch();
  }

  void setSearch(String query) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      state = state.copyWith(search: query, offset: 0);
      _fetch();
    });
  }

  void nextPage() {
    state = state.copyWith(offset: state.offset + state.limit);
    _fetch();
  }

  void prevPage() {
    final newOffset = (state.offset - state.limit).clamp(0, state.offset);
    state = state.copyWith(offset: newOffset);
    _fetch();
  }

  void retry() => _fetch();

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }
}

// ── Providers ──────────────────────────────────────────────────────────────

final _historyRepoProvider = Provider((_) => DetectionsRepo());
final _historyControllerProvider =
    StateNotifierProvider<_HistoryController, _HistoryState>(
        (ref) => _HistoryController(ref.read(_historyRepoProvider)));

// ── View ───────────────────────────────────────────────────────────────────

class HistoryView extends ConsumerWidget {
  const HistoryView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
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
            // Filters
            _FilterBar(),
            const SizedBox(height: 16),
            // Table
            Expanded(child: _HistoryTable()),
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
              'Detection History',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Browse all detected license plates',
              style: TextStyle(
                fontSize: 14,
                color: Colors.white.withOpacity(0.5),
              ),
            ),
          ],
        ),
      ],
    ).animate().fadeIn(duration: 400.ms).slideX(begin: -0.02);
  }
}

// ── Filter bar ─────────────────────────────────────────────────────────────

class _FilterBar extends ConsumerStatefulWidget {
  @override
  ConsumerState<_FilterBar> createState() => _FilterBarState();
}

class _FilterBarState extends ConsumerState<_FilterBar> {
  final _searchCtrl = TextEditingController();

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = ref.read(_historyControllerProvider.notifier);
    final sourceType = ref.watch(_historyControllerProvider).sourceType;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Row(
        children: [
          // Search
          Expanded(
            child: Container(
              height: 38,
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.04),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.white.withOpacity(0.08)),
              ),
              child: TextField(
                controller: _searchCtrl,
                style: const TextStyle(fontSize: 13, color: Colors.white),
                decoration: InputDecoration(
                  hintText: 'Search plates...',
                  hintStyle: TextStyle(color: Colors.white.withOpacity(0.3)),
                  prefixIcon: Icon(AppIcons.search, size: 16, color: Colors.white.withOpacity(0.4)),
                  border: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(vertical: 10),
                ),
                onChanged: controller.setSearch,
              ),
            ),
          ),
          const SizedBox(width: 12),
          // Source type filter chips
          _FilterChip(label: 'All', isSelected: sourceType == 'all', onTap: () => controller.setSourceType('all')),
          const SizedBox(width: 6),
          _FilterChip(label: 'Image', isSelected: sourceType == 'image', onTap: () => controller.setSourceType('image')),
          const SizedBox(width: 6),
          _FilterChip(label: 'Video', isSelected: sourceType == 'video', onTap: () => controller.setSourceType('video')),
          const SizedBox(width: 6),
          _FilterChip(label: 'RTSP', isSelected: sourceType == 'rtsp', onTap: () => controller.setSourceType('rtsp')),
        ],
      ),
    ).animate().fadeIn(duration: 400.ms, delay: 100.ms);
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _FilterChip({required this.label, required this.isSelected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected ? const Color(0xFF3B82F6).withOpacity(0.15) : Colors.white.withOpacity(0.04),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
            color: isSelected ? const Color(0xFF3B82F6).withOpacity(0.3) : Colors.white.withOpacity(0.08),
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w500,
            color: isSelected ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.6),
          ),
        ),
      ),
    );
  }
}

// ── History table ──────────────────────────────────────────────────────────

class _HistoryTable extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(_historyControllerProvider);
    final controller = ref.read(_historyControllerProvider.notifier);

    if (state.loading && state.data == null) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }

    if (state.error != null && state.data == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(AppIcons.alertCircle, size: 48, color: Colors.white.withOpacity(0.3)),
            const SizedBox(height: 12),
            Text('Could not load history',
                style: TextStyle(color: Colors.white.withOpacity(0.5))),
            const SizedBox(height: 8),
            TextButton(onPressed: controller.retry, child: const Text('Retry')),
          ],
        ),
      );
    }

    final resp = state.data;

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        children: [
          // Error banner
          if (state.error != null)
            Container(
              padding: const EdgeInsets.all(10),
              color: const Color(0xFFEF4444).withOpacity(0.1),
              child: Row(
                children: [
                  const Icon(AppIcons.alertCircle, size: 14, color: Color(0xFFEF4444)),
                  const SizedBox(width: 8),
                  Text(state.error!, style: const TextStyle(fontSize: 12, color: Color(0xFFEF4444))),
                  const Spacer(),
                  TextButton(onPressed: controller.retry, child: const Text('Retry', style: TextStyle(fontSize: 11))),
                ],
              ),
            ),
          // Count header
          if (resp != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Row(
                children: [
                  Text(
                    '${resp.total} detection${resp.total == 1 ? '' : 's'}',
                    style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.5)),
                  ),
                  if (state.loading)
                    Padding(
                      padding: const EdgeInsets.only(left: 8),
                      child: SizedBox(
                        width: 12, height: 12,
                        child: CircularProgressIndicator(strokeWidth: 1.5, color: Colors.white.withOpacity(0.3)),
                      ),
                    ),
                ],
              ),
            ),
          // Table header
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(color: Colors.white.withOpacity(0.06)),
              ),
            ),
            child: Row(
              children: [
                _TableHeader('Plate', flex: 3),
                _TableHeader('Source', flex: 2),
                _TableHeader('Time', flex: 3),
                _TableHeader('Confidence', flex: 1),
              ],
            ),
          ),
          // Rows
          if (resp != null && resp.data.isEmpty)
            Expanded(
              child: Center(
                child: Text('No detections match the current filter.',
                    style: TextStyle(color: Colors.white.withOpacity(0.4))),
              ),
            )
          else if (resp != null)
            Expanded(
              child: ListView.builder(
                itemCount: resp.data.length,
                itemBuilder: (ctx, i) => _TableRow(detection: resp.data[i]),
              ),
            ),
          // Pagination
          if (resp != null && resp.total > state.limit)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                border: Border(top: BorderSide(color: Colors.white.withOpacity(0.06))),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _PaginationButton(
                    icon: AppIcons.chevronLeft,
                    onPressed: state.offset > 0 ? controller.prevPage : null,
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Text(
                      '${state.offset + 1}–${state.offset + resp.data.length} of ${resp.total}',
                      style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.5)),
                    ),
                  ),
                  _PaginationButton(
                    icon: AppIcons.chevronRight,
                    onPressed: (state.offset + state.limit) < resp.total ? controller.nextPage : null,
                  ),
                ],
              ),
            ),
        ],
      ),
    ).animate().fadeIn(duration: 400.ms, delay: 200.ms);
  }
}

class _TableHeader extends StatelessWidget {
  final String label;
  final int flex;
  const _TableHeader(this.label, {this.flex = 1});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      flex: flex,
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: Colors.white.withOpacity(0.4),
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

class _TableRow extends StatefulWidget {
  final DetectionModel detection;
  const _TableRow({required this.detection});

  @override
  State<_TableRow> createState() => _TableRowState();
}

class _TableRowState extends State<_TableRow> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final d = widget.detection;
    final plateLabel = d.platePersian?.isNotEmpty == true ? d.platePersian! : d.plateDtrb;

    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: _hovered ? Colors.white.withOpacity(0.02) : Colors.transparent,
          border: Border(
            bottom: BorderSide(color: Colors.white.withOpacity(0.03)),
          ),
        ),
        child: Row(
          children: [
            Expanded(
              flex: 3,
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(6),
                    decoration: BoxDecoration(
                      color: const Color(0xFF3B82F6).withOpacity(0.1),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Icon(AppIcons.creditCard, size: 14, color: Color(0xFF3B82F6)),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      plateLabel,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: Colors.white,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              flex: 2,
              child: _SourceBadge(type: d.sourceType),
            ),
            Expanded(
              flex: 3,
              child: Text(
                d.timestamp,
                style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.5)),
              ),
            ),
            Expanded(
              flex: 1,
              child: _ConfidenceBadge(value: d.confidence),
            ),
          ],
        ),
      ),
    );
  }
}

class _SourceBadge extends StatelessWidget {
  final String type;
  const _SourceBadge({required this.type});

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (type) {
      case 'image': color = const Color(0xFF8B5CF6); break;
      case 'video': color = const Color(0xFF06B6D4); break;
      case 'rtsp': color = const Color(0xFF10B981); break;
      default: color = const Color(0xFF6B7280);
    }
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: color.withOpacity(0.1),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            type,
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w500, color: color),
          ),
        ),
      ],
    );
  }
}

class _ConfidenceBadge extends StatelessWidget {
  final double value;
  const _ConfidenceBadge({required this.value});

  @override
  Widget build(BuildContext context) {
    final pct = value * 100;
    final color = pct >= 80 ? const Color(0xFF10B981) :
                  pct >= 60 ? const Color(0xFFF59E0B) : const Color(0xFFEF4444);
    return Text(
      '${pct.toStringAsFixed(1)}%',
      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color),
    );
  }
}

class _PaginationButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback? onPressed;
  const _PaginationButton({required this.icon, this.onPressed});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onPressed,
      child: Container(
        padding: const EdgeInsets.all(6),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.04),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: Colors.white.withOpacity(0.08)),
        ),
        child: Icon(
          icon, size: 16,
          color: onPressed != null ? Colors.white.withOpacity(0.6) : Colors.white.withOpacity(0.2),
        ),
      ),
    );
  }
}

String _errorMessage(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
