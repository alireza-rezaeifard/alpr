// lib/app/router.dart
// go_router configuration with an auth redirect guard for all 6 views + login.
// Requirements: 1.2, 1.3, 1.4, 1.6, 1.9, 18.1, 18.2, 18.5

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../core/auth_interceptor.dart';
import '../data/controllers/auth_controller.dart';
import '../features/auth/login_screen.dart';
import '../features/dashboard/dashboard_view.dart';
import '../features/history/history_view.dart';
import '../features/analytics/analytics_view.dart';
import '../features/sessions/sessions_view.dart';
import '../features/detection/detection_view.dart';
import '../features/cameras/cameras_view.dart';
import 'shell_scaffold.dart';

/// Route path for the login screen.
const String kLoginRoute = '/login';

/// Default route once authenticated.
const String kDashboardRoute = '/dashboard';

/// Provides the app's [GoRouter] with a redirect guard wired to auth state.
///
/// The guard consults [authControllerProvider] (the session source of truth)
/// and [AuthInterceptor.reauthNotifier] (raised on a backend 401) so that:
/// - unauthenticated users are forced to [kLoginRoute] (Requirement 18.1);
/// - a successful login redirects away from [kLoginRoute] to the dashboard
///   (Requirement 18.2);
/// - a 401 that clears the token redirects back to login (Requirement 18.3);
/// - navigating between protected screens preserves the session
///   (Requirement 18.5).
final routerProvider = Provider<GoRouter>((ref) {
  // Re-evaluate redirects whenever auth state changes or a 401 is signalled.
  final refresh = _AuthRefreshListenable(ref);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: kDashboardRoute,
    refreshListenable: refresh,
    redirect: (context, state) {
      final loggedIn = ref.read(authControllerProvider).isAuthenticated;
      final needsReauth = AuthInterceptor.needsReauthentication;
      final atLogin = state.matchedLocation == kLoginRoute;

      // Not authenticated (or a 401 cleared the session): force the login screen.
      if (!loggedIn || needsReauth) {
        return atLogin ? null : kLoginRoute;
      }

      // Authenticated but sitting on the login screen: go to the dashboard.
      if (atLogin) return kDashboardRoute;

      // Authenticated and navigating a protected route: preserve the session.
      return null;
    },
    errorBuilder: (context, state) => const _ErrorPage(),
    routes: [
      GoRoute(
        path: kLoginRoute,
        pageBuilder: (context, state) => _noTransition(
          state,
          const LoginScreen(),
        ),
      ),
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
});

/// Bridges Riverpod auth state and the 401 signal into a [Listenable] that
/// go_router can use as its `refreshListenable`.
class _AuthRefreshListenable extends ChangeNotifier {
  _AuthRefreshListenable(Ref ref) {
    // Notify when the authenticated session changes (login / logout / expiry).
    _subscription = ref.listen<AuthState>(
      authControllerProvider,
      (_, __) => notifyListeners(),
    );
    // Notify when a 401 raises the re-authentication signal.
    AuthInterceptor.reauthNotifier.addListener(notifyListeners);
  }

  late final ProviderSubscription<AuthState> _subscription;

  @override
  void dispose() {
    AuthInterceptor.reauthNotifier.removeListener(notifyListeners);
    _subscription.close();
    super.dispose();
  }
}

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
                onPressed: () => context.go(kDashboardRoute),
                child: const Text('Go to Dashboard'),
              ),
            ],
          ),
        ),
      );
}
