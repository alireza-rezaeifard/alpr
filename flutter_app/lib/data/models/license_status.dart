/// License activation state and limits.
/// Validates: Requirements 3.5
class LicenseStatus {
  final bool active;
  final String? expiry;
  final int? cameraLimit;
  final int configuredCameras;

  const LicenseStatus({
    required this.active,
    this.expiry,
    this.cameraLimit,
    required this.configuredCameras,
  });

  factory LicenseStatus.fromJson(Map<String, dynamic> json) => LicenseStatus(
        active: json['active'] as bool,
        expiry: json['expiry'] as String?,
        cameraLimit: json['camera_limit'] as int?,
        configuredCameras: json['configured_cameras'] as int,
      );

  Map<String, dynamic> toJson() => {
        'active': active,
        'expiry': expiry,
        'camera_limit': cameraLimit,
        'configured_cameras': configuredCameras,
      };

  /// Check if the license is expired
  bool get isExpired {
    if (!active || expiry == null) return true;
    final expiryDate = DateTime.tryParse(expiry!);
    if (expiryDate == null) return true;
    return DateTime.now().isAfter(expiryDate);
  }

  /// Check if the license is valid (active and not expired)
  bool get isValid => active && !isExpired;

  /// Check if camera limit has been reached
  bool get isAtLimit {
    if (cameraLimit == null) return false;
    return configuredCameras >= cameraLimit!;
  }

  /// Get remaining camera slots
  int get remainingSlots {
    if (cameraLimit == null) return 0;
    return (cameraLimit! - configuredCameras).clamp(0, cameraLimit!);
  }

  /// Get days until expiry (null if not active or no expiry date)
  int? get daysUntilExpiry {
    if (!active || expiry == null) return null;
    final expiryDate = DateTime.tryParse(expiry!);
    if (expiryDate == null) return null;
    final difference = expiryDate.difference(DateTime.now());
    return difference.inDays;
  }

  LicenseStatus copyWith({
    bool? active,
    String? expiry,
    int? cameraLimit,
    int? configuredCameras,
  }) =>
      LicenseStatus(
        active: active ?? this.active,
        expiry: expiry ?? this.expiry,
        cameraLimit: cameraLimit ?? this.cameraLimit,
        configuredCameras: configuredCameras ?? this.configuredCameras,
      );
}
