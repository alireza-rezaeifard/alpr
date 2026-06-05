// lib/app/router.dart
// go_router configuration with routes for all 6 views.
// Requirements: 1.2, 1.3, 1.4, 1.6, 1.9

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../features/dashboard/dashboard_view.dart';
import '../features/history/history_view.dart';
import '../features/analytics/analytics_view.dart';
import '../features/sessions/sessions_view.dart';
import '../features/detection/detection_view.dart';
import '../features/cameras/cameras_view.dart';
import 'shell_scaffold.dart';

final GoRouter appRouter = GoRouter(
  initialLocation: '/dashboard',
  errorBuilder: (context, state) => const _ErrorPage(),
  routes: [
    ShellRoute(
      builder: (context, state, child) => ShellScaffold(child: child),
      routes: [
        GoRoute(
          path: '/dashboard',
          pageBuilder: (context, state) => _noTransition(
            state, const DashboardView(),
          ),
        ),
        GoRoute(
          path: '/history',
          pageBuilder: (context, state) => _noTransition(
            state, const HistoryView(),
          ),
        ),
        GoRoute(
          path: '/analytics',
          pageBuilder: (context, state) => _noTransition(
            state, const AnalyticsView(),
          ),
        ),
        GoRoute(
          path: '/sessions',
          pageBuilder: (context, state) => _noTransition(
            state, const SessionsView(),
          ),
        ),
        GoRoute(
          path: '/detection',
          pageBuilder: (context, state) => _noTransition(
            state, const DetectionView(),
          ),
        ),
        GoRoute(
          path: '/cameras',
          pageBuilder: (context, state) => _noTransition(
            state, const CamerasView(),
          ),
        ),
      ],
    ),
  ],
);

CustomTransitionPage<void> _noTransition(GoRouterState state, Widget child) {
  return CustomTransitionPage<void>(
    key: state.pageKey,
    child: child,
    transitionsBuilder: (_, __, ___, c) => c,
  );
}

class _ErrorPage extends StatelessWidget {
  const _ErrorPage();
  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, size: 48, color: Colors.red),
              const SizedBox(height: 16),
              const Text('Page failed to load'),
              const SizedBox(height: 8),
              ElevatedButton(
                onPressed: () => context.go('/dashboard'),
                child: const Text('Go to Dashboard'),
              ),
            ],
          ),
        ),
      );
}
