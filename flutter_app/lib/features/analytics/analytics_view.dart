// lib/features/analytics/analytics_view.dart
// Analytics view with timeline, sources, confidence, and letter-frequency charts.
// Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../../data/models/chart_models.dart';
import '../../data/repositories/stats_repo.dart';
import '../../core/api_client.dart';

// ── Providers ──────────────────────────────────────────────────────────────

final _analyticsRepoProvider = Provider((_) => StatsRepo());

/// Currently selected day-range for the timeline. Default 7 days (Req 5.1).
final _selectedDaysProvider = StateProvider<int>((_) => 7);

/// Timeline data keyed by selected day count (Req 5.1, 5.2).
final analyticsTimelineProvider =
    FutureProvider.family<List<TimelineEntry>, int>((ref, days) =>
        ref.read(_analyticsRepoProvider).getTimeline(days: days));

/// Source distribution data (Req 5.1).
final analyticsSourcesProvider = FutureProvider<List<SourceEntry>>((ref) =>
    ref.read(_analyticsRepoProvider).getSources());

/// Confidence-bin data (Req 5.1).
final analyticsConfidenceProvider = FutureProvider<List<ConfidenceEntry>>(
    (ref) => ref.read(_analyticsRepoProvider).getConfidence());

/// Letter-frequency data (Req 5.1, 5.4).
final analyticsLettersProvider = FutureProvider<List<LetterEntry>>((ref) =>
    ref.read(_analyticsRepoProvider).getLetters());

// ── View ───────────────────────────────────────────────────────────────────

/// Top-level Analytics screen.
///
/// Loads four independent data sources (timeline, sources, confidence, letters).
/// Per-chart loading indicators, error indicators with retry, and empty-state
/// messages are shown in isolation so a failing chart does not block siblings
/// (Req 5.5, 5.6).
class AnalyticsView extends ConsumerWidget {
  const AnalyticsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedDays = ref.watch(_selectedDaysProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Analytics')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // ── Timeline with day selector (Req 5.1, 5.2) ──────────────────
          _TimelineSectionWidget(selectedDays: selectedDays),
          const SizedBox(height: 16),
          // ── Sources + Confidence side by side (Req 5.1) ─────────────────
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: _SourcesChartWidget()),
              const SizedBox(width: 12),
              Expanded(child: _ConfidenceChartWidget()),
            ],
          ),
          const SizedBox(height: 16),
          // ── Letter-frequency bar chart (Req 5.4) ─────────────────────────
          _LettersChartWidget(),
        ],
      ),
    );
  }
}

// ── Timeline section ───────────────────────────────────────────────────────

/// Detection timeline chart with 7/14/30/90-day selector.
///
/// Changing the selector only re-requests the timeline endpoint; the other
/// three charts are untouched (Req 5.2).
class _TimelineSectionWidget extends ConsumerWidget {
  final int selectedDays;
  const _TimelineSectionWidget({required this.selectedDays});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final timelineAsync = ref.watch(analyticsTimelineProvider(selectedDays));

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Detection Timeline',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                // ── Day-range selector (Req 5.2) ──────────────────────────
                DropdownButton<int>(
                  value: selectedDays,
                  items: const [
                    DropdownMenuItem(value: 7, child: Text('7 days')),
                    DropdownMenuItem(value: 14, child: Text('14 days')),
                    DropdownMenuItem(value: 30, child: Text('30 days')),
                    DropdownMenuItem(value: 90, child: Text('90 days')),
                  ],
                  onChanged: (v) {
                    if (v != null) {
                      ref.read(_selectedDaysProvider.notifier).state = v;
                    }
                  },
                ),
              ],
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 180,
              child: timelineAsync.when(
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => _ChartError(
                  msg: _errMsg(e),
                  onRetry: () =>
                      ref.invalidate(analyticsTimelineProvider(selectedDays)),
                ),
                data: (data) {
                  if (data.isEmpty) return const _EmptyState();
                  return BarChart(
                    BarChartData(
                      barGroups: data.asMap().entries.map((e) {
                        return BarChartGroupData(
                          x: e.key,
                          barRods: [
                            BarChartRodData(
                              toY: e.value.cnt.toDouble(),
                              width: 8,
                            ),
                          ],
                        );
                      }).toList(),
                      titlesData: FlTitlesData(
                        bottomTitles: AxisTitles(
                          sideTitles: SideTitles(
                            showTitles: true,
                            getTitlesWidget: (value, _) {
                              final idx = value.toInt();
                              if (idx < 0 || idx >= data.length) {
                                return const SizedBox.shrink();
                              }
                              // Show MM-DD portion when full ISO date is available
                              final label = data[idx].dt.length >= 10
                                  ? data[idx].dt.substring(5) // MM-DD
                                  : data[idx].dt;
                              return Text(
                                label,
                                style: const TextStyle(fontSize: 9),
                              );
                            },
                          ),
                        ),
                        leftTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false)),
                        topTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false)),
                        rightTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false)),
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Sources chart ──────────────────────────────────────────────────────────

