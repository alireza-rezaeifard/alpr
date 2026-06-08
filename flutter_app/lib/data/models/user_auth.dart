/// Authentication response model containing session token and user permissions.
/// Validates: Requirements 1.1, 2.x
class UserAuth {
  final String token;
  final String role;
  final String expiresAt;
  final List<String> permissions;

  const UserAuth({
    required this.token,
    required this.role,
    required this.expiresAt,
    required this.permissions,
  });

  factory UserAuth.fromJson(Map<String, dynamic> json) => UserAuth(
        token: json['token'] as String,
        role: json['role'] as String,
        expiresAt: json['expires_at'] as String,
        permissions: (json['permissions'] as List<dynamic>?)
                ?.map((e) => e as String)
                .toList() ??
            [],
      );

  Map<String, dynamic> toJson() => {
        'token': token,
        'role': role,
        'expires_at': expiresAt,
        'permissions': permissions,
      };

  /// Check if the session token has expired
  bool get isExpired {
    final expiry = DateTime.tryParse(expiresAt);
    if (expiry == null) return true;
    return DateTime.now().isAfter(expiry);
  }

  /// Check if the user has a specific permission
  bool hasPermission(String permission) => permissions.contains(permission);

  /// Check if the user is an Admin
  bool get isAdmin => role == 'Admin';

  /// Check if the user is an Operator
  bool get isOperator => role == 'Operator';

  /// Check if the user is a Viewer
  bool get isViewer => role == 'Viewer';

  UserAuth copyWith({
    String? token,
    String? role,
    String? expiresAt,
    List<String>? permissions,
  }) =>
      UserAuth(
        token: token ?? this.token,
        role: role ?? this.role,
        expiresAt: expiresAt ?? this.expiresAt,
        permissions: permissions ?? this.permissions,
      );
}
