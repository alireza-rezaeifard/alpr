# Core Module - Authentication & API Client

This module provides the core infrastructure for API communication and authentication in the PLPR Flutter client.

## Components

### 1. API Client (`api_client.dart`)
Singleton Dio instance configured for the PLPR backend.

**Features:**
- Base URL configuration from `RuntimeConfig`
- Default 10-second timeouts
- Token attachment via `AuthInterceptor`
- Error mapping via `_ErrorMappingInterceptor`
- Custom timeout options for different request types

**Usage:**
```dart
final dio = ApiClient.instance;
final response = await dio.get('/cameras');

// With custom timeout
final response = await dio.get(
  '/detections',
  options: ApiClient.withTimeout(ApiClient.uploadTimeout),
);
```

### 2. Auth Interceptor (`auth_interceptor.dart`)
Dio interceptor that handles Bearer token attachment and 401 responses.

**Features:**
- Automatically attaches stored token to all requests
- On 401 response: clears token and sets reauthentication flag
- Works seamlessly with the router redirect guard

**How it works:**
1. Before request: reads token from storage and adds `Authorization: Bearer <token>` header
2. On 401 error: clears stored token, sets `needsReauthentication` flag
3. Router checks flag and redirects to login

### 3. Secure Storage (`secure_storage.dart`)
Simple in-memory token storage for Windows/Web platforms.

**API:**
```dart
await SecureStorage.writeToken(token);
final token = await SecureStorage.readToken();
await SecureStorage.deleteToken();
final hasToken = await SecureStorage.hasToken();
```

**Note:** For production native apps, replace with `flutter_secure_storage`.

### 4. Auth Provider (`auth_provider.dart`)
Riverpod providers for authentication state management.

**Providers:**

- `authStateProvider` - Main auth state (UserAuth | null)
- `isAuthenticatedProvider` - Boolean authentication status
- `currentAuthProvider` - Current UserAuth object
- `hasPermissionProvider(permission)` - Check specific permission

**Usage:**
```dart
// In a widget
class MyWidget extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isAuth = ref.watch(isAuthenticatedProvider);
    final auth = ref.watch(currentAuthProvider);
    
    if (!isAuth) return LoginScreen();
    
    return Text('Welcome, ${auth?.role}');
  }
}

// Login
final authNotifier = ref.read(authStateProvider.notifier);
await authNotifier.login(userAuth);

// Logout
await authNotifier.logout();

// Check permission
final canManageCameras = ref.watch(hasPermissionProvider('manage_cameras'));
```

### 5. Session Provider (`session_provider.dart`)
Providers for session information and expiry tracking.

**Providers:**

- `sessionInfoProvider` - SessionInfo with expiry details
- `isSessionValidProvider` - Boolean validity check
- `isSessionExpiringSoonProvider` - True if < 5 minutes remaining
- `sessionTimeRemainingProvider` - Duration until expiry

**Usage:**
```dart
// Check if session is expiring soon
final isExpiringSoon = ref.watch(isSessionExpiringSoonProvider);
if (isExpiringSoon) {
  showSnackBar('Session expiring soon. Please save your work.');
}

// Display time remaining
final timeRemaining = ref.watch(sessionTimeRemainingProvider);
Text('Session expires in ${timeRemaining.inMinutes} minutes');
```

## Authentication Flow

### Login Flow
1. User submits credentials to `AuthRepo.login()`
2. Backend validates and returns `UserAuth` with token
3. `AuthState.login()` stores token in `SecureStorage`
4. `AuthState` updates with new auth
5. Router redirect guard allows access to protected routes

### 401 Response Flow
1. API call receives 401 from backend
2. `AuthInterceptor.onError()` detects 401
3. Token is cleared from `SecureStorage`
4. `AuthInterceptor.needsReauthentication` flag is set
5. Router redirect guard checks flag on next navigation
6. User is redirected to `/login`

### Logout Flow
1. `AuthState.logout()` is called
2. `AuthRepo.logout()` invalidates token on backend
3. Token is cleared from `SecureStorage`
4. `AuthState` is set to null
5. Router redirect guard redirects to `/login`

## Integration with Router

The router (`app/router.dart`) should check:

```dart
redirect: (context, state) {
  final container = ProviderContainer();
  final isAuth = container.read(isAuthenticatedProvider);
  
  // Check 401 flag
  if (AuthInterceptor.needsReauthentication) {
    AuthInterceptor.clearReauthFlag();
    return '/login';
  }
  
  // Check auth state
  if (!isAuth && state.location != '/login') {
    return '/login';
  }
  
  if (isAuth && state.location == '/login') {
    return '/dashboard';
  }
  
  return null; // No redirect
}
```

## Testing

Comprehensive tests are provided:

- `test/core/auth_interceptor_test.dart` - Token attachment and 401 handling
- `test/core/auth_provider_test.dart` - Auth and session provider behavior

Run tests:
```bash
flutter test test/core/
```

## Requirements Coverage

- **Requirement 18.2**: Session token stored and attached to requests ✓
- **Requirement 18.3**: 401 response clears token and triggers redirect ✓

## Future Enhancements

1. **Persistent Storage**: Replace in-memory storage with `flutter_secure_storage` or `shared_preferences` for session persistence across app restarts
2. **Token Refresh**: Add automatic token refresh before expiry
3. **Biometric Auth**: Add fingerprint/face ID support
4. **Multi-account**: Support multiple user profiles
