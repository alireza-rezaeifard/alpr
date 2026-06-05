// lib/shared/widgets/connectivity_badge.dart
// Persistent connectivity badge shown in the navigation shell.
// Requirements: 1.7, 1.8, 2.2, 2.3, 2.6, 2.7

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/health_controller.dart';

class ConnectivityBadge extends ConsumerWidget {
  const ConnectivityBadge({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final healthAsync = ref.watch(healthControllerProvider);

    return healthAsync.when(
      loading: () => const _StatusChip(
        label: 'Connecting…',
        color: Colors.orange,
        icon: Icons.sync,
      ),
      error: (_, __) => _StatusChip(
        label: 'Error',
        color: Colors.red,
        icon: Icons.error_outline,
        onRetry: () => ref.read(healthControllerProvider.notifier).retry(),
      ),
      data: (state) {
        switch (state.status) {
          case ConnectivityStatus.connected:
            return const _StatusChip(
              label: 'Connected',
              color: Colors.green,
              icon: Icons.check_circle_outline,
            );
          case ConnectivityStatus.configError:
            return _StatusChip(
              label: 'Config Error',
              color: Colors.red,
              icon: Icons.settings_input_component,
              tooltip: state.errorMessage,
            );
          case ConnectivityStatus.disconnected:
            return _StatusChip(
              label: 'Disconnected',
              color: Colors.red,
              icon: Icons.wifi_off,
              tooltip: state.errorMessage,
              onRetry: () =>
                  ref.read(healthControllerProvider.notifier).retry(),
            );
          case ConnectivityStatus.unknown:
            return const _StatusChip(
              label: 'Unknown',
              color: Colors.grey,
              icon: Icons.help_outline,
            );
        }
      },
    );
  }
}

class _StatusChip extends StatelessWidget {
  final String label;
  final Color color;
  final IconData icon;
  final String? tooltip;
  final VoidCallback? onRetry;

  const _StatusChip({
    required this.label,
    required this.color,
    required this.icon,
    this.tooltip,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    Widget chip = Chip(
      avatar: Icon(icon, color: Colors.white, size: 16),
      label: Text(
        label,
        style: const TextStyle(color: Colors.white, fontSize: 12),
      ),
      backgroundColor: color,
      padding: const EdgeInsets.symmetric(horizontal: 4),
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );

    if (tooltip != null) {
      chip = Tooltip(message: tooltip!, child: chip);
    }

    if (onRetry != null) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          chip,
          const SizedBox(width: 4),
          IconButton(
            icon: const Icon(Icons.refresh, size: 16),
            onPressed: onRetry,
            tooltip: 'Retry',
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 24, minHeight: 24),
          ),
        ],
      );
    }
    return chip;
  }
}
