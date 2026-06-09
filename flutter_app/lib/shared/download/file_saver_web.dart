// lib/shared/download/file_saver_web.dart
// Web implementation: build a Blob and trigger a browser download.

import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

Future<String?> saveBytes(String fileName, List<int> bytes) async {
  final data = Uint8List.fromList(bytes).toJS;
  final blob = web.Blob(
    <JSAny>[data].toJS,
    web.BlobPropertyBag(type: 'text/csv;charset=utf-8'),
  );
  final url = web.URL.createObjectURL(blob);
  final anchor = web.HTMLAnchorElement()
    ..href = url
    ..download = fileName;
  anchor.click();
  web.URL.revokeObjectURL(url);
  return fileName;
}
