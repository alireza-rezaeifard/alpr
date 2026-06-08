// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'session_provider.dart';

// **************************************************************************
// RiverpodGenerator
// **************************************************************************

String _$sessionInfoHash() => r'0f662ca2f270eff6d1ecbc2390cec43c40a74dab';

/// Provider that tracks the current session state.
/// Returns SessionInfo if a valid session exists, null otherwise.
///
/// Copied from [sessionInfo].
@ProviderFor(sessionInfo)
final sessionInfoProvider = AutoDisposeProvider<SessionInfo?>.internal(
  sessionInfo,
  name: r'sessionInfoProvider',
  debugGetCreateSourceHash:
      const bool.fromEnvironment('dart.vm.product') ? null : _$sessionInfoHash,
  dependencies: null,
  allTransitiveDependencies: null,
);

@Deprecated('Will be removed in 3.0. Use Ref instead')
// ignore: unused_element
typedef SessionInfoRef = AutoDisposeProviderRef<SessionInfo?>;
String _$isSessionValidHash() => r'43a794277117b97d698dd30f716f7f09316c3794';

/// Provider for checking if session is valid
///
/// Copied from [isSessionValid].
@ProviderFor(isSessionValid)
final isSessionValidProvider = AutoDisposeProvider<bool>.internal(
  isSessionValid,
  name: r'isSessionValidProvider',
  debugGetCreateSourceHash: const bool.fromEnvironment('dart.vm.product')
      ? null
      : _$isSessionValidHash,
  dependencies: null,
  allTransitiveDependencies: null,
);

@Deprecated('Will be removed in 3.0. Use Ref instead')
// ignore: unused_element
typedef IsSessionValidRef = AutoDisposeProviderRef<bool>;
String _$isSessionExpiringSoonHash() =>
    r'527659013eea7ebcd74111c69f017b83a3c058d9';

/// Provider for checking if session is expiring soon
///
/// Copied from [isSessionExpiringSoon].
@ProviderFor(isSessionExpiringSoon)
final isSessionExpiringSoonProvider = AutoDisposeProvider<bool>.internal(
  isSessionExpiringSoon,
  name: r'isSessionExpiringSoonProvider',
  debugGetCreateSourceHash: const bool.fromEnvironment('dart.vm.product')
      ? null
      : _$isSessionExpiringSoonHash,
  dependencies: null,
  allTransitiveDependencies: null,
);

@Deprecated('Will be removed in 3.0. Use Ref instead')
// ignore: unused_element
typedef IsSessionExpiringSoonRef = AutoDisposeProviderRef<bool>;
String _$sessionTimeRemainingHash() =>
    r'3a76eb0c37a442b051371864f6f21b8b3b3b2b67';

/// Provider for session time remaining
///
/// Copied from [sessionTimeRemaining].
@ProviderFor(sessionTimeRemaining)
final sessionTimeRemainingProvider = AutoDisposeProvider<Duration>.internal(
  sessionTimeRemaining,
  name: r'sessionTimeRemainingProvider',
  debugGetCreateSourceHash: const bool.fromEnvironment('dart.vm.product')
      ? null
      : _$sessionTimeRemainingHash,
  dependencies: null,
  allTransitiveDependencies: null,
);

@Deprecated('Will be removed in 3.0. Use Ref instead')
// ignore: unused_element
typedef SessionTimeRemainingRef = AutoDisposeProviderRef<Duration>;
// ignore_for_file: type=lint
// ignore_for_file: subtype_of_sealed_class, invalid_use_of_internal_member, invalid_use_of_visible_for_testing_member, deprecated_member_use_from_same_package
