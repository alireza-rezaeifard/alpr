import 'package:dio/dio.dart';
import '../models/detection_model.dart';
import '../models/video_task_model.dart';
import '../models/rtsp_task_model.dart';
import '../../core/api_client.dart';

class DetectImageResult {
  final int sessionId;
  final String annotated; // base64 data URL
  final List<Map<String, dynamic>> plates;
  DetectImageResult({required this.sessionId, required this.annotated, required this.plates});
  factory DetectImageResult.fromJson(Map<String, dynamic> json) => DetectImageResult(
        sessionId: json['session_id'] as int,
        annotated: json['annotated'] as String,
        plates: List<Map<String, dynamic>>.from(json['plates'] as List),
      );
}

class VideoStartResult {
  final String taskId;
  final int sessionId;
  VideoStartResult({required this.taskId, required this.sessionId});
  factory VideoStartResult.fromJson(Map<String, dynamic> json) => VideoStartResult(
        taskId: json['task_id'] as String,
        sessionId: json['session_id'] as int,
      );
}

class DetectRepo {
  final Dio _dio;
  DetectRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  Future<DetectImageResult> detectImage(List<int> fileBytes, String filename) async {
    final form = FormData.fromMap({
      'file': MultipartFile.fromBytes(fileBytes, filename: filename),
    });
    final res = await _dio.post('/detect/image',
        data: form,
        options: ApiClient.withTimeout(ApiClient.uploadTimeout));
    return DetectImageResult.fromJson(res.data as Map<String, dynamic>);
  }

  Future<VideoStartResult> startVideoTask(
      List<int> fileBytes, String filename, int skipFrames) async {
    final form = FormData.fromMap({
      'file': MultipartFile.fromBytes(fileBytes, filename: filename),
      'skip_frames': skipFrames.toString(),
      'fast_mode': 'false',
    });
    final res = await _dio.post('/detect/video',
        data: form,
        options: ApiClient.withTimeout(ApiClient.uploadTimeout));
    return VideoStartResult.fromJson(res.data as Map<String, dynamic>);
  }

  Future<VideoTaskStatus> pollVideoTask(String taskId) async {
    final res = await _dio.get('/detect/video/$taskId',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return VideoTaskStatus.fromJson(res.data as Map<String, dynamic>);
  }

  Future<void> stopVideoTask(String taskId) async {
    await _dio.post('/detect/video/$taskId/stop',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
  }

  Future<Map<String, dynamic>> startRtsp(String url, int skipFrames) async {
    final form = FormData.fromMap({
      'url': url,
      'skip_frames': skipFrames.toString(),
      'fast_mode': 'false',
    });
    final res = await _dio.post('/detect/rtsp',
        data: form,
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return res.data as Map<String, dynamic>;
  }

  Future<RtspTaskStatus> pollRtsp(String taskId) async {
    final res = await _dio.get('/detect/rtsp/$taskId',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return RtspTaskStatus.fromJson(res.data as Map<String, dynamic>);
  }

  Future<void> stopRtsp(String taskId) async {
    await _dio.post('/detect/rtsp/$taskId/stop',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
  }
}
