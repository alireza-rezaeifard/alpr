/// User account view model.
/// Validates: Requirements 2.x
class UserModel {
  final int id;
  final String username;
  final String role;
  final bool disabled;
  final String createdAt;

  const UserModel({
    required this.id,
    required this.username,
    required this.role,
    required this.disabled,
    required this.createdAt,
  });

  factory UserModel.fromJson(Map<String, dynamic> json) => UserModel(
        id: json['id'] as int,
        username: json['username'] as String,
        role: json['role'] as String,
        disabled: json['disabled'] as bool,
        createdAt: json['created_at'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'username': username,
        'role': role,
        'disabled': disabled,
        'created_at': createdAt,
      };

  /// Check if the account is enabled
  bool get isEnabled => !disabled;

  /// Check if the user is an Admin
  bool get isAdmin => role == 'Admin';

  /// Check if the user is an Operator
  bool get isOperator => role == 'Operator';

  /// Check if the user is a Viewer
  bool get isViewer => role == 'Viewer';

  UserModel copyWith({
    int? id,
    String? username,
    String? role,
    bool? disabled,
    String? createdAt,
  }) =>
      UserModel(
        id: id ?? this.id,
        username: username ?? this.username,
        role: role ?? this.role,
        disabled: disabled ?? this.disabled,
        createdAt: createdAt ?? this.createdAt,
      );
}
