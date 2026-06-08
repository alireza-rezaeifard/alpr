// lib/shared/app_icons.dart
// Icon constants mapped from Lucide-style names to Material Icons.
// This avoids the lucide_icons package incompatibility while maintaining
// the same icon API across the app.

import 'package:flutter/material.dart';

/// Clean icon set using Material Symbols / Icons with Lucide-like naming.
class AppIcons {
  AppIcons._();

  // Navigation
  static const layoutDashboard = Icons.dashboard_outlined;
  static const history = Icons.history;
  static const barChart3 = Icons.bar_chart_rounded;
  static const layers = Icons.layers_outlined;
  static const scanLine = Icons.document_scanner_outlined;
  static const camera = Icons.videocam_outlined;

  // Actions
  static const search = Icons.search;
  static const plus = Icons.add;
  static const play = Icons.play_arrow_rounded;
  static const square = Icons.stop_rounded;
  static const refreshCw = Icons.refresh;
  static const upload = Icons.upload_file_outlined;
  static const edit2 = Icons.edit_outlined;
  static const trash2 = Icons.delete_outline;
  static const chevronLeft = Icons.chevron_left;
  static const chevronRight = Icons.chevron_right;
  static const loader2 = Icons.sync;
  static const settings = Icons.settings_outlined;
  static const settings2 = Icons.tune;

  // Status / Feedback
  static const alertCircle = Icons.error_outline;
  static const checkCircle = Icons.check_circle_outline;
  static const xCircle = Icons.cancel_outlined;
  static const helpCircle = Icons.help_outline;
  static const circle = Icons.circle_outlined;
  static const wifi = Icons.wifi;
  static const wifiOff = Icons.wifi_off;

  // Content
  static const creditCard = Icons.credit_card;
  static const image = Icons.image_outlined;
  static const imageOff = Icons.broken_image_outlined;
  static const video = Icons.video_file_outlined;
  static const file = Icons.insert_drive_file_outlined;
  static const monitor = Icons.monitor_outlined;
  static const radar = Icons.radar;
  static const radio = Icons.sensors;
  static const clock = Icons.access_time;
  static const timer = Icons.timer_outlined;
  static const fingerprint = Icons.fingerprint;

  // Charts / Analytics
  static const trendingUp = Icons.trending_up;
  static const pieChart = Icons.pie_chart_outline;
  static const gauge = Icons.speed;
  static const trophy = Icons.emoji_events_outlined;
  static const target = Icons.gps_fixed;

  // Layout
  static const panelLeftOpen = Icons.menu;
  static const panelLeftClose = Icons.menu_open;
}
