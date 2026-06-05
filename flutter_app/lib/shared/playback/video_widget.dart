// lib/shared/playback/video_widget.dart
// Cross-platform video widget.
// On Web: uses HtmlElementView with an HTML5 <video> tag via dart:ui_web.
// On Windows: placeholder until media_kit native libs are available.
// Requirements: 8.3, 10.7

import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'playback_controller.dart';

// Web-specific imports are conditionally used
import 'video_widget_web.dart' if (dart.library.io) 'video_widget_stub.dart'
    as platform_video;

/// Renders video from a [PlaybackController].
/// On Web, creates an HTML5 video element from the picked bytes.
/// On Windows, shows a placeholder (media_kit requires VS toolchain).
class VideoWidget extends StatelessWidget {
  final PlaybackController controller;
  const VideoWidget({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    return platform_video.buildVideoWidget(controller);
  }
}
