// lib/shared/widgets/chart_card.dart
// Shared card + state widgets used by the Syncfusion analytics/dashboard charts.

import 'package:flutter/material.dart';

class ChartCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final Widget child;

  const ChartCard({
    super.key,
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.child,
  });

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
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: Colors.white.withValues(alpha: 0.45)),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Colors.white)),
              const Spacer(),
              Text(subtitle, style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.4))),
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }
}

class ChartLoading extends StatelessWidget {
  const ChartLoading({super.key});
  @override
  Widget build(BuildContext context) =>
      const SizedBox(height: 200, child: Center(child: CircularProgressIndicator(strokeWidth: 2)));
}

class ChartEmpty extends StatelessWidget {
  const ChartEmpty({super.key});
  @override
  Widget build(BuildContext context) => SizedBox(
        height: 160,
        child: Center(
          child: Text('داده‌ای برای نمایش نیست', style: TextStyle(color: Colors.white.withValues(alpha: 0.35))),
        ),
      );
}

class ChartError extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const ChartError({super.key, required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 120,
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(message, textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.45))),
              TextButton(onPressed: onRetry, child: const Text('تلاش دوباره', style: TextStyle(fontSize: 12))),
            ],
          ),
        ),
      );
}
