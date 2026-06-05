// lib/features/history/history_view.dart
// Searchable, filterable detection history view.
// Requirements: 4.1–4.7

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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

  /// Filter by source type; resets offset to 0 per Req 4.2.
  void setSourceType(String type) {
    state = state.copyWith(sourceType: type, offset: 0);
    _fetch();
  }

  /// Debounced 300 ms search; resets offset to 0 per Req 4.3.
  void setSearch(String query) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      state = state.copyWith(search: query, offset: 0);
      _fetch();
    });
  }

  /// Next page: increment offset by limit per Req 4.5.
  void nextPage() {
    state = state.copyWith(offset: state.offset + state.limit);
    _fetch();
  }

  /// Prev page: decrement offset, clamped to 0 per Req 4.5.
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

/// History view — shows all detections with filter, search, and pagination.
/// Requirements: 4.1–4.7
class HistoryView extends ConsumerWidget {
  const HistoryView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Detection History')),
      body: Column(
        children: [
          _FilterBar(),
          Expanded(child: _HistoryList()),
        ],
      ),
    );
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
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Row(
        children: [
          // Source-type filter (Req 4.2)
          DropdownButton<String>(
            value: sourceType,
            items: const [
              DropdownMenuItem(value: 'all', child: Text('All')),
              DropdownMenuItem(value: 'image', child: Text('Image')),
              DropdownMenuItem(value: 'video', child: Text('Video')),
              DropdownMenuItem(value: 'rtsp', child: Text('RTSP')),
            ],
            onChanged: (v) => controller.setSourceType(v ?? 'all'),
          ),
          const SizedBox(width: 12),
          // Search field — debounced 300 ms (Req 4.3)
          Expanded(
            child: TextField(
              controller: _searchCtrl,
              decoration: const InputDecoration(
                hintText: 'Search plates…',
                prefixIcon: Icon(Icons.search),
                isDense: true,
              ),
              onChanged: controller.setSearch,
            ),
          ),
        ],
      ),
    );
  }
}

// ── History list ───────────────────────────────────────────────────────────

class _HistoryList extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(_historyControllerProvider);
    final controller = ref.read(_historyControllerProvider.notifier);

    // Initial load (no prior data yet)
    if (state.loading && state.data == null) {
      return const Center(child: CircularProgressIndicator());
    }

    // Hard error — no previous results to retain
    if (state.error != null && state.data == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 8),
            Text('Could not load history: ${state.error}'),
            const SizedBox(height: 8),
            ElevatedButton(
              onPressed: controller.retry,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    final resp = state.data;

    return Column(
      children: [
        // Error banner — retains previous results (Req 4.6)
        if (state.error != null)
          MaterialBanner(
            content: Text('Load error: ${state.error}'),
            actions: [
              TextButton(
                onPressed: controller.retry,
                child: const Text('Retry'),
              ),
            ],
          ),
        // Total record count (Req 4.4)
        if (resp != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                '${resp.total} detection${resp.total == 1 ? '' : 's'}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ),
        // Empty-state (Req 4.7)
        if (resp != null && resp.data.isEmpty)
          const Expanded(
            child: Center(
              child: Text(
                'No detections match the current filter.',
                style: TextStyle(color: Colors.grey),
              ),
            ),
          )
        else if (resp != null)
          Expanded(
            child: ListView.builder(
              itemCount: resp.data.length,
              itemBuilder: (ctx, i) => _DetectionRow(detection: resp.data[i]),
            ),
          ),
        // Pagination controls — visible only when total > limit (Req 4.5)
        if (resp != null && resp.total > state.limit)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(
                  icon: const Icon(Icons.chevron_left),
                  tooltip: 'Previous page',
                  onPressed: state.offset > 0 ? controller.prevPage : null,
                ),
                Text(
                  '${state.offset + 1}–${state.offset + resp.data.length}'
                  ' of ${resp.total}',
                ),
                IconButton(
                  icon: const Icon(Icons.chevron_right),
                  tooltip: 'Next page',
                  onPressed: (state.offset + state.limit) < resp.total
                      ? controller.nextPage
                      : null,
                ),
              ],
            ),
          ),
      ],
    );
  }
}

// ── Detection row ──────────────────────────────────────────────────────────

class _DetectionRow extends StatelessWidget {
  final DetectionModel detection;
  const _DetectionRow({required this.detection});

  @override
  Widget build(BuildContext context) {
    // Show Persian plate when available, fallback to DTRB (Req 4.1)
    final plateLabel = detection.platePersian?.isNotEmpty == true
        ? detection.platePersian!
        : detection.plateDtrb;

    final sourceFile = detection.sourceFile;

    return ListTile(
      leading: const Icon(Icons.credit_card),
      title: Text(plateLabel),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${detection.sourceType} • ${detection.timestamp}'),
          if (sourceFile != null && sourceFile.isNotEmpty)
            Text(
              sourceFile,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: Colors.grey),
            ),
        ],
      ),
      isThreeLine: sourceFile != null && sourceFile.isNotEmpty,
      trailing: Text(
        '${(detection.confidence * 100).toStringAsFixed(1)}%',
        style: const TextStyle(fontWeight: FontWeight.bold),
      ),
    );
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────

String _errorMessage(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
