// lib/features/analytics/analytics_view.dart
// Analytics screen built entirely with Syncfusion charts (Requirement 17.6):
// timeline (spline area), source distribution (doughnut), confidence bins
// (column), and top plates (bar). Includes a day-range selector.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:syncfusion_flutter_charts/charts.dart';

import '../../core/api_client.dart';
import '../../core/persian_format.dart';
import '../../data/models/chart_models.dart';
import '../../data/repositories/stats_repo.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/chart_card.dart';
import '../../shared/widgets/screen_shell.dart';

final _analyticsRepoProvider = Provider((_) => StatsRepo());
final _selectedDaysProvider = StateProvider<int>((_) => 7);

final analyticsTimelineProvider = FutureProvider.family<List<TimelineEntry>, int>(
    (ref, days) => ref.read(_analyticsRepoProvider).getTimeline(days: days));
final analyticsSourcesProvider = FutureProvider<List<SourceEntry>>((ref) => ref.read(_analyticsRepoProvider).getSources());
final analyticsConfidenceProvider = FutureProvider<List<ConfidenceEntry>>((ref) => ref.read(_analyticsRepoProvider).getConfidence());
final analyticsLettersProvider = FutureProvider<List<LetterEntry>>((ref) => ref.read(_analyticsRepoProvider).getLetters());

const _accentBlue = Color(0xFF3B82F6);

class AnalyticsView extends ConsumerWidget {
  const AnalyticsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedDays = ref.watch(_selectedDaysProvider);

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        ScreenHeader(
          title: 'تحلیل‌ها',
          subtitle: 'الگوها و بینش‌های تشخیص',
          actions: [_DayRangeSelector(selected: selectedDays)],
        ),
        const SizedBox(height: 24),
        _TimelineSection(days: selectedDays),
        const SizedBox(height: 16),
        LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth > 800;
            final sources = _SourcesSection();
            final confidence = _ConfidenceSection();
            if (wide) {
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: sources),
                  const SizedBox(width: 16),
                  Expanded(child: confidence),
                ],
              );
            }
            return Column(children: [sources, const SizedBox(height: 16), confidence]);
          },
        ),
        const SizedBox(height: 16),
        _LettersSection(),
      ],
    );
  }
}

