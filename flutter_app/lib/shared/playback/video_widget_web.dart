// lib/shared/playback/video_widget_web.dart
// Web implementation: HTML5 <video> element via dart:ui_web.

import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;
import 'dart:js_interop';
import 'package:web/web.dart' as web;
import 'package:flutter/material.dart';
import 'playback_controller.dart';

int _viewIdCounter = 0;

Widget buildVideoWidget(PlaybackController controller) {
  final bytes = controller.videoBytes;
  if (bytes == null || bytes.isEmpty) {
    return const Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.video_library_outlined, size: 48, color: Colors.grey),
          SizedBox(height: 8),
          Text('No video loaded', style: TextStyle(color: Colors.grey)),
        ],
      ),
    );
  }

  return _WebVideoPlayer(key: ValueKey(bytes.hashCode), bytes: bytes);
}

class _WebVideoPlayer extends StatefulWidget {
  final Uint8List bytes;
  const _WebVideoPlayer({super.key, required this.bytes});

  @override
  State<_WebVideoPlayer> createState() => _WebVideoPlayerState();
}

class _WebVideoPlayerState extends State<_WebVideoPlayer> {
  late final String _viewType;

  @override
  void initState() {
    super.initState();
    _viewIdCounter++;
    _viewType = 'plpr-video-player-$_viewIdCounter';

    // Create a Blob URL from the video bytes
    final blob = web.Blob(
      [widget.bytes.toJS].toJS,
      web.BlobPropertyBag(type: 'video/mp4'),
    );
    final blobUrl = web.URL.createObjectURL(blob);

    // Register the HTML element factory
    ui_web.platformViewRegistry.registerViewFactory(
      _viewType,
      (int viewId, {Object? params}) {
        final video = web.document.createElement('video') as web.HTMLVideoElement;
        video.src = blobUrl;
        video.autoplay = true;
        video.controls = true;
        video.loop = true;
        video.muted = true; // Autoplay requires muted in most browsers
        video.style.width = '100%';
        video.style.height = '100%';
        video.style.objectFit = 'contain';
        video.style.backgroundColor = '#000';
        video.playbackRate = 1.0;
        return video;
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return HtmlElementView(viewType: _viewType);
  }
}
