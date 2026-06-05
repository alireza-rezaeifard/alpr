class PlateLogEntry {
  final int frame;
  final String time;
  final String plateText;
  final String dtrbText;
  final double confidence;

  const PlateLogEntry({
    required this.frame,
    required this.time,
    required this.plateText,
    required this.dtrbText,
    required this.confidence,
  });

  factory PlateLogEntry.fromJson(Map<String, dynamic> json) => PlateLogEntry(
        frame: json['frame'] as int? ?? 0,
        time: json['time'] as String? ?? '',
        plateText: json['plate_text'] as String? ?? '',
        dtrbText: json['dtrb_text'] as String? ?? '',
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      );
}

class VideoTaskStatus {
  final String status;
  final int frameIdx;
  final int totalFrames;
  final List<PlateLogEntry> plateLog;
  final List<String> liveDetections;
  final String? error;
  final String? outputPath;
  final String? annotated; // base64 data URL of latest annotated frame

  const VideoTaskStatus({
    required this.status,
    required this.frameIdx,
    required this.totalFrames,
    required this.plateLog,
    required this.liveDetections,
    this.error,
    this.outputPath,
    this.annotated,
  });

  factory VideoTaskStatus.fromJson(Map<String, dynamic> json) =>
      VideoTaskStatus(
        status: json['status'] as String? ?? 'unknown',
        frameIdx: json['frame_idx'] as int? ?? 0,
        totalFrames: json['total_frames'] as int? ?? 0,
        plateLog: (json['plate_log'] as List? ?? [])
            .map((e) => PlateLogEntry.fromJson(e as Map<String, dynamic>))
            .toList(),
        liveDetections: List<String>.from(json['live_detections'] as List? ?? []),
        error: json['error'] as String?,
        outputPath: json['output_path'] as String?,
        annotated: json['annotated'] as String?,
      );

  /// Progress in percent [0,100], or null when indeterminate.
  int? get progressPercent {
    if (totalFrames <= 0) return null;
    return (frameIdx / totalFrames * 100).round().clamp(0, 100);
  }
}
