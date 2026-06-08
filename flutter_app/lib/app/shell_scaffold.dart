// lib/app/shell_scaffold.dart
// Fluent UI NavigationPane shell with Persian RTL layout.
// Requirements: 17.1, 17.2, 17.3

import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../shared/widgets/connectivity_badge.dart';

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
  ];

  int _selectedIndex(BuildContext context) {
    final loc = GoRouterState.of(context).uri.path;
    final idx = _destinations.indexWhere((d) => loc.startsWith(d.path));
    return idx < 0 ? 0 : idx;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedIndex = _selectedIndex(context);

    return NavigationView(
      appBar: const NavigationAppBar(
        title: Padding(
          padding: EdgeInsets.only(right: 12.0),
          child: Text(
            'سامانه تشخیص پلاک خودرو',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        actions: Padding(
          padding: EdgeInsets.symmetric(horizontal: 12.0),
          child: ConnectivityBadge(),
        ),
      ),
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
            ],
          ),
        ),
        items: _destinations.map((dest) {
          return PaneItem(
            icon: Icon(dest.icon),
            title: Text(dest.label),
            body: const SizedBox.shrink(),
          );
        }).toList(),
        footerItems: [
          PaneItemSeparator(),
          PaneItem(
            icon: const Icon(FluentIcons.settings),
            title: const Text('تنظیمات'),
            body: const SizedBox.shrink(),
          ),
        ],
      ),
      content: ScaffoldPage.withPadding(
        content: child,
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
