class CameraModel {
  final int id;
  final String name;
  final String url;
  final int skipFrames;
  final String status; // stopped|queued|connecting|connected|streaming|error
  final String? taskId;
  final int? sessionId;

  const CameraModel({
    required this.id,
    required this.name,
    required this.url,
    required this.skipFrames,
    required this.status,
    this.taskId,
    this.sessionId,
  });

  factory CameraModel.fromJson(Map<String, dynamic> json) => CameraModel(
        id: json['id'] as int,
        name: json['name'] as String? ?? '',
        url: json['url'] as String? ?? '',
        skipFrames: json['skip_frames'] as int? ?? 15,
        status: json['status'] as String? ?? 'stopped',
        taskId: json['task_id'] as String?,
        sessionId: json['session_id'] as int?,
      );

  CameraModel copyWith({String? name, String? status, String? taskId}) =>
      CameraModel(
        id: id,
        name: name ?? this.name,
        url: url,
        skipFrames: skipFrames,
        status: status ?? this.status,
        taskId: taskId ?? this.taskId,
        sessionId: sessionId,
      );
}

class StartResultModel {
  final int cameraId;
  final String status; // running|queued|error
  final String? taskId;

  const StartResultModel({
    required this.cameraId,
    required this.status,
    this.taskId,
  });

  factory StartResultModel.fromJson(Map<String, dynamic> json) =>
      StartResultModel(
        cameraId: json['camera_id'] as int,
        status: json['status'] as String,
        taskId: json['task_id'] as String?,
      );
}
