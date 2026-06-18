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
  final String? carColor;
  final String? carType;
  final String? city;
  final List<double>? carBbox;

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
    this.carColor,
    this.carType,
    this.city,
    this.carBbox,
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
        carColor: json['car_color'] as String?,
        carType: json['car_type'] as String?,
        city: json['city'] as String?,
        carBbox: json['car_bbox'] != null
            ? (json['car_bbox'] as List).map((e) => (e as num).toDouble()).toList()
            : null,
      );
}
