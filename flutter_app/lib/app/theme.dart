// lib/app/theme.dart
// Fluent Design theme for Persian ANPR system with Vazirmatn font.
// Requirements: 17.3

import 'package:fluent_ui/fluent_ui.dart';

class AppTheme {
  AppTheme._();

  // ── Color palette (Fluent Design inspired) ─────────────────────────────
  static const _background = Color(0xFF1C1C1C);
  static const _surface = Color(0xFF2C2C2C);
  static const _surfaceVariant = Color(0xFF3C3C3C);
  static const _border = Color(0xFF4C4C4C);
  static const _muted = Color(0xFF9CA3AF);
  static const _foreground = Color(0xFFFAFAFA);
  static const _accentBlue = Color(0xFF0078D4);
  static const _accentBlueHover = Color(0xFF106EBE);
  static const _destructive = Color(0xFFE81123);
  static const _success = Color(0xFF10B981);
  static const _warning = Color(0xFFF59E0B);

  static FluentThemeData get fluentDark => FluentThemeData(
        brightness: Brightness.dark,
        accentColor: AccentColor.swatch({
          'normal': _accentBlue,
          'dark': _accentBlueHover,
          'light': const Color(0xFF4CC2FF),
        }),
        scaffoldBackgroundColor: _background,
        cardColor: _surface,
        fontFamily: 'Vazirmatn',
        typography: Typography.fromBrightness(
          brightness: Brightness.dark,
        ).apply(
              fontFamily: 'Vazirmatn',
              displayColor: _foreground,
            ),
        visualDensity: VisualDensity.adaptivePlatformDensity,
        navigationPaneTheme: NavigationPaneThemeData(
          backgroundColor: _surface,
          overlayBackgroundColor: _surfaceVariant,
          highlightColor: _accentBlue.withValues(alpha: 0.1),
          animationDuration: const Duration(milliseconds: 200),
        ),
      );

  static FluentThemeData get fluentLight => FluentThemeData(
        brightness: Brightness.light,
        accentColor: AccentColor.swatch({
          'normal': _accentBlue,
          'dark': _accentBlueHover,
          'light': const Color(0xFF4CC2FF),
        }),
        fontFamily: 'Vazirmatn',
        visualDensity: VisualDensity.adaptivePlatformDensity,
      );

  // Color utilities for use in widgets
  static const destructive = _destructive;
  static const success = _success;
  static const warning = _warning;
  static const muted = _muted;
  static const accentBlue = _accentBlue;
}
