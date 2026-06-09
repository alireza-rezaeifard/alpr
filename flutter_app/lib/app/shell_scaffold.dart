// lib/app/shell_scaffold.dart
// Fluent UI NavigationPane shell with Persian RTL layout.
// Requirements: 17.1, 17.2, 17.3

import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../data/controllers/auth_controller.dart';
import '../shared/widgets/connectivity_badge.dart';
import '../shared/widgets/permission_gate.dart';

/// Provider for pane display mode
final paneDisplayModeProvider = StateProvider<PaneDisplayMode>(
  (_) => PaneDisplayMode.auto,
);

class ShellScaffold extends ConsumerWidget {
  final Widget child;
  const ShellScaffold({super.key, required this.child});

  // Persian navigation destinations
  static const _destinations = [
    _NavDest(icon: FluentIcons.home, label: 'داشبورد', path: '/dashboard'),
    _NavDest(icon: FluentIcons.history, label: 'تاریخچه', path: '/history'),
    _NavDest(icon: FluentIcons.bar_chart_vertical, label: 'تحلیل‌ها', path: '/analytics'),
    _NavDest(icon: FluentIcons.timer, label: 'جلسات', path: '/sessions'),
    _NavDest(icon: FluentIcons.number_symbol, label: 'تشخیص', path: '/detection'),
    _NavDest(icon: FluentIcons.camera, label: 'دوربین‌ها', path: '/cameras'),
    _NavDest(icon: FluentIcons.video, label: 'پایش زنده', path: '/live-monitor'),
    _NavDest(icon: FluentIcons.list, label: 'فهرست‌ها و هشدارها', path: '/watchlists'),
  ];

  int _selectedIndex(BuildContext context) {
    final loc = GoRouterState.of(context).uri.path;
    final idx = _destinations.indexWhere((d) => loc.startsWith(d.path));
    return idx < 0 ? 0 : idx;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedIndex = _selectedIndex(context);
    final auth = ref.watch(currentSessionProvider);
    final canManageConfig = auth?.hasPermission(Permissions.manageConfig) ?? false;
    final canManageUsers = auth?.hasPermission(Permissions.manageUsers) ?? false;
    final canViewAudit = auth?.hasPermission(Permissions.viewAudit) ?? false;

    return NavigationView(
      pane: NavigationPane(
        selected: selectedIndex,
        onChanged: (index) {
          if (index < _destinations.length) {
            context.go(_destinations[index].path);
          }
        },
        displayMode: PaneDisplayMode.auto,
        header: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [Color(0xFF0078D4), Color(0xFF106EBE)],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  FluentIcons.number_symbol,
                  color: Colors.white,
                  size: 20,
                ),
              ),
              const SizedBox(width: 12),
              const Expanded(
                child: Text(
                  'سامانه تشخیص پلاک خودرو',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const ConnectivityBadge(),
            ],
          ),
        ),
        items: _destinations.asMap().entries.map((entry) {
          final i = entry.key;
          final dest = entry.value;
          return PaneItem(
            icon: Icon(dest.icon),
            title: Text(dest.label),
            // Only the selected pane hosts the routed content. Fluent keeps all
            // pane bodies alive in an IndexedStack, so reusing the same `child`
            // in every body mounts it (and its GlobalKeys, e.g. PlutoGrid) many
            // times at once and crashes. Non-selected panes get an empty body.
            body: i == selectedIndex
                ? ScaffoldPage.withPadding(content: child)
                : const SizedBox.shrink(),
          );
        }).toList(),
        footerItems: [
          PaneItemSeparator(),
          // Admin-only: user management.
          if (canManageUsers)
            PaneItem(
              icon: const Icon(FluentIcons.people),
              title: const Text('کاربران'),
              body: const SizedBox.shrink(),
              onTap: () => context.go('/users'),
            ),
          // Admin-only: audit log.
          if (canViewAudit)
            PaneItem(
              icon: const Icon(FluentIcons.shield),
              title: const Text('گزارش رخدادها'),
              body: const SizedBox.shrink(),
              onTap: () => context.go('/audit'),
            ),
          PaneItem(
            icon: const Icon(FluentIcons.permissions),
            title: const Text('مجوز'),
            body: const SizedBox.shrink(),
            onTap: () => context.go('/license'),
          ),
          // The settings entry is only shown to roles that may manage config.
          if (canManageConfig)
            PaneItem(
              icon: const Icon(FluentIcons.settings),
              title: const Text('تنظیمات'),
              body: const SizedBox.shrink(),
              onTap: () => context.go('/settings'),
            ),
        ],
      ),
    );
  }
}

class _NavDest {
  final IconData icon;
  final String label;
  final String path;
  const _NavDest({
    required this.icon,
    required this.label,
    required this.path,
  });
}
