// lib/features/analytics/analytics_view.dart
// Modern analytics view with gradient charts and clean layout.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../../shared/app_icons.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../../data/models/chart_models.dart';
import '../../data/repositories/stats_repo.dart';
import '../../core/api_client.dart';

// ── Providers ──────────────────────────────────────────────────────────────

final _analyticsRepoProvider = Provider((_) => StatsRepo());
final _selectedDaysProvider = StateProvider<int>((_) => 7);

final analyticsTimelineProvider =
    FutureProvider.family<List<TimelineEntry>, int>((ref, days) =>
        ref.read(_analyticsRepoProvider).getTimeline(days: days));

final analyticsSourcesProvider = FutureProvider<List<SourceEntry>>((ref) =>
    ref.read(_analyticsRepoProvider).getSources());

final analyticsConfidenceProvider = FutureProvider<List<ConfidenceEntry>>(
    (ref) => ref.read(_analyticsRepoProvider).getConfidence());

final analyticsLettersProvider = FutureProvider<List<LetterEntry>>((ref) =>
    ref.read(_analyticsRepoProvider).getLetters());

// ── View ───────────────────────────────────────────────────────────────────

class AnalyticsView extends ConsumerWidget {
  const AnalyticsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedDays = ref.watch(_selectedDaysProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          // Header
          _buildHeader(context, ref, selectedDays),
          const SizedBox(height: 24),
          // Timeline (main chart)
          _TimelineSection(selectedDays: selectedDays),
          const SizedBox(height: 20),
          // Sources + Confidence
          LayoutBuilder(
            builder: (context, constraints) {
              if (constraints.maxWidth > 800) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: _SourcesSection()),
                    const SizedBox(width: 16),
                    Expanded(child: _ConfidenceSection()),
                  ],
                );
              }
              return Column(
                children: [
                  _SourcesSection(),
                  const SizedBox(height: 16),
                  _ConfidenceSection(),
                ],
              );
            },
          ),
          const SizedBox(height: 20),
          // Top plates
          _LettersSection(),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context, WidgetRef ref, int selectedDays) {
    return Row(
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Analytics',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Detection patterns and insights',
              style: TextStyle(fontSize: 14, color: Colors.white.withOpacity(0.5)),
            ),
          ],
        ),
        const Spacer(),
        // Day range selector
        Container(
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.04),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.white.withOpacity(0.08)),
          ),
          child: Row(
            children: [7, 14, 30, 90].map((days) {
              final isSelected = days == selectedDays;
              return GestureDetector(
                onTap: () => ref.read(_selectedDaysProvider.notifier).state = days,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: isSelected ? const Color(0xFF3B82F6).withOpacity(0.15) : Colors.transparent,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '${days}d',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w500,
                      color: isSelected ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.5),
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
        ),
      ],
    ).animate().fadeIn(duration: 400.ms);
  }
}

// ── Timeline ───────────────────────────────────────────────────────────────

class _TimelineSection extends ConsumerWidget {
  final int selectedDays;
  const _TimelineSection({required this.selectedDays});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final timelineAsync = ref.watch(analyticsTimelineProvider(selectedDays));

