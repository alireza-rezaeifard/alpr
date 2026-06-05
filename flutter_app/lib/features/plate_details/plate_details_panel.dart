// lib/features/plate_details/plate_details_panel.dart
// Shows plate category, color scheme (with swatch), region, and Persian text.
// Requirements: 15.1–15.7

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/plate_metadata_model.dart';
import '../../data/repositories/plate_meta_repo.dart';
import '../../core/api_client.dart';

// ── Provider ──────────────────────────────────────────────────────────────

final _plateMetaRepoProvider = Provider((_) => PlateMetaRepo());

/// Keyed by the raw plate string. Provide a 10s timeout via ApiClient.
final plateMetadataProvider =
    FutureProvider.family<PlateMetadataModel, String>((ref, plate) =>
        ref.read(_plateMetaRepoProvider).getMetadata(plate));

// ── Panel widget ──────────────────────────────────────────────────────────

/// A panel widget that loads and displays Iranian plate metadata for [plateValue].
///
/// Accepts either a persian or latin (dtrb) plate string. Pass as a modal
/// bottom sheet or side panel.
///
/// Requirements: 15.1–15.7
class PlateDetailsPanel extends ConsumerWidget {
  final String plateValue;
  final String? platePersian; // Already-formatted Persian plate for display

  const PlateDetailsPanel({
    super.key,
    required this.plateValue,
    this.platePersian,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final metaAsync = ref.watch(plateMetadataProvider(plateValue));

    return Container(
      padding: const EdgeInsets.all(20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            children: [
              const Icon(Icons.credit_card, size: 28),
              const SizedBox(width: 8),
              Text(
                'Plate Details',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),

          // Persian plate display (Req 15.5) — RTL rendering (Req 15.7)
          if (platePersian != null && platePersian!.isNotEmpty)
            Directionality(
              textDirection: TextDirection.rtl,
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                margin: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: Theme.of(context).colorScheme.outline,
                  ),
                ),
                child: Text(
                  platePersian!,
                  textDirection: TextDirection.rtl,
                  style: Theme.of(context)
                      .textTheme
                      .headlineMedium
                      ?.copyWith(fontWeight: FontWeight.bold),
                  textAlign: TextAlign.center,
                ),
              ),
            ),

          const Divider(),

          // Metadata content
          metaAsync.when(
            // Req 15.2 — loading indicator
            loading: () => const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator()),
            ),
            // Req 15.6 — request failure: stop loader, show error + retry
            error: (e, _) {
              final msg =
                  (e is ApiException) ? e.failure.message : e.toString();
              return Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    const Icon(Icons.error_outline,
                        color: Colors.red, size: 40),
                    const SizedBox(height: 8),
                    Text(
                      'Failed to load plate details: $msg',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    ElevatedButton.icon(
                      icon: const Icon(Icons.refresh),
                      label: const Text('Retry'),
                      onPressed: () =>
                          ref.invalidate(plateMetadataProvider(plateValue)),
                    ),
                  ],
                ),
              );
            },
            data: (meta) {
              // Req 15.3 — not-classified result
              if (!meta.classified) {
                return Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(Icons.help_outline, color: Colors.orange),
                          SizedBox(width: 8),
                          Text('Not Classified',
                              style: TextStyle(
                                  fontWeight: FontWeight.bold, fontSize: 16)),
                        ],
                      ),
                      if (meta.reason != null) ...[
                        const SizedBox(height: 8),
                        Text(meta.reason!,
                            style: const TextStyle(color: Colors.grey)),
                      ],
                    ],
                  ),
                );
              }

              // Classified result — show all fields
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Req 15.1 — category
                  _DetailRow(
                    label: 'Category',
                    value: meta.categoryDisplay ?? meta.category ?? '—',
                    isRtl: false,
                  ),
                  // Req 15.4 — color scheme: text + visual swatch
                  _ColorSchemeRow(meta: meta),
                  // Req 15.1 — region
                  _DetailRow(
                    label: 'Region',
                    value: meta.regionName ?? '—',
                    isRtl: true, // Province names include Persian text (Req 15.7)
                  ),
                  // Req 15.1 — special note (if any)
                  if (meta.specialNote != null && meta.specialNote!.isNotEmpty)
                    _DetailRow(
                      label: 'Note',
                      value: meta.specialNote!,
                      isRtl: true,
                    ),
                  const SizedBox(height: 8),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

// ── Helper widgets ────────────────────────────────────────────────────────

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;
  final bool isRtl;
  const _DetailRow({
    required this.label,
    required this.value,
    required this.isRtl,
  });

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 80,
              child: Text(
                label,
                style: Theme.of(context)
                    .textTheme
                    .labelMedium
                    ?.copyWith(color: Colors.grey),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Directionality(
                textDirection:
                    isRtl ? TextDirection.rtl : TextDirection.ltr,
                child: Text(
                  value,
                  textDirection: isRtl ? TextDirection.rtl : TextDirection.ltr,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
            ),
          ],
        ),
      );
}

// Req 15.4 — renders color scheme name as text + filled color indicator
class _ColorSchemeRow extends StatelessWidget {
  final PlateMetadataModel meta;
  const _ColorSchemeRow({required this.meta});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          children: [
            SizedBox(
              width: 80,
              child: Text(
                'Color',
                style: Theme.of(context)
                    .textTheme
                    .labelMedium
                    ?.copyWith(color: Colors.grey),
              ),
            ),
            const SizedBox(width: 12),
            // Color swatch (filled circle)
            Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(
                color: meta.swatchColor,
                shape: BoxShape.circle,
                border: Border.all(
                  color: Colors.grey.shade400,
                  width: 1.5,
                ),
              ),
            ),
            const SizedBox(width: 8),
            // Color scheme name as text
            Text(
              meta.colorScheme ?? '—',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ],
        ),
      );
}

// ── Helper to show the panel as a bottom sheet ────────────────────────────

/// Show [PlateDetailsPanel] as a modal bottom sheet.
void showPlateDetails(
  BuildContext context, {
  required String plateValue,
  String? platePersian,
}) {
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
    ),
    builder: (_) => ProviderScope(
      child: PlateDetailsPanel(
        plateValue: plateValue,
        platePersian: platePersian,
      ),
    ),
  );
}