class _DayRangeSelector extends ConsumerWidget {
  final int selected;
  const _DayRangeSelector({required this.selected});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [7, 14, 30, 90].map((days) {
          final isSelected = days == selected;
          return MouseRegion(
            cursor: SystemMouseCursors.click,
            child: GestureDetector(
              onTap: () => ref.read(_selectedDaysProvider.notifier).state = days,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: isSelected ? _accentBlue.withValues(alpha: 0.15) : Colors.transparent,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '${PersianFormat.number(days)} روز',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                    color: isSelected ? _accentBlue : Colors.white.withValues(alpha: 0.5),
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _TimelineSection extends ConsumerWidget {
  final int days;
  const _TimelineSection({required this.days});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsTimelineProvider(days));
    return ChartCard(
      title: 'روند تشخیص',
      subtitle: '${PersianFormat.number(days)} روز اخیر',
      icon: AppIcons.trendingUp,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errMsg(e), onRetry: () => ref.invalidate(analyticsTimelineProvider(days))),
        data: (data) {
          if (data.isEmpty) return const ChartEmpty();
          return SizedBox(
            height: 260,
            child: SfCartesianChart(
              plotAreaBorderWidth: 0,
              primaryXAxis: CategoryAxis(
                interval: data.length > 14 ? 3 : null,
                majorGridLines: const MajorGridLines(width: 0),
                axisLine: AxisLine(color: Colors.white.withValues(alpha: 0.1)),
                labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 10, fontFamily: 'Vazirmatn'),
              ),
              primaryYAxis: NumericAxis(
                majorGridLines: MajorGridLines(width: 0.5, color: Colors.white.withValues(alpha: 0.06)),
                axisLine: const AxisLine(width: 0),
                labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 10, fontFamily: 'Vazirmatn'),
              ),
              series: <CartesianSeries<TimelineEntry, String>>[
                SplineAreaSeries<TimelineEntry, String>(
                  dataSource: data,
                  xValueMapper: (e, _) => e.dt.length >= 10 ? e.dt.substring(5) : e.dt,
                  yValueMapper: (e, _) => e.cnt,
                  borderWidth: 2.5,
                  borderColor: _accentBlue,
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [_accentBlue.withValues(alpha: 0.3), _accentBlue.withValues(alpha: 0.02)],
                  ),
                  markerSettings: const MarkerSettings(isVisible: true, height: 5, width: 5, borderColor: _accentBlue, color: Colors.white),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _SourcesSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsSourcesProvider);
    return ChartCard(
      title: 'توزیع منابع',
      subtitle: 'بر اساس نوع',
      icon: AppIcons.pieChart,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errMsg(e), onRetry: () => ref.invalidate(analyticsSourcesProvider)),
        data: (data) {
          if (data.isEmpty) return const ChartEmpty();
          const palette = [Color(0xFF3B82F6), Color(0xFF8B5CF6), Color(0xFF10B981), Color(0xFFF59E0B)];
          return SizedBox(
            height: 240,
            child: SfCircularChart(
              legend: Legend(
                isVisible: true,
                position: LegendPosition.bottom,
                textStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontFamily: 'Vazirmatn', fontSize: 11),
              ),
              series: <CircularSeries<SourceEntry, String>>[
                DoughnutSeries<SourceEntry, String>(
                  dataSource: data,
                  xValueMapper: (e, _) => _sourceLabel(e.sourceType),
                  yValueMapper: (e, _) => e.cnt,
                  pointColorMapper: (e, i) => palette[i % palette.length],
                  innerRadius: '60%',
                  // Data labels are shown via the legend below. The on-slice
                  // builder template triggers a layout crash in
                  // syncfusion_flutter_charts 28.2.12 (CircularDataLabelStack),
                  // so it is intentionally disabled here.
                  dataLabelSettings: const DataLabelSettings(isVisible: false),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _ConfidenceSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsConfidenceProvider);
    return ChartCard(
      title: 'توزیع اطمینان',
      subtitle: 'بازه‌های امتیاز',
      icon: AppIcons.gauge,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errMsg(e), onRetry: () => ref.invalidate(analyticsConfidenceProvider)),
        data: (data) {
          if (data.isEmpty) return const ChartEmpty();
          return SizedBox(
            height: 240,
            child: SfCartesianChart(
              plotAreaBorderWidth: 0,
              primaryXAxis: NumericAxis(
                majorGridLines: const MajorGridLines(width: 0),
                axisLine: AxisLine(color: Colors.white.withValues(alpha: 0.1)),
                labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 10, fontFamily: 'Vazirmatn'),
                numberFormat: null,
              ),
              primaryYAxis: NumericAxis(
                majorGridLines: MajorGridLines(width: 0.5, color: Colors.white.withValues(alpha: 0.06)),
                axisLine: const AxisLine(width: 0),
                labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 10, fontFamily: 'Vazirmatn'),
              ),
              series: <CartesianSeries<ConfidenceEntry, num>>[
                ColumnSeries<ConfidenceEntry, num>(
                  dataSource: data,
                  xValueMapper: (e, _) => (e.bin * 100).roundToDouble(),
                  yValueMapper: (e, _) => e.cnt,
                  gradient: const LinearGradient(colors: [Color(0xFF10B981), Color(0xFF06B6D4)], begin: Alignment.bottomCenter, end: Alignment.topCenter),
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _LettersSection extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analyticsLettersProvider);
    return ChartCard(
      title: 'پرتکرارترین پلاک‌ها',
      subtitle: 'بر اساس فراوانی',
      icon: AppIcons.trophy,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errMsg(e), onRetry: () => ref.invalidate(analyticsLettersProvider)),
        data: (data) {
          if (data.isEmpty) return const ChartEmpty();
          final sorted = [...data]..sort((a, b) {
              final cmp = b.cnt.compareTo(a.cnt);
              return cmp != 0 ? cmp : a.platePersian.compareTo(b.platePersian);
            });
          final top = sorted.take(12).toList();
          return SizedBox(
            height: 300,
            child: SfCartesianChart(
              plotAreaBorderWidth: 0,
              primaryXAxis: CategoryAxis(
                majorGridLines: const MajorGridLines(width: 0),
                axisLine: AxisLine(color: Colors.white.withValues(alpha: 0.1)),
                labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.45), fontSize: 10, fontFamily: 'Vazirmatn'),
              ),
              primaryYAxis: NumericAxis(
                majorGridLines: MajorGridLines(width: 0.5, color: Colors.white.withValues(alpha: 0.06)),
                axisLine: const AxisLine(width: 0),
                labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 10, fontFamily: 'Vazirmatn'),
              ),
              series: <CartesianSeries<LetterEntry, String>>[
                BarSeries<LetterEntry, String>(
                  dataSource: top,
                  xValueMapper: (e, _) => e.platePersian,
                  yValueMapper: (e, _) => e.cnt,
                  gradient: const LinearGradient(colors: [Color(0xFFF59E0B), Color(0xFFF97316)]),
                  borderRadius: const BorderRadius.horizontal(right: Radius.circular(4)),
                ),
              ],
            ),
          );
        },
      ),
    );
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

String _errMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
