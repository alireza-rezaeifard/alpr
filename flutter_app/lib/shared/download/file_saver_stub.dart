// lib/shared/download/file_saver_stub.dart
// Fallback used when neither dart:io nor web is available.

Future<String?> saveBytes(String fileName, List<int> bytes) async {
  throw UnsupportedError('File saving is not supported on this platform.');
}
