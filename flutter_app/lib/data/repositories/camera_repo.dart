import 'package:dio/dio.dart';
import '../models/camera_model.dart';
import '../../core/api_client.dart';

class CameraRepo {
  final Dio _dio;
  CameraRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  Future<List<CameraModel>> listCameras() async {
    final res = await _dio.get('/cameras',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    final data = _asList(res.data);
    return data.map((e) => CameraModel.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<CameraModel> createCamera(String name, String url, int skipFrames) async {
    final res = await _dio.post('/cameras',
        data: {'name': name, 'url': url, 'skip_frames': skipFrames},
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return CameraModel.fromJson(res.data as Map<String, dynamic>);
  }

  Future<CameraModel> updateCamera(int id, {String? name, String? url, int? skipFrames}) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (url != null) body['url'] = url;
    if (skipFrames != null) body['skip_frames'] = skipFrames;
    final res = await _dio.patch('/cameras/$id',
        data: body,
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return CameraModel.fromJson(res.data as Map<String, dynamic>);
  }

  Future<void> deleteCamera(int id) async {
    await _dio.delete('/cameras/$id',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
  }

  Future<StartResultModel> startCamera(int id) async {
    final res = await _dio.post('/cameras/$id/start',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return StartResultModel.fromJson(res.data as Map<String, dynamic>);
  }

  Future<void> stopCamera(int id) async {
    await _dio.post('/cameras/$id/stop',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
  }

  Future<List<StartResultModel>> startAll() async {
    final res = await _dio.post('/cameras/start-all',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    final data = _asList(res.data);
    return data.map((e) => StartResultModel.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> stopAll() async {
    await _dio.post('/cameras/stop-all',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
  }

  Future<int> getConcurrencyLimit() async {
    final res = await _dio.get('/config/concurrency',
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return (res.data as Map)['concurrency_limit'] as int;
  }

  Future<int> setConcurrencyLimit(int value) async {
    final res = await _dio.put('/config/concurrency',
        data: {'value': value},
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return (res.data as Map)['concurrency_limit'] as int;
  }
}

/// Accepts either a bare JSON array (new routers) or a ``{ "data": [...] }``
/// envelope (legacy endpoints) and returns the underlying list.
List<dynamic> _asList(dynamic body) {
  if (body is List) return body;
  if (body is Map && body['data'] is List) return body['data'] as List;
  return const [];
}
