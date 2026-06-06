import 'plate_metadata_model.dart';

/// Enhanced plate log entry returned by the video/RTSP status API endpoints.
///
/// Extends the basic plate detection data with Iranian plate validation info
/// and full metadata (province, vehicle type, plate color scheme).
class EnhancedPlateLogEntry {
  final int frame;
  final String time;
  final double timeSec;
  final String plateText;
  final String dtrbText;
  final double confidence;
  final List<double> bbox;
  final String persianDisplay;
  final bool isValidIranian;
  final PlateMetadataModel? metadata;

  const EnhancedPlateLogEntry({
    required this.frame,
    required this.time,
    required this.timeSec,
    required this.plateText,
    required this.dtrbText,
    required this.confidence,
    required this.bbox,
    required this.persianDisplay,
    required this.isValidIranian,
    this.metadata,
  });

  factory EnhancedPlateLogEntry.fromJson(Map<String, dynamic> json) =>
      EnhancedPlateLogEntry(
        frame: json['frame'] as int? ?? 0,
        time: json['time'] as String? ?? '',
        timeSec: (json['time_sec'] as num?)?.toDouble() ?? 0.0,
        plateText: json['plate_text'] as String? ?? '',
        dtrbText: json['dtrb_text'] as String? ?? '',
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
        bbox: (json['bbox'] as List?)
                ?.map((e) => (e as num).toDouble())
                .toList() ??
            const [0, 0, 0, 0],
        persianDisplay: json['persian_display'] as String? ?? '',
        isValidIranian: json['is_valid_iranian'] as bool? ?? false,
        metadata: json['metadata'] != null
            ? PlateMetadataModel.fromJson(
                json['metadata'] as Map<String, dynamic>)
            : null,
      );
}
