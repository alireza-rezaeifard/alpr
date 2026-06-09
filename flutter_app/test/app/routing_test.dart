// test/app/routing_test.dart
// Widget tests for routing, RTL root layout, and the 401 interceptor wiring.
//
// Covers:
//   - RTL root layout (Requirement 17.2)
//   - Redirect forces unauthenticated users to /login (Requirement 18.1)
//   - Successful auth stores the token and navigates to the dashboard
//     (Requirement 18.2)
//   - A 401 clears the stored token and returns the user to login
//     (Requirement 18.3)
//   - Navigating protected routes preserves the authenticated session
//     (Requirement 18.5)
//
// The login/dashboard navigation and 401 behaviour are exercised through the
// production redirect guard (`authRedirect`), the real `authControllerProvider`
// (backed by a fake repository) and the real `AuthInterceptor`. Lightweight
// placeholder routes stand in for the Fluent feature screens so these tests
// stay focused on the foundation routing layer.

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:flutter_app/app/app.dart';
import 'package:flutter_app/app/router.dart';
import 'package:flutter_app/core/auth_interceptor.dart';
import 'package:flutter_app/core/secure_storage.dart';
import 'package:flutter_app/data/controllers/auth_controller.dart';
import 'package:flutter_app/data/models/user_auth.dart';
import 'package:flutter_app/data/repositories/auth_repo.dart';
import 'package:flutter_app/features/auth/login_screen.dart';

/// A fake [AuthRepo] that returns a canned session without any network I/O.
class _FakeAuthRepo extends AuthRepo {
  _FakeAuthRepo();

  static UserAuth validSession() => UserAuth(
        token: 'fake-token',
        role: 'Operator',
        expiresAt: DateTime.now().add(const Duration(hours: 1)).toIso8601String(),
        permissions: const ['view', 'manage_cameras', 'run_detection'],
      );

  @override
  Future<UserAuth> login(String username, String password) async {
    return validSession();
  }

  @override
  Future<void> logout() async {}

  @override
  Future<Map<String, dynamic>> me() async => {
        'role': 'Operator',
        'expires_at': DateTime.now().add(const Duration(hours: 1)).toIso8601String(),
        'permissions': const ['view'],
      };
}

/// Listenable mirroring the production refresh wiring: it fires when the auth
/// session changes or when a 401 raises the re-authentication signal.
class _TestAuthRefresh extends ChangeNotifier {
  _TestAuthRefresh(ProviderContainer container) {
    _sub = container.listen<AuthState>(
      authControllerProvider,
      (_, __) => notifyListeners(),
    );
    AuthInterceptor.reauthNotifier.addListener(notifyListeners);
  }

  late final ProviderSubscription<AuthState> _sub;

  @override
  void dispose() {
    AuthInterceptor.reauthNotifier.removeListener(notifyListeners);
    _sub.close();
    super.dispose();
  }
}

/// Builds a lightweight router that reuses the production [authRedirect] guard
/// but renders plain placeholder routes instead of the Fluent feature screens.
GoRouter _buildHarnessRouter(ProviderContainer container, Listenable refresh) {
  return GoRouter(
    initialLocation: kDashboardRoute,
    refreshListenable: refresh,
    redirect: (context, state) => authRedirect(
      loggedIn: container.read(authControllerProvider).isAuthenticated,
      needsReauth: AuthInterceptor.needsReauthentication,
      matchedLocation: state.matchedLocation,
    ),
    routes: [
      GoRoute(
        path: kLoginRoute,
        builder: (_, __) => const Text('LOGIN', textDirection: TextDirection.rtl),
      ),
      GoRoute(
        path: '/dashboard',
        builder: (_, __) => const Text('DASHBOARD', textDirection: TextDirection.rtl),
      ),
      GoRoute(
        path: '/cameras',
        builder: (_, __) => const Text('CAMERAS', textDirection: TextDirection.rtl),
      ),
    ],
  );
}