    return _ChartCard(
      title: 'Detection Timeline',
      subtitle: 'Last $selectedDays days',
      icon: AppIcons.trendingUp,
      child: timelineAsync.when(
        loading: () => const _ChartLoading(),
        error: (e, _) => _ChartError(
          msg: _errMsg(e),
          onRetry: () => ref.invalidate(analyticsTimelineProvider(selectedDays)),
        ),
        data: (data) {
          if (data.isEmpty) return const _EmptyState();
          return SizedBox(
            height: 240,
            child: LineChart(LineChartData(
              lineBarsData: [
                LineChartBarData(
                  spots: data.asMap().entries.map((e) =>
                      FlSpot(e.key.toDouble(), e.value.cnt.toDouble())).toList(),
                  isCurved: true,
                  curveSmoothness: 0.3,
                  gradient: const LinearGradient(
                    colors: [Color(0xFF3B82F6), Color(0xFF8B5CF6)],
                  ),
                  barWidth: 2.5,
                  dotData: FlDotData(
                    show: true,
                    getDotPainter: (spot, _, __, ___) => FlDotCirclePainter(
                      radius: 3,
                      color: const Color(0xFF3B82F6),
                      strokeWidth: 1.5,
                      strokeColor: Colors.white,
                    ),
                  ),
                  belowBarData: BarAreaData(
                    show: true,
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        const Color(0xFF3B82F6).withOpacity(0.15),
                        const Color(0xFF3B82F6).withOpacity(0.0),
                      ],
                    ),
                  ),
                ),
              ],
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                getDrawingHorizontalLine: (value) => FlLine(
                  color: Colors.white.withOpacity(0.04),
                  strokeWidth: 1,
                ),
              ),
              borderData: FlBorderData(show: false),
              titlesData: FlTitlesData(
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    interval: data.length > 14 ? 3 : 1,
                    getTitlesWidget: (value, _) {
                      final idx = value.toInt();
                      if (idx < 0 || idx >= data.length) return const SizedBox.shrink();
                      final label = data[idx].dt.length >= 10
                          ? data[idx].dt.substring(5)
                          : data[idx].dt;
                      return Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(label, style: TextStyle(
                          fontSize: 10, color: Colors.white.withOpacity(0.35),
                        )),
                      );
                    },
                  ),
                ),
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 40,
                    getTitlesWidget: (value, _) => Text(
                      value.toInt().toString(),
                      style: TextStyle(fontSize: 10, color: Colors.white.withOpacity(0.35)),
                    ),
                  ),
                ),
                topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              ),
            )),
          );
        },
      ),
    ).animate().fadeIn(duration: 500.ms, delay: 100.ms);
  }
}

// ── Sources ────────────────────────────────────────────────────────────────

class _SourcesSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsSourcesProvider);
    return _ChartCard(
      title: 'Source Distribution',
      subtitle: 'By type',
      icon: AppIcons.pieChart,
      child: async.when(
        loading: () => const _ChartLoading(),
        error: (e, _) => _ChartError(
          msg: _errMsg(e),
          onRetry: () => ref.invalidate(analyticsSourcesProvider),
        ),
        data: (data) {
          if (data.isEmpty) return const _EmptyState();
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
                    sectionsSpace: 3,
                    centerSpaceRadius: 35,
                    sections: data.asMap().entries.map((e) => PieChartSectionData(
                      value: e.value.cnt.toDouble(),
                      title: '',
                      color: colors[e.key % colors.length],
                      radius: 35,
                    )).toList(),
                  )),
                ),
                Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: data.asMap().entries.map((e) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Container(width: 10, height: 10, decoration: BoxDecoration(
                          color: colors[e.key % colors.length],
                          borderRadius: BorderRadius.circular(2),
                        )),
                        const SizedBox(width: 8),
                        Text(
                          '${e.value.sourceType} (${e.value.cnt})',
                          style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.6)),
                        ),
                      ],
                    ),
                  )).toList(),
                ),
              ],
            ),
          );
        },
      ),
    ).animate().fadeIn(duration: 500.ms, delay: 200.ms);
  }
}

// ── Confidence ─────────────────────────────────────────────────────────────