/// Pie chart showing detection count per source type (image / video / rtsp).
class _SourcesChartWidget extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsSourcesProvider);
    return _ChartCard(
      title: 'Source Distribution',
      child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _ChartError(
          msg: _errMsg(e),
          onRetry: () => ref.invalidate(analyticsSourcesProvider),
        ),
        data: (data) {
          if (data.isEmpty) return const _EmptyState();
          const colors = [
            Colors.blue,
            Colors.orange,
            Colors.green,
            Colors.purple,
          ];
          return SizedBox(
            height: 160,
            child: PieChart(
              PieChartData(
                sections: data.asMap().entries.map((e) {
                  return PieChartSectionData(
                    value: e.value.cnt.toDouble(),
                    title: '${e.value.sourceType}\n${e.value.cnt}',
                    color: colors[e.key % colors.length],
                    radius: 60,
                    titleStyle: const TextStyle(
                      fontSize: 10,
                      color: Colors.white,
                    ),
                  );
                }).toList(),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ── Confidence chart ───────────────────────────────────────────────────────

/// Bar chart of confidence-score distribution in bucketed bins.
class _ConfidenceChartWidget extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsConfidenceProvider);
    return _ChartCard(
      title: 'Confidence Bins',
      child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _ChartError(
          msg: _errMsg(e),
          onRetry: () => ref.invalidate(analyticsConfidenceProvider),
        ),
        data: (data) {
          if (data.isEmpty) return const _EmptyState();
          return SizedBox(
            height: 160,
            child: BarChart(
              BarChartData(
                barGroups: data.asMap().entries.map((e) {
                  return BarChartGroupData(
                    x: e.key,
                    barRods: [
                      BarChartRodData(
                        toY: e.value.cnt.toDouble(),
                        width: 6,
                        color: Colors.teal,
                      ),
                    ],
                  );
                }).toList(),
                titlesData: const FlTitlesData(show: false),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ── Letters chart ──────────────────────────────────────────────────────────

/// Horizontal bar chart of top-15 most-frequently detected plates.
///
/// Entries are sorted by descending count; ties are broken by ascending
/// `plate_persian` value (Req 5.4).
class _LettersChartWidget extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsLettersProvider);
    return _ChartCard(
      title: 'Top Plates (by frequency)',
      child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _ChartError(
          msg: _errMsg(e),
          onRetry: () => ref.invalidate(analyticsLettersProvider),
        ),
        data: (data) {
          if (data.isEmpty) return const _EmptyState();

          // Sort: descending count, ties broken by ascending letter (Req 5.4)
          final sorted = [...data]..sort((a, b) {
              final cmp = b.cnt.compareTo(a.cnt);
              return cmp != 0 ? cmp : a.platePersian.compareTo(b.platePersian);
            });
          final top = sorted.take(15).toList();

          return SizedBox(
            height: 200,
            child: BarChart(
              BarChartData(
                barGroups: top.asMap().entries.map((e) {
                  return BarChartGroupData(
                    x: e.key,
                    barRods: [
                      BarChartRodData(
                        toY: e.value.cnt.toDouble(),
                        width: 14,
                        color: Colors.indigo,
                      ),
                    ],
                  );
                }).toList(),
                titlesData: FlTitlesData(
                  bottomTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      getTitlesWidget: (value, _) {
                        final idx = value.toInt();
                        if (idx < 0 || idx >= top.length) {
                          return const SizedBox.shrink();
                        }
                        return Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            top[idx].platePersian,
                            style: const TextStyle(fontSize: 9),
                            textDirection: TextDirection.rtl,
                          ),
                        );
                      },
                    ),
                  ),
                  leftTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false)),
                  topTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false)),
                  rightTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false)),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ── Shared widgets ─────────────────────────────────────────────────────────

/// Card wrapper with a title above the chart content.
class _ChartCard extends StatelessWidget {
  final String title;
  final Widget child;
  const _ChartCard({required this.title, required this.child});

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title,
                  style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              child,
            ],
          ),
        ),
      );
}

/// Per-chart error indicator with a retry button (Req 5.6).
class _ChartError extends StatelessWidget {
  final String msg;
  final VoidCallback onRetry;
  const _ChartError({required this.msg, required this.onRetry});

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 80,
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(msg, style: const TextStyle(fontSize: 12)),
              TextButton(onPressed: onRetry, child: const Text('Retry')),
            ],
          ),
        ),
      );
}

/// Per-chart empty-state message shown when the endpoint returns an empty list (Req 5.5).
class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 80,
        child: Center(child: Text('No data available')),
      );
}

/// Extracts a human-readable message from an error object.
String _errMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
