// lib/app/app.dart
// FluentApp.router entry point with Persian RTL support and Fluent design.
// Requirements: 17.1, 17.2, 17.3

import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'router.dart';
import 'theme.dart';

class PlprApp extends ConsumerWidget {
  const PlprApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    return Directionality(
      textDirection: TextDirection.rtl,
      child: FluentApp.router(
        title: 'سامانه تشخیص پلاک خودرو',
        theme: AppTheme.fluentDark,
        locale: const Locale('fa', 'IR'),
        supportedLocales: const [
          Locale('fa', 'IR'),
          Locale('en', 'US'),
        ],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        routerConfig: router,
        debugShowCheckedModeBanner: false,
      ),
    );
  }
}
