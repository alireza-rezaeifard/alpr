// lib/features/dashboard/dashboard_view.dart
// Dashboard with KPI cards, a Syncfusion radial gauge, and Syncfusion charts
// (Requirement 17.6), plus a recent-detections list.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:syncfusion_flutter_charts/charts.dart' hide CornerStyle;
import 'package:syncfusion_flutter_gauges/gauges.dart';

import '../../core/api_client.dart';
import '../../core/persian_format.dart';
import '../../data/models/chart_models.dart';
import '../../data/models/detection_model.dart';
import '../../data/models/stats_model.dart';
import '../../data/repositories/detections_repo.dart';
import '../../data/repositories/stats_repo.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/chart_card.dart';
import '../../shared/widgets/screen_shell.dart';

final _statsRepoProvider = Provider((_) => StatsRepo());
final _detectionsRepoProvider = Provider((_) => DetectionsRepo());

final statsProvider = FutureProvider<StatsModel>((ref) => ref.read(_statsRepoProvider).getStats());
final timelineProvider = FutureProvider<List<TimelineEntry>>((ref) => ref.read(_statsRepoProvider).getTimeline(days: 7));
final sourcesProvider = FutureProvider<List<SourceEntry>>((ref) => ref.read(_statsRepoProvider).getSources());
final recentDetectionsProvider = FutureProvider<DetectionsResponse>((ref) => ref.read(_detectionsRepoProvider).getDetections(limit: 8, offset: 0));

class DashboardView extends ConsumerWidget {
  const DashboardView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        ScreenHeader(
          title: 'داشبورد',
          subtitle: 'نمای کلی سامانه تشخیص پلاک',
          actions: [
            ToolbarButton(
              icon: AppIcons.refreshCw,
              label: 'بازخوانی',
              onTap: () {
                ref.invalidate(statsProvider);
                ref.invalidate(timelineProvider);
                ref.invalidate(sourcesProvider);
                ref.invalidate(recentDetectionsProvider);
              },
            ),
          ],
        ),
        const SizedBox(height: 24),
        const _StatsSection(),
        const SizedBox(height: 16),
        LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth > 900;
            final timeline = _TimelineChart();
            final gauge = _ConfidenceGauge();
            if (wide) {
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: 2, child: timeline),
                  const SizedBox(width: 16),
                  Expanded(child: gauge),
                ],
              );
            }
            return Column(children: [timeline, const SizedBox(height: 16), gauge]);
          },
        ),
        const SizedBox(height: 16),
        LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth > 900;
            final sources = _SourcesChart();
            final recent = _RecentDetections();
            if (wide) {
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: sources),
                  const SizedBox(width: 16),
                  Expanded(flex: 2, child: recent),
                ],
              );
            }
            return Column(children: [sources, const SizedBox(height: 16), recent]);
          },
        ),
      ],
    );
  }
}

// ── KPI cards ───────────────────────────────────────────────────────────────

class _StatsSection extends ConsumerWidget {
  const _StatsSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statsAsync = ref.watch(statsProvider);
    return statsAsync.when(
      loading: () => const SizedBox(height: 110, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
      error: (e, _) => _ErrorBanner(message: _errorMessage(e), onRetry: () => ref.invalidate(statsProvider)),
      data: (stats) => LayoutBuilder(
        builder: (context, constraints) {
          final cols = constraints.maxWidth > 900 ? 4 : 2;
          return GridView.count(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            crossAxisCount: cols,
            crossAxisSpacing: 16,
            mainAxisSpacing: 16,
            childAspectRatio: 2.4,
            children: [
              _StatCard(title: 'کل تشخیص‌ها', value: PersianFormat.number(stats.totalDetections), icon: AppIcons.search, accent: const Color(0xFF3B82F6), change: '${PersianFormat.number(stats.detections7d)} در هفته اخیر'),
              _StatCard(title: 'پلاک‌های یکتا', value: PersianFormat.number(stats.uniquePlates), icon: AppIcons.creditCard, accent: const Color(0xFF8B5CF6)),
              _StatCard(title: 'جلسات', value: PersianFormat.number(stats.totalSessions), icon: AppIcons.layers, accent: const Color(0xFF06B6D4), change: '${PersianFormat.number(stats.sessions7d)} در هفته اخیر'),
              _StatCard(title: 'میانگین اطمینان', value: stats.avgConfidence != null ? PersianFormat.percentage(stats.avgConfidence!) : '—', icon: AppIcons.target, accent: const Color(0xFF10B981)),
            ],
          );
        },
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color accent;
  final String? change;
  const _StatCard({required this.title, required this.value, required this.icon, required this.accent, this.change});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              Expanded(child: Text(title, style: TextStyle(fontSize: 13, color: Colors.white.withValues(alpha: 0.55)))),
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: accent.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)),
                child: Icon(icon, size: 16, color: accent),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(value, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: Colors.white)),
          if (change != null) ...[
            const SizedBox(height: 4),
            Text(change!, style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.4))),
          ],
        ],
      ),
    );
  }
}

// ── Timeline (Syncfusion column chart) ───────────────────────────────────────

