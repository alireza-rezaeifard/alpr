# Data Models Documentation

This directory contains immutable Dart models for the ANPR System redesign, mirroring the backend API response envelopes.

## Implemented Models

### Authentication & Authorization

#### `user_auth.dart` - UserAuth
Authentication response model containing session token and user permissions.
- **Fields**: token, role, expiresAt, permissions
- **Utilities**: isExpired, hasPermission(), isAdmin, isOperator, isViewer
- **Validates**: Requirements 1.1, 2.x

#### `user_model.dart` - UserModel
User account view model for user management.
- **Fields**: id, username, role, disabled, createdAt
- **Utilities**: isEnabled, isAdmin, isOperator, isViewer
- **Validates**: Requirements 2.x

### Licensing

#### `license_status.dart` - LicenseStatus
License activation state and camera limits.
- **Fields**: active, expiry, cameraLimit, configuredCameras
- **Utilities**: isExpired, isValid, isAtLimit, remainingSlots, daysUntilExpiry
- **Validates**: Requirements 3.5

### Watchlists & Alerts

#### `watchlist_entry.dart` - WatchlistEntry
A single plate entry within a watchlist.
- **Fields**: id, watchlistId, plateValue, label, reason, createdAt
- **Utilities**: hasLabel, hasReason
- **Validates**: Requirements 12.2

#### `watchlist.dart` - Watchlist
A watchlist with its plate entries.
- **Fields**: id, name, listType, createdAt, entries
- **Utilities**: isBlocklist, isAllowlist, entryCount, isEmpty, isNotEmpty
- **Validates**: Requirements 12.1

#### `alert.dart` - Alert
An alert raised when a detection matches a watchlist entry.
- **Fields**: id, detectionId, entryId, plateValue, createdAt
- **Utilities**: timestamp, timeSinceCreated
- **Validates**: Requirements 12.4

### Audit & Compliance

#### `audit_entry.dart` - AuditEntry
An append-only audit log entry recording security-relevant actions.
- **Fields**: id, username, action, resource, outcome, timestamp
- **Utilities**: wasSuccessful, wasFailed, timestampDate, hasUsername, hasResource
- **Validates**: Requirements 15.2

### Persian Formatting

#### `persian_format.dart` - PersianFormat
Helper class for converting numbers, dates, and times to Persian locale format.

**Methods:**
- `toPersianDigits(String)` - Convert Latin digits (0-9) to Persian (۰-۹)
- `toLatinDigits(String)` - Convert Persian digits to Latin
- `number(int)` - Format integer with Persian digits
- `decimal(double, {decimalPlaces})` - Format decimal with Persian digits
- `numberWithSeparator(num, {separator})` - Format with thousand separators
- `date(DateTime)` - Format as YYYY/MM/DD with Persian digits
- `time(DateTime, {includeSeconds})` - Format as HH:MM:SS with Persian digits
- `dateTime(DateTime, {includeSeconds})` - Format date and time
- `dateFromIso(String?)` - Parse and format ISO date string
- `timeFromIso(String?, {includeSeconds})` - Parse and format ISO time string
- `dateTimeFromIso(String?, {includeSeconds})` - Parse and format ISO datetime string
- `duration(Duration)` - Format duration in Persian (e.g., "۲ ساعت و ۱۵ دقیقه")
- `confidence(double)` - Format confidence as percentage (e.g., "۹۵٪")
- `relativeTime(DateTime)` - Format relative time (e.g., "۵ دقیقه پیش")
- `relativeTimeFromIso(String?)` - Format relative time from ISO string

**Validates**: Requirements 17.4

## Model Characteristics

All models are implemented as **immutable classes** with:

1. **const constructors** - Compile-time constant instances
2. **fromJson factory** - JSON deserialization from backend responses
3. **toJson method** - JSON serialization for API requests
4. **copyWith method** - Create modified copies while maintaining immutability
5. **Utility getters** - Computed properties for common operations

## Testing

Comprehensive unit tests are located at `test/data/models/models_test.dart`:
- ✅ JSON serialization/deserialization round-trips
- ✅ Utility method correctness
- ✅ Persian digit conversion bidirectionality
- ✅ Date/time formatting
- ✅ Relative time calculations
- ✅ Edge cases and null handling

Run tests with:
```bash
flutter test test/data/models/models_test.dart
```

**Test Results**: 33/33 tests passing ✅

## Usage Examples

### Authentication
```dart
// Parse login response
final auth = UserAuth.fromJson(response.data);

// Check permissions
if (auth.hasPermission('manage_cameras')) {
  // Show camera management UI
}

// Check if expired
if (auth.isExpired) {
  // Redirect to login
}
```

### License Status
```dart
// Parse license status
final license = LicenseStatus.fromJson(response.data);

// Check validity
if (!license.isValid) {
  // Show license warning
}

// Check remaining slots
print('Cameras available: ${license.remainingSlots}');
```

### Watchlist Management
```dart
// Parse watchlist with entries
final watchlist = Watchlist.fromJson(response.data);

// Check type
if (watchlist.isBlocklist) {
  // Display as blocklist
}

// Iterate entries
for (final entry in watchlist.entries) {
  print('${entry.plateValue}: ${entry.label ?? "No label"}');
}
```

### Persian Formatting
```dart
// Format numbers
PersianFormat.number(123) // "۱۲۳"
PersianFormat.numberWithSeparator(1234567) // "۱٬۲۳۴٬۵۶۷"

// Format dates
final now = DateTime.now();
PersianFormat.date(now) // "۲۰۲۵/۰۱/۱۵"
PersianFormat.time(now) // "۱۴:۳۰:۴۵"

// Format from ISO strings
PersianFormat.dateFromIso('2025-01-15T14:30:45Z') // "۲۰۲۵/۰۱/۱۵"

// Relative time
PersianFormat.relativeTime(fiveMinutesAgo) // "۵ دقیقه پیش"

// Confidence scores
PersianFormat.confidence(0.95) // "۹۵٪"
```

### Audit Logging
```dart
// Parse audit entry
final entry = AuditEntry.fromJson(response.data);

// Check outcome
if (entry.wasSuccessful) {
  // Show success indicator
}

// Format timestamp
final timestamp = PersianFormat.relativeTimeFromIso(entry.timestamp);
print('Action performed: $timestamp');
```

## Integration with Backend

All models match the Pydantic schemas defined in `schemas.py`:
- `LoginResponse` → `UserAuth`
- `UserView` → `UserModel`
- `LicenseStatus` → `LicenseStatus`
- `WatchlistView` → `Watchlist`
- `WatchlistEntryView` → `WatchlistEntry`
- `AlertView` → `Alert`
- `AuditEntryView` → `AuditEntry`

## Dependencies

- `intl: ^0.19.0` - Used by `PersianFormat` for number formatting

## Next Steps

These models will be used by:
1. **Repositories** (`lib/data/repositories/`) - API client wrappers
2. **Controllers** (`lib/features/*/controllers/`) - Riverpod state management
3. **UI Screens** (`lib/features/*/presentation/`) - Display formatted data

---

**Implementation Status**: ✅ Complete
**Task**: 19.2 - Implement Dart models and PersianFormat helper
**Requirements**: 17.4
