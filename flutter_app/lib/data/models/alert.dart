/// An alert raised when a detection matches a watchlist entry.
/// Validates: Requirements 12.4
class Alert {
  final int id;
  final int detectionId;
  final int entryId;
  final String plateValue;
  final String createdAt;

  const Alert({
    required this.id,
    required this.detectionId,
    required this.entryId,
    required this.plateValue,
    required this.createdAt,
  });

  factory Alert.fromJson(Map<String, dynamic> json) => Alert(
        id: json['id'] as int,
        detectionId: json['detection_id'] as int,
        entryId: json['entry_id'] as int,
        plateValue: json['plate_value'] as String,
        createdAt: json['created_at'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'detection_id': detectionId,
        'entry_id': entryId,
        'plate_value': plateValue,
        'created_at': createdAt,
      };

  /// Get the alert's creation timestamp as DateTime
  DateTime? get timestamp {
    return DateTime.tryParse(createdAt);
  }

  /// Get time elapsed since alert creation
  Duration? get timeSinceCreated {
    final ts = timestamp;
    if (ts == null) return null;
    return DateTime.now().difference(ts);
  }

  Alert copyWith({
    int? id,
    int? detectionId,
    int? entryId,
    String? plateValue,
    String? createdAt,
  }) =>
      Alert(
        id: id ?? this.id,
        detectionId: detectionId ?? this.detectionId,
        entryId: entryId ?? this.entryId,
        plateValue: plateValue ?? this.plateValue,
        createdAt: createdAt ?? this.createdAt,
      );
}
