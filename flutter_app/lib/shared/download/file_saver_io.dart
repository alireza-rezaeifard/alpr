// lib/shared/download/file_saver_io.dart
// Desktop/mobile implementation: prompt for a destination then write the bytes.

import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

Future<String?> saveBytes(String fileName, List<int> bytes) async {
  final path = await FilePicker.platform.saveFile(
    dialogTitle: 'ذخیره خروجی',
    fileName: fileName,
    type: FileType.custom,
    allowedExtensions: const ['csv'],
    bytes: Uint8List.fromList(bytes),
  );
  if (path == null) return null;
  // On desktop the picker returns the chosen path but does not write the file,
  // so persist the bytes ourselves.
  final file = File(path);
  if (!await file.exists() || await file.length() != bytes.length) {
    await file.writeAsBytes(bytes, flush: true);
  }
  return path;
}
