import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_app/data/models/user_auth.dart';
import 'package:flutter_app/data/models/user_model.dart';
import 'package:flutter_app/data/models/license_status.dart';
import 'package:flutter_app/data/models/watchlist.dart';
import 'package:flutter_app/data/models/watchlist_entry.dart';
import 'package:flutter_app/data/models/alert.dart';
import 'package:flutter_app/data/models/audit_entry.dart';
import 'package:flutter_app/data/models/persian_format.dart';

void main() {
  group('UserAuth Model', () {
    test('fromJson creates valid UserAuth', () {
      final json = {
        'token': 'abc123',
        'role': 'Admin',
        'expires_at': '2025-12-31T23:59:59Z',
        'permissions': ['manage_users', 'manage_cameras'],
      };

      final userAuth = UserAuth.fromJson(json);

      expect(userAuth.token, 'abc123');
      expect(userAuth.role, 'Admin');
      expect(userAuth.expiresAt, '2025-12-31T23:59:59Z');
      expect(userAuth.permissions, ['manage_users', 'manage_cameras']);
    });

    test('toJson serializes correctly', () {
      final userAuth = UserAuth(
        token: 'xyz789',
        role: 'Operator',
        expiresAt: '2025-06-30T12:00:00Z',
        permissions: ['manage_cameras', 'run_detection'],
      );

      final json = userAuth.toJson();

      expect(json['token'], 'xyz789');
      expect(json['role'], 'Operator');
      expect(json['expires_at'], '2025-06-30T12:00:00Z');
      expect(json['permissions'], ['manage_cameras', 'run_detection']);
    });

    test('hasPermission checks correctly', () {
      final userAuth = UserAuth(
        token: 'token',
        role: 'Admin',
        expiresAt: '2025-12-31T23:59:59Z',
        permissions: ['manage_users'],
      );

      expect(userAuth.hasPermission('manage_users'), true);
      expect(userAuth.hasPermission('view'), false);
    });

    test('role checks work correctly', () {
      final admin = UserAuth(
        token: 'token',
        role: 'Admin',
        expiresAt: '2025-12-31T23:59:59Z',
        permissions: [],
      );

      expect(admin.isAdmin, true);
      expect(admin.isOperator, false);
      expect(admin.isViewer, false);
    });
  });

  group('UserModel', () {
    test('fromJson creates valid UserModel', () {
      final json = {
        'id': 1,
        'username': 'admin',
        'role': 'Admin',
        'disabled': false,
        'created_at': '2025-01-01T00:00:00Z',
      };

      final user = UserModel.fromJson(json);

      expect(user.id, 1);
      expect(user.username, 'admin');
      expect(user.role, 'Admin');
      expect(user.disabled, false);
      expect(user.isEnabled, true);
    });

    test('toJson serializes correctly', () {
      final user = UserModel(
        id: 2,
        username: 'operator1',
        role: 'Operator',
        disabled: true,
        createdAt: '2025-01-15T10:30:00Z',
      );

      final json = user.toJson();

      expect(json['id'], 2);
      expect(json['username'], 'operator1');
      expect(json['disabled'], true);
    });
  });

  group('LicenseStatus Model', () {
    test('fromJson creates valid LicenseStatus', () {
      final json = {
        'active': true,
        'expiry': '2025-12-31',
        'camera_limit': 10,
        'configured_cameras': 5,
      };

      final license = LicenseStatus.fromJson(json);

      expect(license.active, true);
      expect(license.expiry, '2025-12-31');
      expect(license.cameraLimit, 10);
      expect(license.configuredCameras, 5);
    });

    test('isValid checks active and expiry', () {
      final validLicense = LicenseStatus(
        active: true,
        expiry: '2099-12-31',
        cameraLimit: 10,
        configuredCameras: 5,
      );

      expect(validLicense.isValid, true);
    });

    test('remainingSlots calculates correctly', () {
      final license = LicenseStatus(
        active: true,
        expiry: '2099-12-31',
        cameraLimit: 10,
        configuredCameras: 7,
      );

      expect(license.remainingSlots, 3);
    });

    test('isAtLimit checks correctly', () {
      final atLimit = LicenseStatus(
        active: true,
        expiry: '2099-12-31',
        cameraLimit: 5,
        configuredCameras: 5,
      );

      expect(atLimit.isAtLimit, true);
    });
  });

  group('WatchlistEntry Model', () {
    test('fromJson creates valid WatchlistEntry', () {
      final json = {
        'id': 1,
        'watchlist_id': 10,
        'plate_value': '12ص345',
        'label': 'Suspicious',
        'reason': 'Wanted vehicle',
        'created_at': '2025-01-01T12:00:00Z',
      };

      final entry = WatchlistEntry.fromJson(json);

      expect(entry.id, 1);
      expect(entry.watchlistId, 10);
      expect(entry.plateValue, '12ص345');
      expect(entry.label, 'Suspicious');
      expect(entry.hasLabel, true);
      expect(entry.hasReason, true);
    });

    test('toJson serializes correctly', () {
      final entry = WatchlistEntry(
        id: 2,
        watchlistId: 20,
        plateValue: '23ب456',
        label: null,
        reason: null,
        createdAt: '2025-01-02T14:30:00Z',
      );

      final json = entry.toJson();

      expect(json['id'], 2);
      expect(json['plate_value'], '23ب456');
      expect(json['label'], null);
    });
  });

  group('Watchlist Model', () {
    test('fromJson creates valid Watchlist with entries', () {
      final json = {
        'id': 1,
        'name': 'Blocklist',
        'list_type': 'blocklist',
        'created_at': '2025-01-01T00:00:00Z',
        'entries': [
          {
            'id': 1,
            'watchlist_id': 1,
            'plate_value': '12ص345',
            'label': 'Test',
            'reason': 'Testing',
            'created_at': '2025-01-01T12:00:00Z',
          }
        ],
      };

      final watchlist = Watchlist.fromJson(json);

      expect(watchlist.id, 1);
      expect(watchlist.name, 'Blocklist');
      expect(watchlist.isBlocklist, true);
      expect(watchlist.entries.length, 1);
      expect(watchlist.entryCount, 1);
    });

    test('isEmpty and isNotEmpty work correctly', () {
      final empty = Watchlist(
        id: 1,
        name: 'Empty List',
        listType: 'allowlist',
        createdAt: '2025-01-01T00:00:00Z',
      );

      expect(empty.isEmpty, true);
      expect(empty.isNotEmpty, false);
    });
  });

  group('Alert Model', () {
    test('fromJson creates valid Alert', () {
      final json = {
        'id': 1,
        'detection_id': 100,
        'entry_id': 50,
        'plate_value': '12ص345',
        'created_at': '2025-01-01T12:00:00Z',
      };

      final alert = Alert.fromJson(json);

      expect(alert.id, 1);
      expect(alert.detectionId, 100);
      expect(alert.entryId, 50);
      expect(alert.plateValue, '12ص345');
    });

    test('timestamp parsing works', () {
      final alert = Alert(
        id: 1,
        detectionId: 100,
        entryId: 50,
        plateValue: '12ص345',
        createdAt: '2025-01-01T12:00:00Z',
      );

      expect(alert.timestamp, isNotNull);
      expect(alert.timeSinceCreated, isNotNull);
    });
  });

  group('AuditEntry Model', () {
    test('fromJson creates valid AuditEntry', () {
      final json = {
        'id': 1,
        'username': 'admin',
        'action': 'login',
        'resource': 'auth',
        'outcome': 'success',
        'timestamp': '2025-01-01T12:00:00Z',
      };

      final entry = AuditEntry.fromJson(json);

      expect(entry.id, 1);
      expect(entry.username, 'admin');
      expect(entry.action, 'login');
      expect(entry.wasSuccessful, true);
    });

    test('outcome checks work correctly', () {
      final success = AuditEntry(
        id: 1,
        action: 'create',
        outcome: 'success',
        timestamp: '2025-01-01T12:00:00Z',
      );

      final failed = AuditEntry(
        id: 2,
        action: 'delete',
        outcome: 'failed',
        timestamp: '2025-01-01T12:05:00Z',
      );

      expect(success.wasSuccessful, true);
      expect(success.wasFailed, false);
      expect(failed.wasSuccessful, false);
      expect(failed.wasFailed, true);
    });
  });

  group('PersianFormat Helper', () {
    test('toPersianDigits converts correctly', () {
      expect(PersianFormat.toPersianDigits('0123456789'), '۰۱۲۳۴۵۶۷۸۹');
      expect(PersianFormat.toPersianDigits('12ص345'), '۱۲ص۳۴۵');
    });

    test('toLatinDigits converts correctly', () {
      expect(PersianFormat.toLatinDigits('۰۱۲۳۴۵۶۷۸۹'), '0123456789');
      expect(PersianFormat.toLatinDigits('۱۲ص۳۴۵'), '12ص345');
    });

    test('number formats integers with Persian digits', () {
      expect(PersianFormat.number(123), '۱۲۳');
      expect(PersianFormat.number(0), '۰');
    });

    test('decimal formats doubles with Persian digits', () {
      expect(PersianFormat.decimal(123.45, decimalPlaces: 2), '۱۲۳.۴۵');
    });

    test('date formats DateTime correctly', () {
      final dt = DateTime(2025, 1, 15);
      expect(PersianFormat.date(dt), '۲۰۲۵/۰۱/۱۵');
    });

    test('time formats DateTime correctly', () {
      final dt = DateTime(2025, 1, 15, 14, 30, 45);
      expect(PersianFormat.time(dt), '۱۴:۳۰:۴۵');
      expect(PersianFormat.time(dt, includeSeconds: false), '۱۴:۳۰');
    });

    test('dateTime formats DateTime correctly', () {
      final dt = DateTime(2025, 1, 15, 14, 30, 45);
      expect(PersianFormat.dateTime(dt), '۲۰۲۵/۰۱/۱۵ ۱۴:۳۰:۴۵');
    });

    test('dateFromIso parses and formats ISO strings', () {
      expect(PersianFormat.dateFromIso('2025-01-15T14:30:45Z'), '۲۰۲۵/۰۱/۱۵');
      expect(PersianFormat.dateFromIso(null), null);
      expect(PersianFormat.dateFromIso(''), null);
    });

    test('confidence formats percentages', () {
      expect(PersianFormat.confidence(0.95), '۹۵٪');
      expect(PersianFormat.confidence(0.5), '۵۰٪');
    });

    test('duration formats correctly', () {
      expect(PersianFormat.duration(Duration(seconds: 30)), '۳۰ ثانیه');
      expect(PersianFormat.duration(Duration(minutes: 5)), '۵ دقیقه');
      expect(
          PersianFormat.duration(Duration(hours: 2, minutes: 15)),
          '۲ ساعت و ۱۵ دقیقه');
    });

    test('relativeTime formats correctly', () {
      final now = DateTime.now();
      final fiveMinutesAgo = now.subtract(Duration(minutes: 5));
      final result = PersianFormat.relativeTime(fiveMinutesAgo);
      expect(result, '۵ دقیقه پیش');
    });

    test('numberWithSeparator formats with thousand separators', () {
      expect(PersianFormat.numberWithSeparator(1234567), '۱٬۲۳۴٬۵۶۷');
    });
  });

  group('Model Round-trips', () {
    test('UserAuth serialization round-trip', () {
      final original = UserAuth(
        token: 'test_token',
        role: 'Admin',
        expiresAt: '2025-12-31T23:59:59Z',
        permissions: ['manage_users', 'view'],
      );

      final json = original.toJson();
      final restored = UserAuth.fromJson(json);

      expect(restored.token, original.token);
      expect(restored.role, original.role);
      expect(restored.expiresAt, original.expiresAt);
      expect(restored.permissions, original.permissions);
    });

    test('LicenseStatus serialization round-trip', () {
      final original = LicenseStatus(
        active: true,
        expiry: '2025-12-31',
        cameraLimit: 20,
        configuredCameras: 10,
      );

      final json = original.toJson();
      final restored = LicenseStatus.fromJson(json);

      expect(restored.active, original.active);
      expect(restored.expiry, original.expiry);
      expect(restored.cameraLimit, original.cameraLimit);
      expect(restored.configuredCameras, original.configuredCameras);
    });

    test('Watchlist with entries serialization round-trip', () {
      final original = Watchlist(
        id: 1,
        name: 'Test List',
        listType: 'blocklist',
        createdAt: '2025-01-01T00:00:00Z',
        entries: [
          WatchlistEntry(
            id: 1,
            watchlistId: 1,
            plateValue: '12ص345',
            label: 'Test',
            reason: 'Testing',
            createdAt: '2025-01-01T12:00:00Z',
          ),
        ],
      );

      final json = original.toJson();
      final restored = Watchlist.fromJson(json);

      expect(restored.id, original.id);
      expect(restored.name, original.name);
      expect(restored.entries.length, original.entries.length);
      expect(restored.entries[0].plateValue, original.entries[0].plateValue);
    });
  });
}