class _ConfidenceSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsConfidenceProvider);
    return _ChartCard(
      title: 'Confidence Distribution',
      subtitle: 'Score bins',
      icon: AppIcons.gauge,
      child: async.when(
        loading: () => const _ChartLoading(),
        error: (e, _) => _ChartError(
          msg: _errMsg(e),
          onRetry: () => ref.invalidate(analyticsConfidenceProvider),
        ),
        data: (data) {
          if (data.isEmpty) return const _EmptyState();
          return SizedBox(
            height: 200,
            child: BarChart(BarChartData(
              barGroups: data.asMap().entries.map((e) => BarChartGroupData(
                x: e.key,
                barRods: [BarChartRodData(
                  toY: e.value.cnt.toDouble(),
                  width: 18,
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
                  gradient: const LinearGradient(
                    begin: Alignment.bottomCenter,
                    end: Alignment.topCenter,
                    colors: [Color(0xFF10B981), Color(0xFF06B6D4)],
                  ),
                )],
              )).toList(),
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                getDrawingHorizontalLine: (value) => FlLine(
                  color: Colors.white.withOpacity(0.04), strokeWidth: 1),
              ),
              borderData: FlBorderData(show: false),
              titlesData: const FlTitlesData(show: false),
            )),
          );
        },
      ),
    ).animate().fadeIn(duration: 500.ms, delay: 250.ms);
  }
}

// ── Letters ────────────────────────────────────────────────────────────────

class _LettersSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsLettersProvider);
    return _ChartCard(
      title: 'Top Plates',
      subtitle: 'By frequency',
      icon: AppIcons.trophy,
      child: async.when(
        loading: () => const _ChartLoading(),
        error: (e, _) => _ChartError(
          msg: _errMsg(e),
          onRetry: () => ref.invalidate(analyticsLettersProvider),
        ),
        data: (data) {
          if (data.isEmpty) return const _EmptyState();
          final sorted = [...data]..sort((a, b) {
              final cmp = b.cnt.compareTo(a.cnt);
              return cmp != 0 ? cmp : a.platePersian.compareTo(b.platePersian);
            });
          final top = sorted.take(12).toList();
          return SizedBox(
            height: 220,
            child: BarChart(BarChartData(
              barGroups: top.asMap().entries.map((e) => BarChartGroupData(
                x: e.key,
                barRods: [BarChartRodData(
                  toY: e.value.cnt.toDouble(),
                  width: 16,
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
                  gradient: const LinearGradient(
                    begin: Alignment.bottomCenter,
                    end: Alignment.topCenter,
                    colors: [Color(0xFFF59E0B), Color(0xFFF97316)],
                  ),
                )],
              )).toList(),
              gridData: FlGridData(show: false),
              borderData: FlBorderData(show: false),
              titlesData: FlTitlesData(
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    getTitlesWidget: (value, _) {
                      final idx = value.toInt();
                      if (idx < 0 || idx >= top.length) return const SizedBox.shrink();
                      return Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(
                          top[idx].platePersian,
                          style: TextStyle(fontSize: 9, color: Colors.white.withOpacity(0.4)),
                          textDirection: TextDirection.rtl,
                        ),
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
      ),
    ).animate().fadeIn(duration: 500.ms, delay: 300.ms);
  }
}

// ── Shared chart widgets ───────────────────────────────────────────────────

class _ChartCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final Widget child;
  const _ChartCard({required this.title, required this.subtitle, required this.icon, required this.child});

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
            Row(children: [
              Icon(icon, size: 16, color: Colors.white.withOpacity(0.4)),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Colors.white)),
              const Spacer(),
              Text(subtitle, style: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.4))),
            ]),
            const SizedBox(height: 16),
            child,
          ],
        ),
      );
}

class _ChartLoading extends StatelessWidget {
  const _ChartLoading();
  @override
  Widget build(BuildContext context) => const SizedBox(
    height: 160, child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
  );
}

class _ChartError extends StatelessWidget {
  final String msg;
  final VoidCallback onRetry;
  const _ChartError({required this.msg, required this.onRetry});
  @override
  Widget build(BuildContext context) => SizedBox(
    height: 80,
    child: Center(child: Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(msg, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.4))),
        TextButton(onPressed: onRetry, child: const Text('Retry', style: TextStyle(fontSize: 12))),
      ],
    )),
  );
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();
  @override
  Widget build(BuildContext context) => SizedBox(
    height: 100,
    child: Center(child: Text('No data available', style: TextStyle(color: Colors.white.withOpacity(0.3)))),
  );
}

String _errMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
