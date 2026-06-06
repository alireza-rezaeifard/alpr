// Tests that VideoTaskStatus and RtspTaskStatus correctly parse enhanced
// plate log/history entries using the new models.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_app/data/models/video_task_model.dart';
import 'package:flutter_app/data/models/rtsp_task_model.dart';
import 'package:flutter_app/data/models/enhanced_plate_log_entry.dart';
import 'package:flutter_app/data/models/enhanced_rtsp_history_entry.dart';

void main() {
  group('VideoTaskStatus enhanced plate_log parsing', () {
    test('parses enhanced plate_log entries with metadata', () {
      final json = {
        'status': 'processing',
        'frame_idx': 150,
        'total_frames': 600,
        'plate_log': [
          {
            'frame': 30,
            'time': '1.00s',
            'time_sec': 1.0,
            'plate_text': '12b34567',
            'dtrb_text': '12b34567',
            'confidence': 0.92,
            'bbox': [0.1, 0.3, 0.4, 0.5],
            'persian_display': '۱۲ ب ۳۴۵-۶۷',
            'is_valid_iranian': true,
            'metadata': {
              'classified': true,
              'category': 'Private',
              'category_display': 'شخصی (Private)',
              'color_scheme': 'white',
              'region_code': '11',
              'region_name': 'تهران (Tehran)',
              'special_note': null,
            },
          },
          {
            'frame': 60,
            'time': '2.00s',
            'time_sec': 2.0,
            'plate_text': 'invalid',
            'dtrb_text': 'invalid',
            'confidence': 0.3,
            'bbox': [0.2, 0.4, 0.5, 0.6],
            'persian_display': 'invalid',
            'is_valid_iranian': false,
            'metadata': null,
          },
        ],
        'live_detections': ['12b34567'],
      };

      final status = VideoTaskStatus.fromJson(json);

      expect(status.plateLog.length, 2);
      expect(status.plateLog[0], isA<EnhancedPlateLogEntry>());
      expect(status.plateLog[0].persianDisplay, '۱۲ ب ۳۴۵-۶۷');
      expect(status.plateLog[0].isValidIranian, true);
      expect(status.plateLog[0].metadata, isNotNull);
      expect(status.plateLog[0].metadata!.classified, true);
      expect(status.plateLog[0].metadata!.category, 'Private');
      expect(status.plateLog[0].metadata!.categoryDisplay, 'شخصی (Private)');
      expect(status.plateLog[0].metadata!.colorScheme, 'white');
      expect(status.plateLog[0].metadata!.regionCode, '11');
      expect(status.plateLog[0].metadata!.regionName, 'تهران (Tehran)');

      // Second entry is invalid — no metadata
      expect(status.plateLog[1].isValidIranian, false);
      expect(status.plateLog[1].metadata, isNull);
      expect(status.plateLog[1].persianDisplay, 'invalid');
    });

    test('handles empty plate_log gracefully', () {
      final json = {
        'status': 'processing',
        'frame_idx': 10,
        'total_frames': 100,
        'plate_log': [],
        'live_detections': [],
      };

      final status = VideoTaskStatus.fromJson(json);
      expect(status.plateLog, isEmpty);
    });

    test('handles missing plate_log key', () {
      final json = {
        'status': 'queued',
        'frame_idx': 0,
        'total_frames': 0,
      };

      final status = VideoTaskStatus.fromJson(json);
      expect(status.plateLog, isEmpty);
    });
  });

  group('RtspTaskStatus enhanced history parsing', () {
    test('parses enhanced history entries with metadata and count', () {
      final json = {
        'status': 'running',
        'history': [
          {
            'dtrb_text': '12b34567',
            'yolo_text': '12b34567',
            'confidence': 0.92,
            'first_seen': '14:30:05',
            'last_seen': '14:30:12',
            'count': 3,
            'persian_display': '۱۲ ب ۳۴۵-۶۷',
            'is_valid_iranian': true,
            'metadata': {
              'classified': true,
              'category': 'Private',
              'category_display': 'شخصی (Private)',
              'color_scheme': 'white',
              'region_code': '11',
              'region_name': 'تهران (Tehran)',
              'special_note': null,
            },
          },
        ],
        'live_detections': ['12b34567'],
      };

      final status = RtspTaskStatus.fromJson(json);

      expect(status.history.length, 1);
      expect(status.history[0], isA<EnhancedRtspHistoryEntry>());
      expect(status.history[0].dtrbText, '12b34567');
      expect(status.history[0].firstSeen, '14:30:05');
      expect(status.history[0].lastSeen, '14:30:12');
      expect(status.history[0].count, 3);
      expect(status.history[0].persianDisplay, '۱۲ ب ۳۴۵-۶۷');
      expect(status.history[0].isValidIranian, true);
      expect(status.history[0].metadata, isNotNull);
      expect(status.history[0].metadata!.classified, true);
      expect(status.history[0].metadata!.regionName, 'تهران (Tehran)');
    });

    test('handles missing enhanced fields with safe defaults', () {
      final json = {
        'status': 'running',
        'history': [
          {
            'dtrb_text': '12b34567',
            'yolo_text': '12b34567',
            'confidence': 0.85,
            'first_seen': '10:00:00',
            'last_seen': '10:00:05',
            'count': 2,
            // No persian_display, is_valid_iranian, or metadata fields
          },
        ],
        'live_detections': [],
      };

      final status = RtspTaskStatus.fromJson(json);

      expect(status.history[0].persianDisplay, '');
      expect(status.history[0].isValidIranian, false);
      expect(status.history[0].metadata, isNull);
      // Base fields still parsed correctly
      expect(status.history[0].dtrbText, '12b34567');
      expect(status.history[0].count, 2);
    });

    test('handles empty history', () {
      final json = {
        'status': 'running',
        'history': [],
        'live_detections': [],
      };

      final status = RtspTaskStatus.fromJson(json);
      expect(status.history, isEmpty);
    });
  });
}
