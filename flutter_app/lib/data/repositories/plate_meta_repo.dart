import 'package:dio/dio.dart';
import '../models/plate_metadata_model.dart';
import '../../core/api_client.dart';

class PlateMetaRepo {
  final Dio _dio;
  PlateMetaRepo({Dio? dio}) : _dio = dio ?? ApiClient.instance;

  Future<PlateMetadataModel> getMetadata(String plate) async {
    final res = await _dio.get('/plate/metadata',
        queryParameters: {'plate': plate},
        options: ApiClient.withTimeout(ApiClient.viewTimeout));
    return PlateMetadataModel.fromJson(res.data as Map<String, dynamic>);
  }
}
