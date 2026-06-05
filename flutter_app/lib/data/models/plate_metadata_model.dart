import 'package:flutter/material.dart';

class PlateMetadataModel {
  final bool classified;
  final String? category;
  final String? categoryDisplay;
  final String? colorScheme; // white|yellow|green|red|blue|black
  final String? regionCode;
  final String? regionName;
  final String? specialNote;
  final String? reason;

  const PlateMetadataModel({
    required this.classified,
    this.category,
    this.categoryDisplay,
    this.colorScheme,
    this.regionCode,
    this.regionName,
    this.specialNote,
    this.reason,
  });

  factory PlateMetadataModel.fromJson(Map<String, dynamic> json) =>
      PlateMetadataModel(
        classified: json['classified'] as bool? ?? false,
        category: json['category'] as String?,
        categoryDisplay: json['category_display'] as String?,
        colorScheme: json['color_scheme'] as String?,
        regionCode: json['region_code'] as String?,
        regionName: json['region_name'] as String?,
        specialNote: json['special_note'] as String?,
        reason: json['reason'] as String?,
      );

  /// Maps the color_scheme string to a Flutter Color for the swatch.
  Color get swatchColor {
    switch (colorScheme?.toLowerCase()) {
      case 'white':  return Colors.white;
      case 'yellow': return Colors.yellow;
      case 'green':  return Colors.green;
      case 'red':    return Colors.red;
      case 'blue':   return Colors.blue;
      case 'black':  return Colors.black;
      default:       return Colors.grey;
    }
  }
}
