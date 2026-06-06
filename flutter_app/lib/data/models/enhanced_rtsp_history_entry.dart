import 'plate_metadata_model.dart';

/// Enhanced RTSP history entry returned by the RTSP status API endpoint.
///
/// Extends the basic RTSP plate history data with Iranian plate validation info
/// and full metadata (province, vehicle type, plate color scheme).
/// RTSP entries include first_seen, last_seen, and count fields for deduplication.
class EnhancedRtspHistoryEntry {
  final String dtrbText;
  final String yoloText;
  final double confidence;
  final String firstSeen;
  final String lastSeen;
  final int count;
  final String persianDisplay;
  final bool isValidIranian;
  final PlateMetadataModel? metadata;

  const EnhancedRtspHistoryEntry({
    required this.dtrbText,
    required this.yoloText,
    required this.confidence,
    required this.firstSeen,
    required this.lastSeen,
    required this.count,
    required this.persianDisplay,
    required this.isValidIranian,
    this.metadata,
  });

  factory EnhancedRtspHistoryEntry.fromJson(Map<String, dynamic> json) =>
      EnhancedRtspHistoryEntry(
        dtrbText: json['dtrb_text'] as String? ?? '',
        yoloText: json['yolo_text'] as String? ?? '',
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
        firstSeen: json['first_seen'] as String? ?? '',
        lastSeen: json['last_seen'] as String? ?? '',
        count: json['count'] as int? ?? 1,
        persianDisplay: json['persian_display'] as String? ?? '',
        isValidIranian: json['is_valid_iranian'] as bool? ?? false,
        metadata: json['metadata'] != null
            ? PlateMetadataModel.fromJson(
                json['metadata'] as Map<String, dynamic>)
            : null,
      );
}