void main() {
  setUp(() async {
    // Reset foundation singletons before each test.
    await SecureStorage.deleteToken();
    AuthInterceptor.clearReauthFlag();
  });

  group('authRedirect (pure routing guard)', () {
    test('unauthenticated users are forced to /login (Req 18.1)', () {
      expect(
        authRedirect(loggedIn: false, needsReauth: false, matchedLocation: '/dashboard'),
        kLoginRoute,
      );
      expect(
        authRedirect(loggedIn: false, needsReauth: false, matchedLocation: '/cameras'),
        kLoginRoute,
      );
    });

    test('unauthenticated user already on /login is left there (Req 18.1)', () {
      expect(
        authRedirect(loggedIn: false, needsReauth: false, matchedLocation: kLoginRoute),
        isNull,
      );
    });

    test('authenticated user on /login is sent to the dashboard (Req 18.2)', () {
      expect(
        authRedirect(loggedIn: true, needsReauth: false, matchedLocation: kLoginRoute),
        kDashboardRoute,
      );
    });

    test('authenticated user on a protected route stays put (Req 18.5)', () {
      expect(
        authRedirect(loggedIn: true, needsReauth: false, matchedLocation: '/cameras'),
        isNull,
      );
    });

    test('a 401 (needsReauth) forces login even when still logged in (Req 18.3)', () {
      expect(
        authRedirect(loggedIn: true, needsReauth: true, matchedLocation: '/cameras'),
        kLoginRoute,
      );
    });
  });

  group('RTL root layout', () {
    testWidgets(
      'app root lays out right-to-left and shows the login screen when '
      'unauthenticated (Req 17.2, 18.1)',
      (tester) async {
        await tester.pumpWidget(
          const ProviderScope(child: PlprApp()),
        );
        await tester.pumpAndSettle();

        // The login screen is presented because no session token is held.
        expect(find.byType(LoginScreen), findsOneWidget);

        // The root layout is right-to-left.
        final direction =
            Directionality.of(tester.element(find.byType(LoginScreen)));
        expect(direction, TextDirection.rtl);
      },
    );
  });

  group('routing + 401 interceptor (widget)', () {
    testWidgets(
      'successful auth navigates to the dashboard and preserves the session '
      'across navigation (Req 18.2, 18.5)',
      (tester) async {
        final container = ProviderContainer(
          overrides: [
            authRepoProvider.overrideWithValue(_FakeAuthRepo()),
          ],
        );
        addTearDown(container.dispose);

        final refresh = _TestAuthRefresh(container);
        addTearDown(refresh.dispose);

        final router = _buildHarnessRouter(container, refresh);
        addTearDown(router.dispose);

        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: MaterialApp.router(routerConfig: router),
          ),
        );
        await tester.pumpAndSettle();

        // Unauthenticated start lands on the login screen.
        expect(find.text('LOGIN'), findsOneWidget);
        expect(find.text('DASHBOARD'), findsNothing);

        // Authenticate: the controller stores the token and the redirect guard
        // navigates to the dashboard.
        await container
            .read(authControllerProvider.notifier)
            .login('admin', 'secret');
        await tester.pumpAndSettle();

        expect(await SecureStorage.readToken(), 'fake-token');
        expect(find.text('DASHBOARD'), findsOneWidget);
        expect(find.text('LOGIN'), findsNothing);

        // Navigate to another protected route: the session is preserved.
        router.go('/cameras');
        await tester.pumpAndSettle();

        expect(find.text('CAMERAS'), findsOneWidget);
        expect(find.text('LOGIN'), findsNothing);
        expect(
          container.read(authControllerProvider).isAuthenticated,
          isTrue,
        );
      },
    );

    testWidgets(
      'a 401 clears the stored token and redirects back to login '
      '(Req 18.3, 18.2)',
      (tester) async {
        final container = ProviderContainer(
          overrides: [
            authRepoProvider.overrideWithValue(_FakeAuthRepo()),
          ],
        );
        addTearDown(container.dispose);

        final refresh = _TestAuthRefresh(container);
        addTearDown(refresh.dispose);

        final router = _buildHarnessRouter(container, refresh);
        addTearDown(router.dispose);

        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: MaterialApp.router(routerConfig: router),
          ),
        );
        await tester.pumpAndSettle();

        // Start authenticated on the dashboard.
        await container
            .read(authControllerProvider.notifier)
            .login('admin', 'secret');
        await tester.pumpAndSettle();
        expect(find.text('DASHBOARD'), findsOneWidget);
        expect(await SecureStorage.hasToken(), isTrue);

        // Drive a real 401 through the production AuthInterceptor.
        final interceptor = AuthInterceptor();
        final error = DioException(
          requestOptions: RequestOptions(path: '/cameras'),
          response: Response(
            requestOptions: RequestOptions(path: '/cameras'),
            statusCode: 401,
            data: const {'error': 'auth_required'},
          ),
          type: DioExceptionType.badResponse,
        );
        interceptor.onError(error, _NoopErrorHandler());

        // Allow the interceptor's async 401 handling to complete.
        await tester.pump(const Duration(milliseconds: 50));
        await tester.pumpAndSettle();

        // The interceptor cleared the token and raised the reauth signal, and
        // the router redirected back to the login screen.
        expect(await SecureStorage.hasToken(), isFalse);
        expect(AuthInterceptor.needsReauthentication, isTrue);
        expect(find.text('LOGIN'), findsOneWidget);
        expect(find.text('DASHBOARD'), findsNothing);
      },
    );
  });
}

/// Error handler that swallows the error so the interceptor's 401 side-effects
/// (token clear + reauth signal) can be observed without an exception.
class _NoopErrorHandler extends ErrorInterceptorHandler {
  @override
  void next(DioException err) {}
}
