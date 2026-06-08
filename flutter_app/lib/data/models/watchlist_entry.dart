/// A single plate entry within a watchlist.
/// Validates: Requirements 12.2
class WatchlistEntry {
  final int id;
  final int watchlistId;
  final String plateValue;
  final String? label;
  final String? reason;
  final String createdAt;

  const WatchlistEntry({
    required this.id,
    required this.watchlistId,
    required this.plateValue,
    this.label,
    this.reason,
    required this.createdAt,
  });

  factory WatchlistEntry.fromJson(Map<String, dynamic> json) =>
      WatchlistEntry(
        id: json['id'] as int,
        watchlistId: json['watchlist_id'] as int,
        plateValue: json['plate_value'] as String,
        label: json['label'] as String?,
        reason: json['reason'] as String?,
        createdAt: json['created_at'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'watchlist_id': watchlistId,
        'plate_value': plateValue,
        'label': label,
        'reason': reason,
        'created_at': createdAt,
      };

  /// Check if the entry has a label
  bool get hasLabel => label != null && label!.isNotEmpty;

  /// Check if the entry has a reason
  bool get hasReason => reason != null && reason!.isNotEmpty;

  WatchlistEntry copyWith({
    int? id,
    int? watchlistId,
    String? plateValue,
    String? label,
    String? reason,
    String? createdAt,
  }) =>
      WatchlistEntry(
        id: id ?? this.id,
        watchlistId: watchlistId ?? this.watchlistId,
        plateValue: plateValue ?? this.plateValue,
        label: label ?? this.label,
        reason: reason ?? this.reason,
        createdAt: createdAt ?? this.createdAt,
      );
}
