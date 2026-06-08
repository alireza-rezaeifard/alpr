/// An append-only audit log entry recording security-relevant actions.
/// Validates: Requirements 15.2
class AuditEntry {
  final int id;
  final String? username;
  final String action;
  final String? resource;
  final String outcome;
  final String timestamp;

  const AuditEntry({
    required this.id,
    this.username,
    required this.action,
    this.resource,
    required this.outcome,
    required this.timestamp,
  });

  factory AuditEntry.fromJson(Map<String, dynamic> json) => AuditEntry(
        id: json['id'] as int,
        username: json['username'] as String?,
        action: json['action'] as String,
        resource: json['resource'] as String?,
        outcome: json['outcome'] as String,
        timestamp: json['timestamp'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'username': username,
        'action': action,
        'resource': resource,
        'outcome': outcome,
        'timestamp': timestamp,
      };

  /// Check if the action was successful
  bool get wasSuccessful =>
      outcome.toLowerCase() == 'success' || outcome.toLowerCase() == 'succeeded';

  /// Check if the action failed
  bool get wasFailed =>
      outcome.toLowerCase() == 'failed' || outcome.toLowerCase() == 'failure';

  /// Get the audit timestamp as DateTime
  DateTime? get timestampDate {
    return DateTime.tryParse(timestamp);
  }

  /// Check if the entry has a username
  bool get hasUsername => username != null && username!.isNotEmpty;

  /// Check if the entry has a resource
  bool get hasResource => resource != null && resource!.isNotEmpty;

  AuditEntry copyWith({
    int? id,
    String? username,
    String? action,
    String? resource,
    String? outcome,
    String? timestamp,
  }) =>
      AuditEntry(
        id: id ?? this.id,
        username: username ?? this.username,
        action: action ?? this.action,
        resource: resource ?? this.resource,
        outcome: outcome ?? this.outcome,
        timestamp: timestamp ?? this.timestamp,
      );
}
