class StatsModel {
  final int totalDetections;
  final int uniquePlates;
  final int totalSessions;
  final double? avgConfidence;
  final int detections7d;
  final int sessions7d;

  const StatsModel({
    required this.totalDetections,
    required this.uniquePlates,
    required this.totalSessions,
    this.avgConfidence,
    required this.detections7d,
    required this.sessions7d,
  });

  factory StatsModel.fromJson(Map<String, dynamic> json) => StatsModel(
        totalDetections: json['total_detections'] as int,
        uniquePlates: json['unique_plates'] as int,
        totalSessions: json['total_sessions'] as int,
        avgConfidence: (json['avg_confidence'] as num?)?.toDouble(),
        detections7d: json['detections_7d'] as int,
        sessions7d: json['sessions_7d'] as int,
      );
}
