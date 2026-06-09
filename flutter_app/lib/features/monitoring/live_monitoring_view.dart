// lib/features/monitoring/live_monitoring_view.dart
// Live Monitoring screen showing annotated MJPEG camera feeds. Access is gated
// behind the `view` (view-streams) permission; the multi-camera MJPEG monitor
// itself is reused from the cameras feature.
// Requirements: 6.1, 6.2, 6.4, 18.4

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../shared/widgets/permission_gate.dart';
import '../cameras/camera_live_monitor.dart';

class LiveMonitoringView extends ConsumerWidget {
  const LiveMonitoringView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Viewing live streams requires the base `view` permission. Roles without
    // it see a denied view instead of the monitor.
    return const PermissionGate(
      permission: Permissions.view,
      fallback: Scaffold(
        backgroundColor: Colors.transparent,
        body: PermissionDeniedView(
          message: 'شما اجازه مشاهده پخش زنده دوربین‌ها را ندارید.',
        ),
      ),
      child: CameraLiveMonitor(),
    );
  }
}
