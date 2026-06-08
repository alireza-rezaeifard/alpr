import 'watchlist_entry.dart';

/// A watchlist with its plate entries.
/// Validates: Requirements 12.1
class Watchlist {
  final int id;
  final String name;
  final String listType;
  final String createdAt;
  final List<WatchlistEntry> entries;

  const Watchlist({
    required this.id,
    required this.name,
    required this.listType,
    required this.createdAt,
    this.entries = const [],
  });

  factory Watchlist.fromJson(Map<String, dynamic> json) => Watchlist(
        id: json['id'] as int,
        name: json['name'] as String,
        listType: json['list_type'] as String,
        createdAt: json['created_at'] as String,
        entries: (json['entries'] as List<dynamic>?)
                ?.map((e) =>
                    WatchlistEntry.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'list_type': listType,
        'created_at': createdAt,
        'entries': entries.map((e) => e.toJson()).toList(),
      };

  /// Check if this is a blocklist
  bool get isBlocklist => listType.toLowerCase() == 'blocklist';

  /// Check if this is an allowlist
  bool get isAllowlist => listType.toLowerCase() == 'allowlist';

  /// Get the total number of entries
  int get entryCount => entries.length;

  /// Check if the watchlist is empty
  bool get isEmpty => entries.isEmpty;

  /// Check if the watchlist has entries
  bool get isNotEmpty => entries.isNotEmpty;

  Watchlist copyWith({
    int? id,
    String? name,
    String? listType,
    String? createdAt,
    List<WatchlistEntry>? entries,
  }) =>
      Watchlist(
        id: id ?? this.id,
        name: name ?? this.name,
        listType: listType ?? this.listType,
        createdAt: createdAt ?? this.createdAt,
        entries: entries ?? this.entries,
      );
}
