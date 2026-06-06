// lib/shared/playback/playback_controller.dart
// Platform-abstracted video player.
// On Web: uses HTML5 video element via HtmlElementView.
// On Windows: uses media_kit (requires native libs).
// Playback rate is ALWAYS 1.0x regardless of skip_frames (Req 8.3, 10.7).

import 'dart:typed_data';

/// Wraps video playback with a fixed 1.0x rate.
/// On Web, stores the bytes and creates a blob URL for the HTML video element.
/// On Windows, delegates to media_kit.
class PlaybackController {
  String? _blobUrl;
  Uint8List? _videoBytes;
  String? _localPath;
  bool _isPlaying = false;

  /// Bound by the web video widget so overlays can sync to playback time.
  double Function()? _currentTimeGetter;
  double Function()? _durationGetter;

  /// Always 1.0x — never modified by sampling interval (Req 8.3, 10.7).
  double get playbackRate => 1.0;

  /// The source URL for the video (blob URL on web, file path on desktop).
  String? get sourceUrl => _blobUrl ?? _localPath;

  /// The raw bytes (available on web after openBytes).
  Uint8List? get videoBytes => _videoBytes;

  bool get isPlaying => _isPlaying;

  /// Current playback position in seconds (0.0 when not bound).
  double get currentTime => _currentTimeGetter?.call() ?? 0.0;

  /// Total duration in seconds (0.0 when unknown).
  double get duration => _durationGetter?.call() ?? 0.0;

  /// Called by the platform video widget to expose live playback position.
  void bindTimeGetters(
    double Function() currentTime,
    double Function() duration,
  ) {
    _currentTimeGetter = currentTime;
    _durationGetter = duration;
  }

  /// Open a local file path (Windows desktop).
  Future<void> open(String path) async {
    _localPath = path;
    _isPlaying = false;
  }

  /// Open from raw bytes (Web file picker result).
  Future<void> openBytes(Uint8List bytes, String mimeType) async {
    _videoBytes = bytes;
    _isPlaying = false;
    // Blob URL creation is handled in the widget layer on web
  }

  void play() {
    _isPlaying = true;
  }

  void pause() {
    _isPlaying = false;
  }

  void stop() {
    _isPlaying = false;
  }

  void dispose() {
    _videoBytes = null;
    _blobUrl = null;
    _localPath = null;
    _currentTimeGetter = null;
    _durationGetter = null;
  }
}
