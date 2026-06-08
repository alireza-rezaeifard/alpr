// lib/shared/widgets/connectivity_badge.dart
// Fluent UI connectivity badge with Persian labels.
// Requirements: 17.1, 17.3

import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../../core/health_controller.dart';

class ConnectivityBadge extends ConsumerWidget {
  const ConnectivityBadge({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final healthAsync = ref.watch(healthControllerProvider);

    return healthAsync.when(
      loading: () => _Badge(
        label: 'در حال اتصال',
        color: const Color(0xFFF59E0B),
        icon: FluentIcons.sync,
        animate: true,
      ),
      error: (_, __) => _Badge(
        label: 'خطا',
        color: const Color(0xFFEF4444),
        icon: FluentIcons.error_badge,
        onTap: () => ref.read(healthControllerProvider.notifier).retry(),
      ),
      data: (state) {
        switch (state.status) {
          case ConnectivityStatus.connected:
            return const _Badge(
              label: 'متصل',
              color: Color(0xFF22C55E),
              icon: FluentIcons.wifi,
            );
          case ConnectivityStatus.configError:
            return _Badge(
              label: 'خطای پیکربندی',
              color: const Color(0xFFEF4444),
              icon: FluentIcons.settings,
              tooltip: state.errorMessage,
            );
          case ConnectivityStatus.disconnected:
            return _Badge(
              label: 'قطع شده',
              color: const Color(0xFFEF4444),
              icon: FluentIcons.plug_disconnected,
              tooltip: state.errorMessage,
              onTap: () => ref.read(healthControllerProvider.notifier).retry(),
            );
          case ConnectivityStatus.unknown:
            return const _Badge(
              label: 'نامشخص',
              color: Color(0xFF6B7280),
              icon: FluentIcons.unknown,
            );
        }
      },
    );
  }
}

class _Badge extends StatelessWidget {
  final String label;
  final Color color;
  final IconData icon;
  final String? tooltip;
  final VoidCallback? onTap;
  final bool animate;

  const _Badge({
    required this.label,
    required this.color,
    required this.icon,
    this.tooltip,
    this.onTap,
    this.animate = false,
  });

  @override
  Widget build(BuildContext context) {
    Widget badge = GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withOpacity(0.2)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: color,
              ),
            ),
            const SizedBox(width: 8),
            Icon(icon, size: 14, color: color),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );

    if (animate) {
      badge = badge.animate(onPlay: (c) => c.repeat())
          .shimmer(duration: 1500.ms);
    }

    if (tooltip != null) {
      badge = Tooltip(message: tooltip!, child: badge);
    }

    return badge;
  }
}
