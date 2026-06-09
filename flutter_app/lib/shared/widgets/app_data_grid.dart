// lib/shared/widgets/app_data_grid.dart
// Reusable PlutoGrid wrapper providing the project's dark, RTL, Persian-aware
// data grid with sorting and column controls enabled (Requirement 17.5).
//
// PlutoGrid is built on Material widgets, so the grid is wrapped in a Material
// ancestor; the surrounding screens live inside the Fluent UI shell.

import 'package:flutter/material.dart';
import 'package:pluto_grid/pluto_grid.dart';

/// Shared colors so every grid in the app looks identical.
class GridPalette {
  GridPalette._();

  static const Color surface = Color(0xFF111113);
  static const Color header = Color(0xFF18181B);
  static const Color border = Color(0x14FFFFFF); // white @ ~8%
  static const Color rowEven = Color(0xFF111113);
  static const Color rowOdd = Color(0xFF141417);
  static const Color activated = Color(0x223B82F6);
  static const Color accent = Color(0xFF3B82F6);
  static const Color text = Color(0xFFFAFAFA);
  static const Color mutedText = Color(0xFF9CA3AF);
}

/// A dark, RTL PlutoGrid wrapped in a rounded card.
///
/// Sorting and the per-column control menu are enabled by default on every
/// column (satisfying the "sorting and column controls" requirement). Callers
/// supply the [columns] and [rows] and may capture the [onLoaded] state
/// manager for programmatic control.
class AppDataGrid extends StatelessWidget {
  final List<PlutoColumn> columns;
  final List<PlutoRow> rows;
  final void Function(PlutoGridOnLoadedEvent event)? onLoaded;
  final void Function(PlutoGridOnSelectedEvent event)? onSelected;
  final double rowHeight;

  const AppDataGrid({
    super.key,
    required this.columns,
    required this.rows,
    this.onLoaded,
    this.onSelected,
    this.rowHeight = 48,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      type: MaterialType.transparency,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: GridPalette.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: GridPalette.border),
          ),
          child: PlutoGrid(
            columns: columns,
            rows: rows,
            mode: PlutoGridMode.selectWithOneTap,
            onLoaded: onLoaded,
            onSelected: onSelected,
            configuration: PlutoGridConfiguration(
              style: PlutoGridStyleConfig(
                gridBackgroundColor: GridPalette.surface,
                gridBorderColor: GridPalette.border,
                borderColor: GridPalette.border,
                activatedBorderColor: GridPalette.accent,
                activatedColor: GridPalette.activated,
                rowColor: GridPalette.rowEven,
                evenRowColor: GridPalette.rowOdd,
                columnTextStyle: const TextStyle(
                  color: GridPalette.mutedText,
                  fontFamily: 'Vazirmatn',
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
                cellTextStyle: const TextStyle(
                  color: GridPalette.text,
                  fontFamily: 'Vazirmatn',
                  fontSize: 13,
                ),
                iconColor: GridPalette.mutedText,
                menuBackgroundColor: GridPalette.header,
                gridPopupBorderRadius: BorderRadius.circular(8),
                rowHeight: rowHeight,
                columnHeight: 46,
                enableGridBorderShadow: false,
                enableColumnBorderVertical: false,
              ),
              columnSize: const PlutoGridColumnSizeConfig(
                autoSizeMode: PlutoAutoSizeMode.scale,
              ),
              scrollbar: const PlutoGridScrollbarConfig(
                isAlwaysShown: false,
                scrollbarThickness: 6,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
