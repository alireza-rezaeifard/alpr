import 'package:dio/dio.dart';
import '../models/stats_model.dart';
import '../models/chart_models.dart';
import '../../core/api_client.dart';

class StatsRepo {
  final Dio _dio;
  StatsRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  Future<StatsModel> getStats() async {
    final res = await _dio.get('/stats',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return StatsModel.fromJson(res.data as Map<String, dynamic>);
  }

  Future<List<TimelineEntry>> getTimeline({int days = 7}) async {
    final res = await _dio.get('/detections/timeline',
        queryParameters: {'days': days},
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    final data = (res.data as Map)['data'] as List;
    return data.map((e) => TimelineEntry.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<SourceEntry>> getSources() async {
    final res = await _dio.get('/detections/sources',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    final data = (res.data as Map)['data'] as List;
    return data.map((e) => SourceEntry.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<ConfidenceEntry>> getConfidence() async {
    final res = await _dio.get('/detections/confidence',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    final data = (res.data as Map)['data'] as List;
    return data.map((e) => ConfidenceEntry.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<LetterEntry>> getLetters() async {
    final res = await _dio.get('/detections/letters',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    final data = (res.data as Map)['data'] as List;
    return data.map((e) => LetterEntry.fromJson(e as Map<String, dynamic>)).toList();
  }
}