class _TimelineChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(timelineProvider);
    return ChartCard(
      title: 'روند تشخیص',
      subtitle: '۷ روز اخیر',
      icon: AppIcons.trendingUp,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errorMessage(e), onRetry: () => ref.invalidate(timelineProvider)),
        data: (data) {
          if (data.isEmpty) return const ChartEmpty();
          return SizedBox(
            height: 240,
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
                labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.45), fontSize: 10, fontFamily: 'Vazirmatn'),
              ),
              series: <CartesianSeries<TimelineEntry, String>>[
                ColumnSeries<TimelineEntry, String>(
                  dataSource: data,
                  xValueMapper: (e, _) => e.dt.length >= 10 ? e.dt.substring(5) : e.dt,
                  yValueMapper: (e, _) => e.cnt,
                  gradient: const LinearGradient(colors: [Color(0xFF3B82F6), Color(0xFF8B5CF6)], begin: Alignment.bottomCenter, end: Alignment.topCenter),
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
                  width: 0.6,
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

// ── Confidence gauge (Syncfusion radial gauge) ───────────────────────────────

class _ConfidenceGauge extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(statsProvider);
    return ChartCard(
      title: 'میانگین اطمینان',
      subtitle: 'کیفیت تشخیص',
      icon: AppIcons.gauge,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errorMessage(e), onRetry: () => ref.invalidate(statsProvider)),
        data: (stats) {
          final pct = (stats.avgConfidence ?? 0) * 100;
          return SizedBox(
            height: 240,
            child: SfRadialGauge(
              axes: <RadialAxis>[
                RadialAxis(
                  minimum: 0,
                  maximum: 100,
                  showLabels: false,
                  showTicks: false,
                  startAngle: 150,
                  endAngle: 30,
                  axisLineStyle: AxisLineStyle(
                    thickness: 0.16,
                    thicknessUnit: GaugeSizeUnit.factor,
                    color: Colors.white.withValues(alpha: 0.08),
                  ),
                  pointers: <GaugePointer>[
                    RangePointer(
                      value: pct,
                      width: 0.16,
                      sizeUnit: GaugeSizeUnit.factor,
                      cornerStyle: CornerStyle.bothCurve,
                      gradient: const SweepGradient(colors: [Color(0xFF06B6D4), Color(0xFF10B981)]),
                    ),
                  ],
                  annotations: <GaugeAnnotation>[
                    GaugeAnnotation(
                      widget: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            PersianFormat.percentage(pct / 100),
                            style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w700, color: Colors.white),
                          ),
                          Text('میانگین', style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.5))),
                        ],
                      ),
                      positionFactor: 0.05,
                      angle: 90,
                    ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

// ── Sources (Syncfusion doughnut) ────────────────────────────────────────────

class _SourcesChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(sourcesProvider);
    return ChartCard(
      title: 'توزیع منابع',
      subtitle: 'بر اساس نوع',
      icon: AppIcons.pieChart,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errorMessage(e), onRetry: () => ref.invalidate(sourcesProvider)),
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
                  innerRadius: '62%',
                  // On-slice label builder templates crash in
                  // syncfusion_flutter_charts 28.2.12 (CircularDataLabelStack);
                  // counts are conveyed via the legend below instead.
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

// ── Recent detections ─────────────────────────────────────────────────────────

class _RecentDetections extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(recentDetectionsProvider);
    return ChartCard(
      title: 'تشخیص‌های اخیر',
      subtitle: 'آخرین پلاک‌ها',
      icon: AppIcons.clock,
      child: async.when(
        loading: () => const ChartLoading(),
        error: (e, _) => ChartError(message: _errorMessage(e), onRetry: () => ref.invalidate(recentDetectionsProvider)),
        data: (resp) {
          if (resp.data.isEmpty) {
            return const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: Text('تشخیصی ثبت نشده است', style: TextStyle(color: Color(0xFF9CA3AF)))),
            );
          }
          return Column(children: resp.data.map(_DetectionRow.new).toList());
        },
      ),
    );
  }
}

class _DetectionRow extends StatelessWidget {
  final DetectionModel detection;
  const _DetectionRow(this.detection);

  @override
  Widget build(BuildContext context) {
    final plate = (detection.platePersian?.isNotEmpty ?? false) ? detection.platePersian! : detection.plateDtrb;
    final ts = DateTime.tryParse(detection.timestamp);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
      margin: const EdgeInsets.only(bottom: 6),
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(8), color: Colors.white.withValues(alpha: 0.02)),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(color: const Color(0xFF3B82F6).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)),
            child: const Icon(AppIcons.creditCard, size: 16, color: Color(0xFF3B82F6)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(plate, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w500, fontSize: 13)),
                Text(
                  '${_sourceLabel(detection.sourceType)} • ${ts != null ? PersianFormat.dateTime(ts) : detection.timestamp}',
                  style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.4)),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(color: const Color(0xFF10B981).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(6)),
            child: Text(PersianFormat.percentage(detection.confidence), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Color(0xFF10B981))),
          ),
        ],
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

class _ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorBanner({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFFEF4444).withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFEF4444).withValues(alpha: 0.2)),
        ),
        child: Row(
          children: [
            const Icon(AppIcons.alertCircle, size: 16, color: Color(0xFFEF4444)),
            const SizedBox(width: 8),
            Expanded(child: Text(message, style: const TextStyle(fontSize: 12, color: Color(0xFFEF4444)))),
            TextButton(onPressed: onRetry, child: const Text('تلاش دوباره', style: TextStyle(fontSize: 12))),
          ],
        ),
      );
}

String _errorMessage(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
