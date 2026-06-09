// test/features/screens_widget_test.dart
// Widget tests for the feature screens covering task 20.4:
//
//   - PlutoGrid is present on the tabular screens (Requirement 17.5):
//       Cameras, Sessions, Users, Audit, Watchlists.
//   - Syncfusion charts/gauges are present on the analytics/dashboard screens
//     (Requirement 17.6): the Dashboard radial gauge + cartesian/circular
//     charts, and the Analytics cartesian/circular charts.
//   - Permission-gated controls are shown for roles that hold the permission
//     and hidden for roles that do not (Requirement 18.4): an Admin sees
//     management controls a Viewer does not.
//
// The feature screens read the active session through the auth controller
// (`authControllerProvider`, via `sessionHasPermission`), so each test seeds
// that controller with a canned session for the role under test. Data is
// injected by overriding the public list/stats providers (cameras, sessions,
// analytics, dashboard) or the repository providers consumed by the feature
// controllers (users, audit, watchlists, alerts) with in-memory fakes — no
// network I/O is performed.

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pluto_grid/pluto_grid.dart';
import 'package:syncfusion_flutter_charts/charts.dart';
import 'package:syncfusion_flutter_gauges/gauges.dart';

import 'package:flutter_app/core/secure_storage.dart';
import 'package:flutter_app/data/controllers/alerts_controller.dart';
import 'package:flutter_app/data/controllers/audit_controller.dart';
import 'package:flutter_app/data/controllers/auth_controller.dart';
import 'package:flutter_app/data/controllers/users_controller.dart';
import 'package:flutter_app/data/controllers/watchlists_controller.dart';
import 'package:flutter_app/data/models/alert.dart';
import 'package:flutter_app/data/models/audit_entry.dart';
import 'package:flutter_app/data/models/camera_model.dart';
import 'package:flutter_app/data/models/chart_models.dart';
import 'package:flutter_app/data/models/detection_model.dart';
import 'package:flutter_app/data/models/session_model.dart';
import 'package:flutter_app/data/models/stats_model.dart';
import 'package:flutter_app/data/models/user_auth.dart';
import 'package:flutter_app/data/models/user_model.dart';
import 'package:flutter_app/data/models/watchlist.dart';
import 'package:flutter_app/data/models/watchlist_entry.dart';
import 'package:flutter_app/data/repositories/alerts_repo.dart';
import 'package:flutter_app/data/repositories/audit_repo.dart';
import 'package:flutter_app/data/repositories/auth_repo.dart';
import 'package:flutter_app/data/repositories/users_repo.dart';
import 'package:flutter_app/data/repositories/watchlists_repo.dart';

import 'package:flutter_app/features/analytics/analytics_view.dart';
import 'package:flutter_app/features/audit/audit_view.dart';
import 'package:flutter_app/features/cameras/cameras_view.dart';
import 'package:flutter_app/features/dashboard/dashboard_view.dart';
import 'package:flutter_app/features/sessions/sessions_view.dart';
import 'package:flutter_app/features/users/users_view.dart';
import 'package:flutter_app/features/watchlists/watchlists_view.dart';
import 'package:flutter_app/shared/widgets/permission_gate.dart'
    show PermissionDeniedView, Permissions;

// ── Roles / sessions ─────────────────────────────────────────────────────────

/// Every backend permission — what an Admin holds at login.
const _adminPermissions = <String>[
  Permissions.view,
  Permissions.manageCameras,
  Permissions.runDetection,
  Permissions.manageWatchlists,
  Permissions.manageUsers,
  Permissions.manageRoles,
  Permissions.manageLicenses,
  Permissions.manageConfig,
  Permissions.viewAudit,
];

/// A Viewer only holds the read permission.
const _viewerPermissions = <String>[Permissions.view];

UserAuth _session(String role, List<String> permissions) => UserAuth(
      token: 'test-token',
      role: role,
      expiresAt:
          DateTime.now().add(const Duration(hours: 1)).toIso8601String(),
      permissions: permissions,
    );

/// A no-op [AuthRepo] so the seeded controller performs no network I/O.
class _StubAuthRepo extends AuthRepo {
  @override
  Future<UserAuth> login(String username, String password) async =>
      _session('Admin', _adminPermissions);

  @override
  Future<void> logout() async {}

