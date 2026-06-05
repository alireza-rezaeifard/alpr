import 'package:dio/dio.dart';
import '../models/detection_model.dart';
import '../../core/api_client.dart';

class DetectionsRepo {
  final Dio _dio;
  DetectionsRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  Future<DetectionsResponse> getDetections({
    int limit = 50,
    int offset = 0,
    String sourceType = 'all',
    String search = '',
  }) async {
    final params = <String, dynamic>{
      'limit': limit,
      'offset': offset,
    };
    if (sourceType != 'all') params['source_type'] = sourceType;
    if (search.isNotEmpty) params['search'] = search;

    final res = await _dio.get('/detections',
        queryParameters: params,
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return DetectionsResponse.fromJson(res.data as Map<String, dynamic>);
  }
}
