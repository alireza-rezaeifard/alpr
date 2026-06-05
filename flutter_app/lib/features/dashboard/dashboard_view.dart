// lib/features/dashboard/dashboard_view.dart
// Dashboard view showing stats summary, charts, and recent detections.
// Requirements: 3.1–3.9

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../../data/models/stats_model.dart';
import '../../data/models/detection_model.dart';
import '../../data/models/chart_models.dart';
import '../../data/repositories/stats_repo.dart';
import '../../data/repositories/detections_repo.dart';
import '../../core/api_client.dart';

// ── Providers ──────────────────────────────────────────────────────────────

final _statsRepoProvider = Provider((_) => StatsRepo());
final _detectionsRepoProvider = Provider((_) => DetectionsRepo());

final statsProvider = FutureProvider<StatsModel>((ref) =>
    ref.read(_statsRepoProvider).getStats());

final timelineProvider = FutureProvider<List<TimelineEntry>>((ref) =>
    ref.read(_statsRepoProvider).getTimeline(days: 7));

final sourcesProvider = FutureProvider<List<SourceEntry>>((ref) =>
    ref.read(_statsRepoProvider).getSources());

final confidenceProvider = FutureProvider<List<ConfidenceEntry>>((ref) =>
    ref.read(_statsRepoProvider).getConfidence());

final lettersProvider = FutureProvider<List<LetterEntry>>((ref) =>
    ref.read(_statsRepoProvider).getLetters());

final recentDetectionsProvider = FutureProvider<DetectionsResponse>((ref) =>
    ref.read(_detectionsRepoProvider).getDetections(limit: 10, offset: 0));

// ── Dashboard view ─────────────────────────────────────────────────────────

class DashboardView extends ConsumerWidget {
  const DashboardView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Dashboard')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(statsProvider);
          ref.invalidate(timelineProvider);
          ref.invalidate(sourcesProvider);
          ref.invalidate(confidenceProvider);
          ref.invalidate(lettersProvider);
          ref.invalidate(recentDetectionsProvider);
        },
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _StatsSection(),
            const SizedBox(height: 16),
            _ChartsSection(),
            const SizedBox(height: 16),
            _RecentDetectionsSection(),
          ],
        ),
      ),
    );
  }
}

// ── Stats summary ──────────────────────────────────────────────────────────

class _StatsSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statsAsync = ref.watch(statsProvider);
    return statsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _ErrorCard(
        message: 'Failed to load stats: ${_errorMessage(e)}',
        onRetry: () => ref.invalidate(statsProvider),
      ),
      data: (stats) => Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          _StatCard('Total Detections', '${stats.totalDetections}', Icons.search),
          _StatCard('Unique Plates', '${stats.uniquePlates}', Icons.credit_card),
          _StatCard('Sessions', '${stats.totalSessions}', Icons.folder),
          _StatCard(
            'Avg Confidence',
            stats.avgConfidence != null
                ? '${(stats.avgConfidence! * 100).toStringAsFixed(1)}%'
                : '—',
            Icons.analytics,
          ),
        ],
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  const _StatCard(this.title, this.value, this.icon);

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 160,
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, color: Theme.of(context).colorScheme.primary),
                const SizedBox(height: 8),
                Text(value,
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        )),
                Text(title, style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ),
        ),
      );
}

// ── Charts ─────────────────────────────────────────────────────────────────

class _ChartsSection extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Analytics', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: _TimelineChart()),
            const SizedBox(width: 12),
            Expanded(child: _SourcesChart()),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: _ConfidenceChart()),
            const SizedBox(width: 12),
            Expanded(child: _LettersChart()),
          ],
        ),
      ],
    );
  }
}

class _TimelineChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _ChartCard(
      title: 'Detection Timeline',
      asyncValue: ref.watch(timelineProvider),
      onRetry: () => ref.invalidate(timelineProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        return SizedBox(
          height: 160,
          child: BarChart(BarChartData(
            barGroups: data.asMap().entries.map((e) => BarChartGroupData(
              x: e.key,
              barRods: [BarChartRodData(toY: e.value.cnt.toDouble(), width: 8)],
            )).toList(),
            titlesData: const FlTitlesData(show: false),
          )),
        );
      },
    );
  }
}

