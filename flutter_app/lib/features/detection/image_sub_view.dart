// lib/features/detection/image_sub_view.dart
// Modern image detection sub-view.

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import '../../shared/app_icons.dart';
import '../../data/repositories/detect_repo.dart';
import '../../core/api_client.dart';
import '../plate_details/plate_details_panel.dart';

// ── State ──────────────────────────────────────────────────────────────────

class _ImageDetectState {
  final bool processing;
  final String? annotated;
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
        fileValidationError: clearFileError ? null : (fileValidationError ?? this.fileValidationError),
      );
}

// ── Controller ─────────────────────────────────────────────────────────────

class _ImageDetectController extends StateNotifier<_ImageDetectState> {
  final DetectRepo _repo;
  _ImageDetectController(this._repo) : super(const _ImageDetectState());

  Future<void> pickAndSubmit(BuildContext context) async {
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

    final ext = name.split('.').last.toLowerCase();
    if (!['jpg', 'jpeg', 'png', 'bmp'].contains(ext)) {
      state = state.copyWith(fileValidationError: 'Unsupported format. Use JPEG, PNG, or BMP.');
      return;
    }
    if (bytes != null && bytes.length > 10 * 1024 * 1024) {
      state = state.copyWith(fileValidationError: 'File too large. Max 10 MB.');
      return;
    }
    if (bytes == null) return;

    state = state.copyWith(processing: true, clearError: true);

    try {
      final res = await _repo.detectImage(bytes, name).timeout(ApiClient.uploadTimeout);
      state = state.copyWith(processing: false, annotated: res.annotated, plates: res.plates);
    } on ApiException catch (e) {
      state = state.copyWith(processing: false, error: 'Detection failed: ${e.failure.message}');
    } catch (e) {
      final msg = e.toString().contains('TimeoutException') ? 'Request timed out.' : e.toString();
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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Upload controls
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF111113),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white.withOpacity(0.06)),
          ),
          child: Row(
            children: [
              _ModernButton(
                icon: state.processing ? AppIcons.loader2 : AppIcons.upload,
                label: state.processing ? 'Processing…' : 'Select Image',
                onTap: state.processing ? null : () => controller.pickAndSubmit(context),
              ),
              if (state.processing) ...[
                const SizedBox(width: 12),
                SizedBox(width: 16, height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white.withOpacity(0.4))),
              ],
              const Spacer(),
              Text('Supports: JPG, PNG, BMP (max 10MB)',
                  style: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.3))),
            ],
          ),
        ),

        // Validation / error
        if (state.fileValidationError != null) ...[
          const SizedBox(height: 8),
          _ErrorBanner(message: state.fileValidationError!),
        ],
        if (state.error != null) ...[
          const SizedBox(height: 8),
          _ErrorBanner(message: state.error!),
        ],

        const SizedBox(height: 12),

        // Results: image + plates side by side
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                flex: 2,
                child: _AnnotatedImage(annotated: state.annotated),
              ),
              const SizedBox(width: 12),
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
    );
  }
}

// ── Annotated image ────────────────────────────────────────────────────────

class _AnnotatedImage extends StatelessWidget {
  final String? annotated;
  const _AnnotatedImage({this.annotated});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      clipBehavior: Clip.antiAlias,
      child: annotated == null
          ? Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(AppIcons.image, size: 48, color: Colors.white.withOpacity(0.12)),
                  const SizedBox(height: 12),
                  Text('No image selected', style: TextStyle(color: Colors.white.withOpacity(0.3))),
                ],
              ),
            )
          : _decodeAndShow(annotated!),
    );
  }

  Widget _decodeAndShow(String data) {
    try {
      final comma = data.indexOf(',');
      final b64 = comma >= 0 ? data.substring(comma + 1) : data;
      final bytes = base64Decode(b64);
      return Image.memory(bytes, fit: BoxFit.contain);
    } catch (_) {
      return Center(child: Icon(AppIcons.imageOff, size: 48, color: Colors.white.withOpacity(0.2)));
    }
  }
}

// ── Plate list ─────────────────────────────────────────────────────────────

class _PlateList extends StatelessWidget {
  final List<Map<String, dynamic>> plates;
  final void Function(Map<String, dynamic>) onTap;
  const _PlateList({required this.plates, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Icon(AppIcons.creditCard, size: 14, color: Colors.white.withOpacity(0.4)),
                const SizedBox(width: 6),
                Text('Detected (${plates.length})', style: TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w500, color: Colors.white.withOpacity(0.7))),
              ],
            ),
          ),
          Divider(height: 1, color: Colors.white.withOpacity(0.04)),
          Expanded(
            child: plates.isEmpty
                ? Center(child: Text('No plates detected',
                    style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.3))))
                : ListView.builder(
                    padding: const EdgeInsets.all(8),
                    itemCount: plates.length,
                    itemBuilder: (ctx, i) {
                      final plate = plates[i];
                      final persian = plate['plate_persian'] as String?;
                      final dtrb = plate['plate_dtrb'] as String? ?? '';
                      final conf = ((plate['confidence'] as num?)?.toDouble() ?? 0.0) * 100;
                      return GestureDetector(
                        onTap: () => onTap(plate),
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 6),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: Colors.white.withOpacity(0.02),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: Colors.white.withOpacity(0.04)),
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(persian ?? dtrb, style: const TextStyle(
                                      fontSize: 13, fontWeight: FontWeight.w500, color: Colors.white)),
                                    Text('Confidence: ${conf.toStringAsFixed(1)}%', style: TextStyle(
                                      fontSize: 11, color: Colors.white.withOpacity(0.4))),
                                  ],
                                ),
                              ),
                              Icon(AppIcons.chevronRight, size: 14, color: Colors.white.withOpacity(0.3)),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

// ── Shared widgets ─────────────────────────────────────────────────────────

class _ModernButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  const _ModernButton({required this.icon, required this.label, this.onTap});

  @override
  Widget build(BuildContext context) {
    const color = Color(0xFF3B82F6);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          color: onTap != null ? color.withOpacity(0.1) : Colors.white.withOpacity(0.02),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: onTap != null ? color.withOpacity(0.3) : Colors.white.withOpacity(0.04)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: onTap != null ? color : Colors.white.withOpacity(0.3)),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500,
                color: onTap != null ? color : Colors.white.withOpacity(0.3))),
          ],
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;
  const _ErrorBanner({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFEF4444).withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.2)),
      ),
      child: Row(
        children: [
          const Icon(AppIcons.alertCircle, size: 14, color: Color(0xFFEF4444)),
          const SizedBox(width: 8),
          Expanded(child: Text(message, style: const TextStyle(fontSize: 12, color: Color(0xFFEF4444)))),
        ],
      ),
    );
  }
}
