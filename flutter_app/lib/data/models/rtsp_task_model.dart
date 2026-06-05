class PlateHistoryEntry {
  final String dtrbText;
  final String yoloText;
  final double confidence;
  final String firstSeen;
  final String lastSeen;
  final int count;

  const PlateHistoryEntry({
    required this.dtrbText,
    required this.yoloText,
    required this.confidence,
    required this.firstSeen,
    required this.lastSeen,
    required this.count,
  });

  factory PlateHistoryEntry.fromJson(Map<String, dynamic> json) =>
      PlateHistoryEntry(
        dtrbText: json['dtrb_text'] as String? ?? '',
        yoloText: json['yolo_text'] as String? ?? '',
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
        firstSeen: json['first_seen'] as String? ?? '',
        lastSeen: json['last_seen'] as String? ?? '',
        count: json['count'] as int? ?? 1,
      );
}

class RtspTaskStatus {
  final String status;
  final List<PlateHistoryEntry> history;
  final List<String> liveDetections;
  final String? annotated; // base64 data URL or null

  const RtspTaskStatus({
    required this.status,
    required this.history,
    required this.liveDetections,
    this.annotated,
  });

  factory RtspTaskStatus.fromJson(Map<String, dynamic> json) => RtspTaskStatus(
        status: json['status'] as String? ?? 'unknown',
        history: (json['history'] as List? ?? [])
            .map((e) => PlateHistoryEntry.fromJson(e as Map<String, dynamic>))
            .toList(),
        liveDetections:
            List<String>.from(json['live_detections'] as List? ?? []),
        annotated: json['annotated'] as String?,
      );

  bool get hasError => status.startsWith('error');
}
