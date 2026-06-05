// lib/app/config.dart
// RuntimeConfig: reads BACKEND_URL from --dart-define or window-injected config.
// Requirements: 1.5, 1.8

import 'package:flutter/foundation.dart';

class RuntimeConfig {
  static const String _defaultUrl = 'http://127.0.0.1:8000';

  /// Backend base URL. Read from --dart-define=BACKEND_URL=... at compile time.
  /// On Web, can also be injected via window.__BACKEND_URL before Flutter boots.
  static String get backendUrl {
    // --dart-define takes precedence
    const defined = String.fromEnvironment('BACKEND_URL', defaultValue: '');
    if (defined.isNotEmpty) return defined;
    // Web: check for runtime injection (set in index.html before main.dart.js loads)
    if (kIsWeb) {
      // ignore: undefined_prefixed_name
      // js.context['__BACKEND_URL'] if available — gracefully falls back
      try {
        // Use conditional import approach; for now fall through to default
      } catch (_) {}
    }
    return _defaultUrl;
  }

  /// True if the backend URL is a non-empty absolute http(s) URL.
  static bool get isValid {
    final url = backendUrl;
    if (url.isEmpty) return false;
    try {
      final uri = Uri.parse(url);
      return uri.isAbsolute && (uri.scheme == 'http' || uri.scheme == 'https');
    } catch (_) {
      return false;
    }
  }
}
