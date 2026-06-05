class DetectionModel {
  final int id;
  final String timestamp;
  final String sourceType;
  final String? sourceFile;
  final String plateDtrb;
  final String? platePersian;
  final double confidence;
  final int? cameraId;
  final String? cameraName;

  const DetectionModel({
    required this.id,
    required this.timestamp,
    required this.sourceType,
    this.sourceFile,
    required this.plateDtrb,
    this.platePersian,
    required this.confidence,
    this.cameraId,
    this.cameraName,
  });

  factory DetectionModel.fromJson(Map<String, dynamic> json) => DetectionModel(
        id: json['id'] as int,
        timestamp: json['timestamp'] as String,
        sourceType: json['source_type'] as String,
        sourceFile: json['source_file'] as String?,
        plateDtrb: json['plate_dtrb'] as String? ?? '',
        platePersian: json['plate_persian'] as String?,
        confidence: (json['confidence'] as num).toDouble(),
        cameraId: json['camera_id'] as int?,
        cameraName: json['camera_name'] as String?,
      );
}

class DetectionsResponse {
  final List<DetectionModel> data;
  final int total;
  final int limit;
  final int offset;

  const DetectionsResponse({
    required this.data,
    required this.total,
    required this.limit,
    required this.offset,
  });

  factory DetectionsResponse.fromJson(Map<String, dynamic> json) =>
      DetectionsResponse(
        data: (json['data'] as List)
            .map((e) => DetectionModel.fromJson(e as Map<String, dynamic>))
            .toList(),
        total: json['total'] as int,
        limit: json['limit'] as int,
        offset: json['offset'] as int,
      );
}