class _SourcesChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _ChartCard(
      title: 'Source Types',
      asyncValue: ref.watch(sourcesProvider),
      onRetry: () => ref.invalidate(sourcesProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        final colors = [Colors.blue, Colors.orange, Colors.green];
        return SizedBox(
          height: 160,
          child: PieChart(PieChartData(
            sections: data.asMap().entries.map((e) => PieChartSectionData(
              value: e.value.cnt.toDouble(),
              title: e.value.sourceType,
              color: colors[e.key % colors.length],
              radius: 60,
            )).toList(),
          )),
        );
      },
    );
  }
}

class _ConfidenceChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _ChartCard(
      title: 'Confidence Distribution',
      asyncValue: ref.watch(confidenceProvider),
      onRetry: () => ref.invalidate(confidenceProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        return SizedBox(
          height: 160,
          child: BarChart(BarChartData(
            barGroups: data.asMap().entries.map((e) => BarChartGroupData(
              x: e.key,
              barRods: [BarChartRodData(toY: e.value.cnt.toDouble(), width: 6)],
            )).toList(),
            titlesData: const FlTitlesData(show: false),
          )),
        );
      },
    );
  }
}

class _LettersChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _ChartCard(
      title: 'Top Plates',
      asyncValue: ref.watch(lettersProvider),
      onRetry: () => ref.invalidate(lettersProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        final sorted = [...data]..sort((a, b) {
            final cmp = b.cnt.compareTo(a.cnt);
            return cmp != 0 ? cmp : a.platePersian.compareTo(b.platePersian);
          });
        return SizedBox(
          height: 160,
          child: BarChart(BarChartData(
            barGroups: sorted.take(10).toList().asMap().entries.map((e) =>
              BarChartGroupData(
                x: e.key,
                barRods: [BarChartRodData(toY: e.value.cnt.toDouble(), width: 10)],
              )).toList(),
            titlesData: const FlTitlesData(show: false),
          )),
        );
      },
    );
  }
}

class _ChartCard<T> extends StatelessWidget {
  final String title;
  final AsyncValue<T> asyncValue;
  final VoidCallback onRetry;
  final Widget Function(T data) builder;

  const _ChartCard({
    required this.title,
    required this.asyncValue,
    required this.onRetry,
    required this.builder,
  });

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              asyncValue.when(
                loading: () => const SizedBox(
                  height: 160,
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => SizedBox(
                  height: 80,
                  child: _ErrorCard(
                    message: _errorMessage(e),
                    onRetry: onRetry,
                  ),
                ),
                data: builder,
              ),
            ],
          ),
        ),
      );
}

class _EmptyChart extends StatelessWidget {
  const _EmptyChart();
  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 80,
        child: Center(child: Text('No data available')),
      );
}

// ── Recent detections ──────────────────────────────────────────────────────

class _RecentDetectionsSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncVal = ref.watch(recentDetectionsProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Recent Detections', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        asyncVal.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => _ErrorCard(
            message: 'Failed to load recent detections: ${_errorMessage(e)}',
            onRetry: () => ref.invalidate(recentDetectionsProvider),
          ),
          data: (resp) {
            if (resp.data.isEmpty) {
              return const Padding(
                padding: EdgeInsets.all(16),
                child: Text('No detections yet'),
              );
            }
            return Column(
              children: resp.data.map((d) => _DetectionTile(d)).toList(),
            );
          },
        ),
      ],
    );
  }
}

class _DetectionTile extends StatelessWidget {
  final DetectionModel detection;
  const _DetectionTile(this.detection);

  @override
  Widget build(BuildContext context) => ListTile(
        leading: const Icon(Icons.credit_card),
        title: Text(detection.platePersian ?? detection.plateDtrb),
        subtitle: Text(detection.timestamp),
        trailing: Text(
          '${(detection.confidence * 100).toStringAsFixed(1)}%',
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
      );
}

// ── Shared helpers ─────────────────────────────────────────────────────────

class _ErrorCard extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorCard({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) => Card(
        color: Theme.of(context).colorScheme.errorContainer,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              const Icon(Icons.error_outline),
              const SizedBox(width: 8),
              Expanded(child: Text(message, style: const TextStyle(fontSize: 12))),
              TextButton(onPressed: onRetry, child: const Text('Retry')),
            ],
          ),
        ),
      );
}

String _errorMessage(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
