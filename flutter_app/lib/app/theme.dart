// lib/app/theme.dart
// App theme: light and dark ThemeData with Vazirmatn font.
// Requirements: 1.1, 1.6

import 'package:flutter/material.dart';

class AppTheme {
  AppTheme._();

  static ThemeData get light => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1565C0),
          brightness: Brightness.light,
        ),
        fontFamily: 'Vazirmatn',
        visualDensity: VisualDensity.adaptivePlatformDensity,
      );

  static ThemeData get dark => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1565C0),
          brightness: Brightness.dark,
        ),
        fontFamily: 'Vazirmatn',
        visualDensity: VisualDensity.adaptivePlatformDensity,
      );
}
