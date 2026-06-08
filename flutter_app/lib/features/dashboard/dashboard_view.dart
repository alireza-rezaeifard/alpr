// lib/features/dashboard/dashboard_view.dart
// Modern dashboard with glass-morphism cards, gradient accents, and clean layout.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../../shared/app_icons.dart';
import 'package:flutter_animate/flutter_animate.dart';
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
      backgroundColor: Colors.transparent,
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
          padding: const EdgeInsets.all(24),
          children: [
            // Header
            _Header(),
            const SizedBox(height: 24),
            // Stats cards
            _StatsSection(),
            const SizedBox(height: 24),
            // Charts grid
            _ChartsSection(),
            const SizedBox(height: 24),
            // Recent detections
            _RecentDetectionsSection(),
          ],
        ),
      ),
    );
  }
}

// ── Header ─────────────────────────────────────────────────────────────────

class _Header extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Dashboard',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'License plate recognition overview',
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

// ── Stats ──────────────────────────────────────────────────────────────────

class _StatsSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statsAsync = ref.watch(statsProvider);
    return statsAsync.when(
      loading: () => const _StatsLoading(),
      error: (e, _) => _ErrorBanner(
        message: 'Failed to load stats: ${_errorMessage(e)}',
        onRetry: () => ref.invalidate(statsProvider),
      ),
      data: (stats) => LayoutBuilder(
        builder: (context, constraints) {
          final crossAxisCount = constraints.maxWidth > 900 ? 4 : 2;
          return GridView.count(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            crossAxisCount: crossAxisCount,
            crossAxisSpacing: 16,
            mainAxisSpacing: 16,
            childAspectRatio: 2.2,
            children: [
              _StatCard(
                title: 'Total Detections',
                value: '${stats.totalDetections}',
                icon: AppIcons.search,
                gradient: const [Color(0xFF3B82F6), Color(0xFF1D4ED8)],
                change: '+${stats.detections7d} this week',
              ),
              _StatCard(
                title: 'Unique Plates',
                value: '${stats.uniquePlates}',
                icon: AppIcons.creditCard,
                gradient: const [Color(0xFF8B5CF6), Color(0xFF6D28D9)],
              ),
              _StatCard(
                title: 'Sessions',
                value: '${stats.totalSessions}',
                icon: AppIcons.layers,
                gradient: const [Color(0xFF06B6D4), Color(0xFF0891B2)],
                change: '+${stats.sessions7d} this week',
              ),
              _StatCard(
                title: 'Avg Confidence',
                value: stats.avgConfidence != null
                    ? '${(stats.avgConfidence! * 100).toStringAsFixed(1)}%'
                    : '—',
                icon: AppIcons.target,
                gradient: const [Color(0xFF10B981), Color(0xFF059669)],
              ),
            ],
          ).animate().fadeIn(duration: 500.ms, delay: 100.ms);
        },
      ),
    );
  }
}

class _StatsLoading extends StatelessWidget {
  const _StatsLoading();

  @override
  Widget build(BuildContext context) {
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 4,
      crossAxisSpacing: 16,
      mainAxisSpacing: 16,
      childAspectRatio: 2.2,
      children: List.generate(4, (_) => _ShimmerCard()),
    );
  }
}

class _ShimmerCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
    ).animate(onPlay: (c) => c.repeat())
        .shimmer(duration: 1500.ms, color: Colors.white.withOpacity(0.05));
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final List<Color> gradient;
  final String? change;

  const _StatCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.gradient,
    this.change,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    fontSize: 13,
                    color: Colors.white.withOpacity(0.5),
                    fontWeight: FontWeight.w400,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  gradient: LinearGradient(colors: gradient),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(icon, size: 16, color: Colors.white),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: const TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w700,
              color: Colors.white,
              letterSpacing: -1,
            ),
          ),
          if (change != null) ...[
            const SizedBox(height: 4),
            Text(
              change!,
              style: TextStyle(
                fontSize: 11,
                color: Colors.white.withOpacity(0.4),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// ── Charts ─────────────────────────────────────────────────────────────────

class _ChartsSection extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth > 900) {
          return Column(
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: 2, child: _TimelineChart()),
                  const SizedBox(width: 16),
                  Expanded(flex: 1, child: _SourcesChart()),
                ],
              ),
              const SizedBox(height: 16),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: _ConfidenceChart()),
                  const SizedBox(width: 16),
                  Expanded(child: _LettersChart()),
                ],
              ),
            ],
          );
        }
        return Column(
          children: [
            _TimelineChart(),
            const SizedBox(height: 16),
            _SourcesChart(),
            const SizedBox(height: 16),
            _ConfidenceChart(),
            const SizedBox(height: 16),
            _LettersChart(),
          ],
        );
      },
    ).animate().fadeIn(duration: 500.ms, delay: 200.ms);
  }
}

