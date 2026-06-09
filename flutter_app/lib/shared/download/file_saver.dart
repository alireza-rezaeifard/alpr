// lib/shared/download/file_saver.dart
// Cross-platform "save bytes to a file" helper used by the history export
// button. The concrete implementation is selected at compile time: a browser
// download on web, a native save dialog on desktop.

import 'file_saver_stub.dart'
    if (dart.library.io) 'file_saver_io.dart'
    if (dart.library.js_interop) 'file_saver_web.dart' as impl;

/// Saves [bytes] under a suggested [fileName].
///
/// Returns a human-readable destination (a file path on desktop) when the save
/// completed, or `null` when the user cancelled. Throws on write failure.
Future<String?> saveBytes(String fileName, List<int> bytes) =>
    impl.saveBytes(fileName, bytes);
