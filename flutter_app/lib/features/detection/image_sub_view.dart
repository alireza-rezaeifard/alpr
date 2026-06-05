// lib/features/detection/image_sub_view.dart
// Image detection sub-view: file picking, upload, annotated result, plate list.
// Requirements: 7.1–7.10

import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import '../../data/repositories/detect_repo.dart';
import '../../core/api_client.dart';
import '../plate_details/plate_details_panel.dart';

// ── State ──────────────────────────────────────────────────────────────────

class _ImageDetectState {
  final bool processing;
  final String? annotated;        // base64 data URL
  final List<Map<String, dynamic>> plates;
  final String? error;
  final String? fileValidationError;

  const _ImageDetectState({
    this.processing = false,
    this.annotated,
    this.plates = const [],
    this.error,
    this.fileValidationError,
  });

  _ImageDetectState copyWith({
    bool? processing,
    String? annotated,
    List<Map<String, dynamic>>? plates,
    String? error,
    String? fileValidationError,
    bool clearError = false,
    bool clearFileError = false,
  }) =>
      _ImageDetectState(
        processing: processing ?? this.processing,
        annotated: annotated ?? this.annotated,
        plates: plates ?? this.plates,
        error: clearError ? null : (error ?? this.error),
        fileValidationError: clearFileError
            ? null
            : (fileValidationError ?? this.fileValidationError),
      );
}

// ── Controller ─────────────────────────────────────────────────────────────

class _ImageDetectController extends StateNotifier<_ImageDetectState> {
  final DetectRepo _repo;

  _ImageDetectController(this._repo) : super(const _ImageDetectState());

  Future<void> pickAndSubmit(BuildContext context) async {
    // Reset previous file validation error
    state = state.copyWith(clearFileError: true);

    FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['jpg', 'jpeg', 'png', 'bmp'],
      withData: true,
    );
    if (result == null || result.files.isEmpty) return;

    final file = result.files.first;
    final bytes = file.bytes;
    final name = file.name;

    // Req 7.7 — validate format and size
    final ext = name.split('.').last.toLowerCase();
    if (!['jpg', 'jpeg', 'png', 'bmp'].contains(ext)) {
      state = state.copyWith(
        fileValidationError: 'Unsupported file format. Please select a JPEG, PNG, or BMP image.',
      );
      return;
    }
    if (bytes != null && bytes.length > 10 * 1024 * 1024) {
      state = state.copyWith(
        fileValidationError: 'File too large. Maximum size is 10 MB.',
      );
      return;
    }
    if (bytes == null) return;

    // Req 7.5 — show processing indicator, disable submit
    state = state.copyWith(processing: true, clearError: true);

    try {
      final res = await _repo.detectImage(bytes, name)
          .timeout(ApiClient.uploadTimeout);

      state = state.copyWith(
        processing: false,
        annotated: res.annotated,
        plates: res.plates,
      );
    } on ApiException catch (e) {
      state = state.copyWith(
        processing: false,
        error: 'Detection failed (${e.failure.status}): ${e.failure.message}',
      );
    } catch (e) {
      final msg = e.toString().contains('TimeoutException')
          ? 'Request timed out after 60 seconds.'
          : e.toString();
      state = state.copyWith(processing: false, error: msg);
    }
  }
}

final _imageDetectRepoProvider = Provider((_) => DetectRepo());
final _imageDetectControllerProvider =
    StateNotifierProvider.autoDispose<_ImageDetectController, _ImageDetectState>(
        (ref) => _ImageDetectController(ref.read(_imageDetectRepoProvider)));

// ── View ───────────────────────────────────────────────────────────────────

class ImageSubView extends ConsumerWidget {
  const ImageSubView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(_imageDetectControllerProvider);
    final controller = ref.read(_imageDetectControllerProvider.notifier);

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Upload button ────────────────────────────────────────────
          Row(
            children: [
              ElevatedButton.icon(
                icon: const Icon(Icons.upload_file),
                label: const Text('Select Image'),
                // Req 7.5 — disable submit while processing
                onPressed: state.processing
                    ? null
                    : () => controller.pickAndSubmit(context),
              ),
              const SizedBox(width: 12),
              if (state.processing) ...[
                const CircularProgressIndicator(),
                const SizedBox(width: 8),
                const Text('Processing…'),
              ],
            ],
          ),

          // Req 7.7 — file validation message
          if (state.fileValidationError != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                state.fileValidationError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),

          const SizedBox(height: 16),

          // ── Error banner (Req 7.4) ────────────────────────────────────
          if (state.error != null)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    const Icon(Icons.error_outline),
                    const SizedBox(width: 8),
                    Expanded(child: Text(state.error!)),
                  ],
                ),
              ),
            ),

          const SizedBox(height: 8),

          // ── Results area ─────────────────────────────────────────────
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Left: annotated image
                Expanded(
                  flex: 2,
                  child: _AnnotatedImage(annotated: state.annotated),
                ),
                const SizedBox(width: 16),
                // Right: plate list
                Expanded(
                  flex: 1,
                  child: _PlateList(
                    plates: state.plates,
                    onTap: (plate) => showPlateDetails(
                      context,
                      plateValue: plate['plate_dtrb'] as String? ?? '',
                      platePersian: plate['plate_persian'] as String?,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Annotated image widget ─────────────────────────────────────────────────

class _AnnotatedImage extends StatelessWidget {
  final String? annotated;
  const _AnnotatedImage({this.annotated});

  @override
  Widget build(BuildContext context) {
    if (annotated == null) {
      return const Card(
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.image_outlined, size: 64, color: Colors.grey),
              SizedBox(height: 8),
              Text('No image selected', style: TextStyle(color: Colors.grey)),
            ],
          ),
        ),
      );
    }
    try {
      final comma = annotated!.indexOf(',');
      final b64 = comma >= 0 ? annotated!.substring(comma + 1) : annotated!;
      final bytes = base64Decode(b64);
      return Card(
        clipBehavior: Clip.hardEdge,
        child: Image.memory(bytes, fit: BoxFit.contain),
      );
    } catch (_) {
      return const Card(
        child: Center(child: Icon(Icons.broken_image, size: 64, color: Colors.grey)),
      );
    }
  }
}

// ── Plate list widget ──────────────────────────────────────────────────────

class _PlateList extends StatelessWidget {
  final List<Map<String, dynamic>> plates;
  final void Function(Map<String, dynamic> plate) onTap;

  const _PlateList({required this.plates, required this.onTap});

  @override
  Widget build(BuildContext context) {
    if (plates.isEmpty) {
      return const Card(
        child: Center(
          child: Padding(
            padding: EdgeInsets.all(16),
            child: Text(
              'No plates detected',
              style: TextStyle(color: Colors.grey),
            ),
          ),
        ),
      );
    }
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text('Detected Plates (${plates.length})',
                style: Theme.of(context).textTheme.titleSmall),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView.builder(
              itemCount: plates.length,
              itemBuilder: (ctx, i) {
                final plate = plates[i];
                final persian = plate['plate_persian'] as String?;
                final dtrb = plate['plate_dtrb'] as String? ?? '';
                final conf = ((plate['confidence'] as num?)?.toDouble() ?? 0.0) * 100;
                return ListTile(
                  leading: const Icon(Icons.credit_card),
                  title: Text(persian ?? dtrb),
                  subtitle: Text('Confidence: ${conf.toStringAsFixed(1)}%'),
                  trailing: const Icon(Icons.info_outline),
                  // Req 7.10 — tap opens plate details panel
                  onTap: () => onTap(plate),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
