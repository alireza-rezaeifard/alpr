class SessionModel {
  final int id;
  final String sourceType;
  final String? sourceFile;
  final String startedAt;
  final String? endedAt;
  final int totalFrames;
  final int totalPlates;
  final int uniquePlates;
  final String status;

  const SessionModel({
    required this.id,
    required this.sourceType,
    this.sourceFile,
    required this.startedAt,
    this.endedAt,
    required this.totalFrames,
    required this.totalPlates,
    required this.uniquePlates,
    required this.status,
  });

  factory SessionModel.fromJson(Map<String, dynamic> json) => SessionModel(
        id: json['id'] as int,
        sourceType: json['source_type'] as String,
        sourceFile: json['source_file'] as String?,
        startedAt: json['started_at'] as String,
        endedAt: json['ended_at'] as String?,
        totalFrames: json['total_frames'] as int? ?? 0,
        totalPlates: json['total_plates'] as int? ?? 0,
        uniquePlates: json['unique_plates'] as int? ?? 0,
        status: json['status'] as String? ?? 'unknown',
      );

  /// Duration in seconds, or null if endedAt is null.
  int? get durationSeconds {
    if (endedAt == null) return null;
    final start = DateTime.tryParse(startedAt);
    final end = DateTime.tryParse(endedAt!);
    if (start == null || end == null) return null;
    return end.difference(start).inSeconds.abs();
  }
}