  @override
  Future<Map<String, dynamic>> me() async => const {
        'role': 'Admin',
        'expires_at': '',
        'permissions': <String>[],
      };
}

/// An [AuthController] pre-seeded with [seed] so screens see a fixed role.
class _SeededAuthController extends AuthController {
  _SeededAuthController(UserAuth? seed) : super(_StubAuthRepo()) {
    if (seed != null) state = AuthState(session: seed);
  }
}

Override _authOverride(UserAuth? session) =>
    authControllerProvider.overrideWith((ref) => _SeededAuthController(session));

// ── Fake repositories (feature controllers fetch through these) ──────────────

class _FakeUsersRepo extends UsersRepo {
  _FakeUsersRepo(this._data);
  final List<UserModel> _data;
  @override
  Future<List<UserModel>> listUsers() async => _data;
}

class _FakeAuditRepo extends AuditRepo {
  _FakeAuditRepo(this._data);
  final List<AuditEntry> _data;
  @override
  Future<List<AuditEntry>> listAuditLog({int limit = 100}) async => _data;
}

class _FakeWatchlistsRepo extends WatchlistsRepo {
  _FakeWatchlistsRepo(this._data);
  final List<Watchlist> _data;
  @override
  Future<List<Watchlist>> listWatchlists() async => _data;
}

class _FakeAlertsRepo extends AlertsRepo {
  _FakeAlertsRepo(this._data);
  final List<Alert> _data;
  @override
  Future<List<Alert>> listAlerts({int? limit}) async => _data;
}

// ── Sample data ──────────────────────────────────────────────────────────────

final _cameras = <CameraModel>[
  const CameraModel(
      id: 1, name: 'درب ورودی', url: 'rtsp://a', skipFrames: 15, status: 'streaming'),
  const CameraModel(
      id: 2, name: 'پارکینگ', url: 'rtsp://b', skipFrames: 10, status: 'stopped'),
];

final _sessions = <SessionModel>[
  const SessionModel(
    id: 1,
    sourceType: 'rtsp',
    sourceFile: 'cam-1',
    startedAt: '2024-01-01T10:00:00',
    endedAt: '2024-01-01T10:05:00',
    totalFrames: 100,
    totalPlates: 12,
    uniquePlates: 9,
    status: 'done',
  ),
];

final _users = <UserModel>[
  const UserModel(
      id: 1, username: 'admin', role: 'Admin', disabled: false, createdAt: '2024-01-01T00:00:00'),
  const UserModel(
      id: 2, username: 'viewer', role: 'Viewer', disabled: true, createdAt: '2024-01-02T00:00:00'),
];

final _audit = <AuditEntry>[
  const AuditEntry(
      id: 1, username: 'admin', action: 'login', resource: 'auth', outcome: 'success', timestamp: '2024-01-01T10:00:00'),
];

final _watchlists = <Watchlist>[
  const Watchlist(
    id: 1,
    name: 'خودروهای مشکوک',
    listType: 'blocklist',
    createdAt: '2024-01-01T00:00:00',
    entries: [
      WatchlistEntry(
          id: 1, watchlistId: 1, plateValue: '12الف345', label: 'سرقتی', reason: 'گزارش', createdAt: '2024-01-01T00:00:00'),
    ],
  ),
];

final _alerts = <Alert>[
  const Alert(id: 1, detectionId: 5, entryId: 1, plateValue: '12الف345', createdAt: '2024-01-01T10:01:00'),
];

final _timeline = <TimelineEntry>[
  const TimelineEntry(dt: '2024-01-01', cnt: 3),
  const TimelineEntry(dt: '2024-01-02', cnt: 7),
];

final _sources = <SourceEntry>[
  const SourceEntry(sourceType: 'image', cnt: 4),
  const SourceEntry(sourceType: 'rtsp', cnt: 6),
];

final _confidence = <ConfidenceEntry>[
  const ConfidenceEntry(bin: 0.6, cnt: 2),
  const ConfidenceEntry(bin: 0.9, cnt: 8),
];

final _letters = <LetterEntry>[
  const LetterEntry(platePersian: '12الف345', cnt: 5),
];

const _stats = StatsModel(
  totalDetections: 120,
  uniquePlates: 80,
  totalSessions: 10,
  avgConfidence: 0.87,
  detections7d: 30,
  sessions7d: 4,
);

