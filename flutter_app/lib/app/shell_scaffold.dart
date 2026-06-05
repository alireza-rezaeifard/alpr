// lib/app/shell_scaffold.dart
// Persistent navigation shell with NavigationRail (wide) and NavigationBar (narrow).
// Requirements: 1.2, 1.3, 1.4

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../shared/widgets/connectivity_badge.dart';

class ShellScaffold extends StatelessWidget {
  final Widget child;
  const ShellScaffold({super.key, required this.child});

  static const _destinations = [
    _NavDest(icon: Icons.dashboard, label: 'Dashboard', path: '/dashboard'),
    _NavDest(icon: Icons.history,   label: 'History',   path: '/history'),
    _NavDest(icon: Icons.bar_chart, label: 'Analytics', path: '/analytics'),
    _NavDest(icon: Icons.list_alt,  label: 'Sessions',  path: '/sessions'),
    _NavDest(icon: Icons.camera_alt,label: 'Detection', path: '/detection'),
    _NavDest(icon: Icons.videocam,  label: 'Cameras',   path: '/cameras'),
  ];

  int _selectedIndex(BuildContext context) {
    final loc = GoRouterState.of(context).uri.path;
    final idx = _destinations.indexWhere((d) => loc.startsWith(d.path));
    return idx < 0 ? 0 : idx;
  }

  @override
  Widget build(BuildContext context) {
    final selectedIndex = _selectedIndex(context);
    final isWide = MediaQuery.sizeOf(context).width >= 720;

    if (isWide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: selectedIndex,
              onDestinationSelected: (i) =>
                  context.go(_destinations[i].path),
              labelType: NavigationRailLabelType.all,
              leading: const Padding(
                padding: EdgeInsets.all(8),
                child: ConnectivityBadge(),
              ),
              destinations: _destinations
                  .map((d) => NavigationRailDestination(
                        icon: Icon(d.icon),
                        label: Text(d.label),
                      ))
                  .toList(),
            ),
            const VerticalDivider(width: 1),
            Expanded(child: child),
          ],
        ),
      );
    }

    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex,
        onDestinationSelected: (i) => context.go(_destinations[i].path),
        destinations: _destinations
            .map((d) => NavigationDestination(
                  icon: Icon(d.icon),
                  label: d.label,
                ))
            .toList(),
      ),
    );
  }
}

class _NavDest {
  final IconData icon;
  final String label;
  final String path;
  const _NavDest({required this.icon, required this.label, required this.path});
}