class _TimelineChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _ChartContainer(
      title: 'Detection Timeline',
      subtitle: 'Last 7 days',
      icon: AppIcons.trendingUp,
      asyncValue: ref.watch(timelineProvider),
      onRetry: () => ref.invalidate(timelineProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        return SizedBox(
          height: 200,
          child: BarChart(BarChartData(
            barGroups: data.asMap().entries.map((e) => BarChartGroupData(
              x: e.key,
              barRods: [BarChartRodData(
                toY: e.value.cnt.toDouble(),
                width: 16,
                borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
                gradient: const LinearGradient(
                  begin: Alignment.bottomCenter,
                  end: Alignment.topCenter,
                  colors: [Color(0xFF3B82F6), Color(0xFF8B5CF6)],
                ),
              )],
            )).toList(),
            gridData: FlGridData(
              show: true,
              drawVerticalLine: false,
              getDrawingHorizontalLine: (value) => FlLine(
                color: Colors.white.withOpacity(0.05),
                strokeWidth: 1,
              ),
            ),
            borderData: FlBorderData(show: false),
            titlesData: FlTitlesData(
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  getTitlesWidget: (value, _) {
                    final idx = value.toInt();
                    if (idx < 0 || idx >= data.length) return const SizedBox.shrink();
                    final label = data[idx].dt.length >= 10
                        ? data[idx].dt.substring(5)
                        : data[idx].dt;
                    return Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(label, style: TextStyle(
                        fontSize: 10, color: Colors.white.withOpacity(0.4),
                      )),
                    );
                  },
                ),
              ),
              leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            ),
          )),
        );
      },
    );
  }
}

class _SourcesChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _ChartContainer(
      title: 'Sources',
      subtitle: 'By type',
      icon: AppIcons.pieChart,
      asyncValue: ref.watch(sourcesProvider),
      onRetry: () => ref.invalidate(sourcesProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        final colors = [
          const Color(0xFF3B82F6),
          const Color(0xFF8B5CF6),
          const Color(0xFF10B981),
          const Color(0xFFF59E0B),
        ];
        return SizedBox(
          height: 200,
          child: Row(
            children: [
              Expanded(
                child: PieChart(PieChartData(
                  sectionsSpace: 2,
                  centerSpaceRadius: 40,
                  sections: data.asMap().entries.map((e) => PieChartSectionData(
                    value: e.value.cnt.toDouble(),
                    title: '',
                    color: colors[e.key % colors.length],
                    radius: 30,
                  )).toList(),
                )),
              ),
              const SizedBox(width: 16),
              Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: data.asMap().entries.map((e) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 10, height: 10,
                        decoration: BoxDecoration(
                          color: colors[e.key % colors.length],
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        '${e.value.sourceType} (${e.value.cnt})',
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.white.withOpacity(0.6),
                        ),
                      ),
                    ],
                  ),
                )).toList(),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _ConfidenceChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _ChartContainer(
      title: 'Confidence Distribution',
      subtitle: 'Score ranges',
      icon: AppIcons.gauge,
      asyncValue: ref.watch(confidenceProvider),
      onRetry: () => ref.invalidate(confidenceProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        return SizedBox(
          height: 160,
          child: BarChart(BarChartData(
            barGroups: data.asMap().entries.map((e) => BarChartGroupData(
              x: e.key,
              barRods: [BarChartRodData(
                toY: e.value.cnt.toDouble(),
                width: 14,
                borderRadius: const BorderRadius.vertical(top: Radius.circular(3)),
                color: const Color(0xFF10B981),
              )],
            )).toList(),
            gridData: FlGridData(show: false),
            borderData: FlBorderData(show: false),
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
    return _ChartContainer(
      title: 'Top Plates',
      subtitle: 'Most frequent',
      icon: AppIcons.trophy,
      asyncValue: ref.watch(lettersProvider),
      onRetry: () => ref.invalidate(lettersProvider),
      builder: (data) {
        if (data.isEmpty) return const _EmptyChart();
        final sorted = [...data]..sort((a, b) {
            final cmp = b.cnt.compareTo(a.cnt);
            return cmp != 0 ? cmp : a.platePersian.compareTo(b.platePersian);
          });
        final top = sorted.take(8).toList();
        return SizedBox(
          height: 160,
          child: BarChart(BarChartData(
            barGroups: top.asMap().entries.map((e) => BarChartGroupData(
              x: e.key,
              barRods: [BarChartRodData(
                toY: e.value.cnt.toDouble(),
                width: 12,
                borderRadius: const BorderRadius.vertical(top: Radius.circular(3)),
                color: const Color(0xFFF59E0B),
              )],
            )).toList(),
            gridData: FlGridData(show: false),
            borderData: FlBorderData(show: false),
            titlesData: const FlTitlesData(show: false),
          )),
        );
      },
    );
  }
}

// ── Chart container ────────────────────────────────────────────────────────

class _ChartContainer<T> extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final AsyncValue<T> asyncValue;
  final VoidCallback onRetry;
  final Widget Function(T data) builder;

  const _ChartContainer({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.asyncValue,
    required this.onRetry,
    required this.builder,
  });

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: const Color(0xFF111113),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white.withOpacity(0.06)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 16, color: Colors.white.withOpacity(0.4)),
                const SizedBox(width: 8),
                Text(title, style: const TextStyle(
                  fontSize: 14, fontWeight: FontWeight.w600, color: Colors.white,
                )),
                const Spacer(),
                Text(subtitle, style: TextStyle(
                  fontSize: 11, color: Colors.white.withOpacity(0.4),
                )),
              ],
            ),
            const SizedBox(height: 16),
            asyncValue.when(
              loading: () => SizedBox(
                height: 160,
                child: Center(
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white.withOpacity(0.3),
                  ),
                ),
              ),
              error: (e, _) => _ErrorBanner(
                message: _errorMessage(e),
                onRetry: onRetry,
              ),
              data: builder,
            ),
          ],
        ),
      );
}

