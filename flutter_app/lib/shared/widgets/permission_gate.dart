// lib/shared/widgets/permission_gate.dart
// Permission-aware widgets that hide or disable controls whose action the
// current role lacks, based on the permission set returned at login.
// Requirements: 18.4, 2.x

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/controllers/auth_controller.dart';
import '../app_icons.dart';

/// Canonical backend permission strings (mirrors `Permission` in the backend).
class Permissions {
  Permissions._();

  static const String view = 'view';
  static const String manageCameras = 'manage_cameras';
  static const String runDetection = 'run_detection';
  static const String manageWatchlists = 'manage_watchlists';
  static const String manageUsers = 'manage_users';
  static const String manageRoles = 'manage_roles';
  static const String manageLicenses = 'manage_licenses';
  static const String manageConfig = 'manage_config';
  static const String viewAudit = 'view_audit';
}

/// Returns true when the currently authenticated user holds [permission].
///
/// Admin holds all permissions via the permission set returned at login, so a
/// single membership check is sufficient here.
bool currentUserHasPermission(WidgetRef ref, String permission) {
  final auth = ref.watch(currentSessionProvider);
  return auth?.hasPermission(permission) ?? false;
}

/// Hides [child] entirely when the current role lacks [permission].
///
/// When [fallback] is provided it is shown instead of an empty box, which is
/// useful for rendering a disabled placeholder.
class PermissionGate extends ConsumerWidget {
  final String permission;
  final Widget child;
  final Widget? fallback;

  const PermissionGate({
    super.key,
    required this.permission,
    required this.child,
    this.fallback,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (currentUserHasPermission(ref, permission)) return child;
    return fallback ?? const SizedBox.shrink();
  }
}

/// Full-screen message shown when a user opens a screen whose action their
/// role does not permit.
class PermissionDeniedView extends StatelessWidget {
  final String message;

  const PermissionDeniedView({
    super.key,
    this.message = 'شما به این بخش دسترسی ندارید.',
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(AppIcons.xCircle, size: 56, color: Colors.white.withOpacity(0.2)),
          const SizedBox(height: 16),
          Text(
            'دسترسی محدود شده',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: Colors.white.withOpacity(0.8),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            message,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: Colors.white.withOpacity(0.5)),
          ),
        ],
      ),
    );
  }
}