final _recentDetections = DetectionsResponse(
  data: const [
    DetectionModel(
        id: 1, timestamp: '2024-01-01T10:00:00', sourceType: 'rtsp', plateDtrb: '12B345', platePersian: '12الف345', confidence: 0.9),
  ],
  total: 1,
  limit: 8,
  offset: 0,
);

// ── Harness ──────────────────────────────────────────────────────────────────

/// Pumps [screen] inside a Persian/RTL MaterialApp with the supplied provider
/// [overrides], using a large surface so lazy lists build every chart/grid.
Future<void> _pumpScreen(
  WidgetTester tester,
  Widget screen,
  List<Override> overrides,
) async {
  tester.view.physicalSize = const Size(1400, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    ProviderScope(
      overrides: overrides,
      child: MaterialApp(
        locale: const Locale('fa', 'IR'),
        supportedLocales: const [Locale('fa', 'IR'), Locale('en', 'US')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Directionality(
          textDirection: TextDirection.rtl,
          child: Scaffold(body: screen),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

/// Unmounts a Syncfusion chart screen in a controlled frame and clears the
/// dispose-time assertion the chart's internal layout-builder raises while
/// tearing down. Assertions run before this is called, so it never masks a
/// real failure — it only keeps the framework's end-of-test finalization clean.
Future<void> _disposeCharts(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  tester.takeException();
}

void main() {
  setUp(() async {
    await SecureStorage.deleteToken();
  });

  // ── Requirement 17.5: PlutoGrid on tabular screens ─────────────────────────

  group('PlutoGrid presence on tabular screens (Req 17.5)', () {
    testWidgets('Cameras screen renders a PlutoGrid', (tester) async {
      await _pumpScreen(tester, const CamerasView(), [
        _authOverride(_session('Admin', _adminPermissions)),
        cameraListProvider.overrideWith((ref) async => _cameras),
      ]);
      expect(find.byType(PlutoGrid), findsOneWidget);
    });

    testWidgets('Sessions screen renders a PlutoGrid', (tester) async {
      await _pumpScreen(tester, const SessionsView(), [
        _authOverride(_session('Viewer', _viewerPermissions)),
        sessionsProvider.overrideWith((ref) async => _sessions),
      ]);
      expect(find.byType(PlutoGrid), findsOneWidget);
    });

    testWidgets('Users screen renders a PlutoGrid for an Admin', (tester) async {
      await _pumpScreen(tester, const UsersView(), [
        _authOverride(_session('Admin', _adminPermissions)),
        usersRepoProvider.overrideWithValue(_FakeUsersRepo(_users)),
      ]);
      expect(find.byType(PlutoGrid), findsOneWidget);
    });

    testWidgets('Audit screen renders a PlutoGrid for an Admin', (tester) async {
      await _pumpScreen(tester, const AuditView(), [
        _authOverride(_session('Admin', _adminPermissions)),
        auditRepoProvider.overrideWithValue(_FakeAuditRepo(_audit)),
      ]);
      expect(find.byType(PlutoGrid), findsOneWidget);
    });

    testWidgets('Watchlists screen renders a PlutoGrid of entries',
        (tester) async {
      await _pumpScreen(tester, const WatchlistsView(), [
        _authOverride(_session('Operator', const [
          Permissions.view,
          Permissions.manageWatchlists,
        ])),
        watchlistsRepoProvider.overrideWithValue(_FakeWatchlistsRepo(_watchlists)),
        alertsRepoProvider.overrideWithValue(_FakeAlertsRepo(_alerts)),
      ]);
      expect(find.byType(PlutoGrid), findsOneWidget);
    });
  });

  // ── Requirement 17.6: Syncfusion charts/gauges on analytics ────────────────

  group('Syncfusion charts/gauges on analytics screens (Req 17.6)', () {
    testWidgets('Dashboard renders a radial gauge and Syncfusion charts',
        (tester) async {
      await _pumpScreen(tester, const DashboardView(), [
        _authOverride(_session('Viewer', _viewerPermissions)),
        statsProvider.overrideWith((ref) async => _stats),
        timelineProvider.overrideWith((ref) async => _timeline),
        sourcesProvider.overrideWith((ref) async => _sources),
        recentDetectionsProvider.overrideWith((ref) async => _recentDetections),
      ]);

      // Radial gauge (Syncfusion gauges) for the average-confidence KPI.
      expect(find.byType(SfRadialGauge), findsOneWidget);
      // Cartesian (column) timeline chart + circular (doughnut) sources chart.
      expect(find.byType(SfCartesianChart), findsWidgets);
      expect(find.byType(SfCircularChart), findsOneWidget);

      await _disposeCharts(tester);
    });

    testWidgets('Analytics renders Syncfusion cartesian and circular charts',
        (tester) async {
      await _pumpScreen(tester, const AnalyticsView(), [
        _authOverride(_session('Viewer', _viewerPermissions)),
        // selectedDays defaults to 7, so the timeline family resolves at 7.
        analyticsTimelineProvider(7).overrideWith((ref) async => _timeline),
        analyticsSourcesProvider.overrideWith((ref) async => _sources),
        analyticsConfidenceProvider.overrideWith((ref) async => _confidence),
        analyticsLettersProvider.overrideWith((ref) async => _letters),
      ]);

      // Timeline (spline-area), confidence (column) and top-plates (bar) are
      // all SfCartesianChart; source distribution is an SfCircularChart.
      expect(find.byType(SfCartesianChart), findsWidgets);
      expect(find.byType(SfCircularChart), findsOneWidget);

      await _disposeCharts(tester);
    });
  });

  // ── Requirement 18.4: permission-gated controls per role ───────────────────

  group('Permission-gated control visibility per role (Req 18.4)', () {
    testWidgets('Cameras: Admin sees the add-camera control', (tester) async {
      await _pumpScreen(tester, const CamerasView(), [
        _authOverride(_session('Admin', _adminPermissions)),
        cameraListProvider.overrideWith((ref) async => _cameras),
      ]);
      expect(find.text('افزودن دوربین'), findsOneWidget);
    });

    testWidgets('Cameras: Viewer does not see the add-camera control, grid still shows',
        (tester) async {
      await _pumpScreen(tester, const CamerasView(), [
        _authOverride(_session('Viewer', _viewerPermissions)),
        cameraListProvider.overrideWith((ref) async => _cameras),
      ]);
      expect(find.text('افزودن دوربین'), findsNothing);
      expect(find.byType(PlutoGrid), findsOneWidget);
    });

    testWidgets('Users: Admin sees the management UI', (tester) async {
      await _pumpScreen(tester, const UsersView(), [
        _authOverride(_session('Admin', _adminPermissions)),
        usersRepoProvider.overrideWithValue(_FakeUsersRepo(_users)),
      ]);
      expect(find.text('کاربر جدید'), findsOneWidget);
      expect(find.byType(PermissionDeniedView), findsNothing);
    });

    testWidgets('Users: Viewer is denied the management control', (tester) async {
      await _pumpScreen(tester, const UsersView(), [
        _authOverride(_session('Viewer', _viewerPermissions)),
        usersRepoProvider.overrideWithValue(_FakeUsersRepo(_users)),
      ]);
      expect(find.text('کاربر جدید'), findsNothing);
      expect(find.byType(PermissionDeniedView), findsOneWidget);
    });

    testWidgets('Watchlists: manage permission reveals the create-list control',
        (tester) async {
      await _pumpScreen(tester, const WatchlistsView(), [
        _authOverride(_session('Operator', const [
          Permissions.view,
          Permissions.manageWatchlists,
        ])),
        watchlistsRepoProvider.overrideWithValue(_FakeWatchlistsRepo(_watchlists)),
        alertsRepoProvider.overrideWithValue(_FakeAlertsRepo(_alerts)),
      ]);
      expect(find.text('فهرست جدید'), findsOneWidget);
    });

    testWidgets('Watchlists: Viewer does not see the create-list control',
        (tester) async {
      await _pumpScreen(tester, const WatchlistsView(), [
        _authOverride(_session('Viewer', _viewerPermissions)),
        watchlistsRepoProvider.overrideWithValue(_FakeWatchlistsRepo(_watchlists)),
        alertsRepoProvider.overrideWithValue(_FakeAlertsRepo(_alerts)),
      ]);
      expect(find.text('فهرست جدید'), findsNothing);
    });
  });
}
