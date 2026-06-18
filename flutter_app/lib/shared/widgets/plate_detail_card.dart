// lib/shared/widgets/plate_detail_card.dart
// Displays a single detected plate with full Iranian metadata.
// Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

import 'package:flutter/material.dart';
import '../../data/models/enhanced_plate_log_entry.dart';

/// A card widget that displays a detected license plate with full metadata.
///
/// For valid Iranian plates (`entry.isValidIranian == true`), shows:
/// - Persian formatted plate text in bold RTL text
/// - Color swatch indicator matching the plate color scheme
/// - Category badge (e.g., "شخصی (Private)")
/// - Province/region name
/// - Confidence percentage
/// - Frame number and timestamp
///
/// For unclassified detections, shows the raw text greyed out with no
/// metadata fields.
///
/// Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
class PlateDetailCard extends StatelessWidget {
  final EnhancedPlateLogEntry entry;

  const PlateDetailCard({super.key, required this.entry});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (!entry.isValidIranian || entry.metadata == null) {
      return _buildUnclassifiedCard(context, theme);
    }

    return _buildClassifiedCard(context, theme);
  }

  /// Builds a full metadata card for a valid Iranian plate (Req 6.1–6.5).
  Widget _buildClassifiedCard(BuildContext context, ThemeData theme) {
    final meta = entry.metadata!;

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 0),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Color swatch indicator (Req 6.4)
            _buildColorSwatch(meta.swatchColor),
            const SizedBox(width: 12),
            // Main content
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Persian plate text (Req 6.1) — RTL, bold
                  Directionality(
                    textDirection: TextDirection.rtl,
                    child: Text(
                      entry.persianDisplay,
                      textDirection: TextDirection.rtl,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  // Category badge (Req 6.2)
                  if (meta.categoryDisplay != null &&
                      meta.categoryDisplay!.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Chip(
                        label: Text(
                          meta.categoryDisplay!,
                          style: const TextStyle(fontSize: 11),
                        ),
                        padding: EdgeInsets.zero,
                        materialTapTargetSize:
                            MaterialTapTargetSize.shrinkWrap,
                        visualDensity: VisualDensity.compact,
                      ),
                    ),
                  // Province/region name (Req 6.3)
                  if (meta.regionName != null && meta.regionName!.isNotEmpty)
                    Directionality(
                      textDirection: TextDirection.rtl,
                      child: Text(
                        meta.regionName!,
                        textDirection: TextDirection.rtl,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ),
                  // Car info: color + type
                  if (entry.carColor != null || entry.carType != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Row(
                        children: [
                          if (entry.carColor != null)
                            _carColorDot(entry.carColor!),
                          if (entry.carColor != null && entry.carType != null)
                            const SizedBox(width: 4),
                          Text(
                            [entry.carColor, entry.carType]
                                .where((e) => e != null)
                                .join(' · '),
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                  // City
                  if (entry.city != null && entry.city!.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(
                        entry.city!,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                  const SizedBox(height: 4),
                  // Frame / timestamp / confidence (Req 6.5)
                  Text(
                    'Frame ${entry.frame} @ ${entry.time} | '
                    'Conf: ${(entry.confidence * 100).toStringAsFixed(0)}%',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.outline),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Builds a greyed-out card for unclassified detections (Req 6.6).
  Widget _buildUnclassifiedCard(BuildContext context, ThemeData theme) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 0),
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // Grey swatch for unclassified
            _buildColorSwatch(Colors.grey),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Raw plate text only — no metadata
                  Text(
                    entry.persianDisplay.isNotEmpty
                        ? entry.persianDisplay
                        : entry.plateText,
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                      color: theme.colorScheme.outline,
                    ),
                  ),
                  // Car info (even for unclassified plates)
                  if (entry.carColor != null || entry.carType != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Row(
                        children: [
                          if (entry.carColor != null)
                            _carColorDot(entry.carColor!),
                          if (entry.carColor != null && entry.carType != null)
                            const SizedBox(width: 4),
                          Text(
                            [entry.carColor, entry.carType]
                                .where((e) => e != null)
                                .join(' · '),
                            style: theme.textTheme.bodySmall
                                ?.copyWith(color: theme.colorScheme.outline),
                          ),
                        ],
                      ),
                    ),
                  if (entry.city != null && entry.city!.isNotEmpty)
                    Text(
                      entry.city!,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                  const SizedBox(height: 4),
                  Text(
                    'Frame ${entry.frame} @ ${entry.time} | '
                    'Conf: ${(entry.confidence * 100).toStringAsFixed(0)}%',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.outline),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Builds a circular color indicator for the plate color scheme.
  Widget _buildColorSwatch(Color color) {
    return Container(
      width: 24,
      height: 24,
      margin: const EdgeInsets.only(top: 4),
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        border: Border.all(color: Colors.grey.shade400, width: 1.5),
      ),
    );
  }

  /// Maps car color name to a Flutter Color.
  Color _carColorToFlutterColor(String name) {
    switch (name.toLowerCase()) {
      case 'black':   return const Color(0xFF1A1A1A);
      case 'blue':    return const Color(0xFF3B82F6);
      case 'brown':   return const Color(0xFF8B4513);
      case 'crimson':
      case 'crismon': return const Color(0xFFDC143C);
      case 'gray':
      case 'grey':    return const Color(0xFF808080);
      case 'green':   return const Color(0xFF22C55E);
      case 'orange':  return const Color(0xFFF97316);
      case 'purple':  return const Color(0xFFA855F7);
      case 'red':     return const Color(0xFFEF4444);
      case 'silver':  return const Color(0xFFC0C0C0);
      case 'white':   return const Color(0xFFF5F5F5);
      case 'yellow':  return const Color(0xFFEAB308);
      default:        return Colors.grey;
    }
  }

  /// Small colored dot for car color.
  Widget _carColorDot(String colorName) {
    return Container(
      width: 10,
      height: 10,
      decoration: BoxDecoration(
        color: _carColorToFlutterColor(colorName),
        shape: BoxShape.circle,
        border: Border.all(color: Colors.grey.shade500, width: 0.5),
      ),
    );
  }
}