class _EmptyChart extends StatelessWidget {
  const _EmptyChart();
  @override
  Widget build(BuildContext context) => SizedBox(
        height: 100,
        child: Center(
          child: Text('No data available',
              style: TextStyle(color: Colors.white.withOpacity(0.3))),
        ),
      );
}

// ── Recent detections ──────────────────────────────────────────────────────

class _RecentDetectionsSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncVal = ref.watch(recentDetectionsProvider);
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(AppIcons.clock, size: 16, color: Colors.white.withOpacity(0.4)),
              const SizedBox(width: 8),
              const Text('Recent Detections', style: TextStyle(
                fontSize: 14, fontWeight: FontWeight.w600, color: Colors.white,
              )),
            ],
          ),
          const SizedBox(height: 16),
          asyncVal.when(
            loading: () => const Center(
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            error: (e, _) => _ErrorBanner(
              message: 'Failed to load: ${_errorMessage(e)}',
              onRetry: () => ref.invalidate(recentDetectionsProvider),
            ),
            data: (resp) {
              if (resp.data.isEmpty) {
                return Padding(
                  padding: const EdgeInsets.all(24),
                  child: Center(
                    child: Text('No detections yet',
                        style: TextStyle(color: Colors.white.withOpacity(0.4))),
                  ),
                );
              }
              return Column(
                children: resp.data.map((d) => _DetectionRow(d)).toList(),
              );
            },
          ),
        ],
      ),
    ).animate().fadeIn(duration: 500.ms, delay: 300.ms);
  }
}

class _DetectionRow extends StatelessWidget {
  final DetectionModel detection;
  const _DetectionRow(this.detection);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
      margin: const EdgeInsets.only(bottom: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        color: Colors.white.withOpacity(0.02),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: const Color(0xFF3B82F6).withOpacity(0.1),
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Icon(AppIcons.creditCard, size: 16, color: Color(0xFF3B82F6)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  detection.platePersian ?? detection.plateDtrb,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w500,
                    fontSize: 13,
                  ),
                ),
                Text(
                  '${detection.sourceType} • ${detection.timestamp}',
                  style: TextStyle(
                    fontSize: 11,
                    color: Colors.white.withOpacity(0.4),
                  ),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: const Color(0xFF10B981).withOpacity(0.1),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              '${(detection.confidence * 100).toStringAsFixed(1)}%',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Color(0xFF10B981),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Error banner ───────────────────────────────────────────────────────────

class _ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorBanner({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFFEF4444).withOpacity(0.1),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.2)),
        ),
        child: Row(
          children: [
            const Icon(AppIcons.alertCircle, size: 16, color: Color(0xFFEF4444)),
            const SizedBox(width: 8),
            Expanded(child: Text(message, style: const TextStyle(
              fontSize: 12, color: Color(0xFFEF4444),
            ))),
            TextButton(
              onPressed: onRetry,
              child: const Text('Retry', style: TextStyle(fontSize: 12)),
            ),
          ],
        ),
      );
}

String _errorMessage(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
