// lib/shared/widgets/screen_shell.dart
// Shared Persian/RTL screen header + permission helpers used by the feature
// screens. The header keeps every screen visually consistent (title, subtitle,
// optional trailing actions) while the permission helpers read the active
// session (the auth controller is the source of truth set at login).

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/controllers/auth_controller.dart';
import '../app_icons.dart';

/// Returns true when the logged-in session holds [permission].
/// Admin receives every permission in its login permission set.
bool sessionHasPermission(WidgetRef ref, String permission) {
  final session = ref.watch(authControllerProvider).session;
  return session?.hasPermission(permission) ?? false;
}

/// Shows [child] only when the active session holds [permission]; otherwise
/// renders [fallback] (an empty box by default). Used to hide controls whose
/// action the current role lacks (Requirement 18.4).
class SessionPermissionGate extends ConsumerWidget {
  final String permission;
  final Widget child;
  final Widget? fallback;

  const SessionPermissionGate({
    super.key,
    required this.permission,
    required this.child,
    this.fallback,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (sessionHasPermission(ref, permission)) return child;
    return fallback ?? const SizedBox.shrink();
  }
}

/// Persian page header with a title, optional subtitle, and trailing actions.
class ScreenHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final List<Widget> actions;

  const ScreenHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.actions = const [],
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFFFAFAFA),
                ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: 4),
                Text(
                  subtitle!,
                  style: const TextStyle(
                    fontSize: 13,
                    color: Color(0xFF9CA3AF),
                  ),
                ),
              ],
            ],
          ),
        ),
        ...actions,
      ],
    );
  }
}

/// A compact, theme-consistent button used in screen headers and toolbars.
class ToolbarButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool primary;
  final bool danger;

  const ToolbarButton({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.primary = false,
    this.danger = false,
  });

  @override
  Widget build(BuildContext context) {
    final disabled = onTap == null;
    final accent = danger ? const Color(0xFFEF4444) : const Color(0xFF3B82F6);
    final fg = primary
        ? Colors.white
        : disabled
            ? Colors.white.withValues(alpha: 0.25)
            : accent;
    return MouseRegion(
      cursor: disabled ? SystemMouseCursors.basic : SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
          decoration: BoxDecoration(
            color: primary
                ? accent.withValues(alpha: disabled ? 0.4 : 1)
                : accent.withValues(alpha: disabled ? 0.04 : 0.12),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: primary
                  ? Colors.transparent
                  : accent.withValues(alpha: disabled ? 0.1 : 0.3),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: fg),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: fg,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Centered empty / error placeholder used by grid screens.
class GridStatePlaceholder extends StatelessWidget {
  final IconData icon;
  final String message;
  final VoidCallback? onRetry;

  const GridStatePlaceholder({
    super.key,
    required this.icon,
    required this.message,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 46, color: Colors.white.withValues(alpha: 0.2)),
          const SizedBox(height: 12),
          Text(
            message,
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.white.withValues(alpha: 0.5)),
          ),
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            TextButton.icon(
              onPressed: onRetry,
              icon: const Icon(AppIcons.refreshCw, size: 14),
              label: const Text('تلاش دوباره'),
            ),
          ],
        ],
      ),
    );
  }
}
