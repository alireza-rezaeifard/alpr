import 'package:dio/dio.dart';
import '../models/session_model.dart';
import '../../core/api_client.dart';

class SessionsRepo {
  final Dio _dio;
  SessionsRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  Future<List<SessionModel>> getSessions({int limit = 20}) async {
    final res = await _dio.get('/sessions',
        queryParameters: {'limit': limit},
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    final data = (res.data as Map)['data'] as List;
    return data.map((e) => SessionModel.fromJson(e as Map<String, dynamic>)).toList();
  }
}
