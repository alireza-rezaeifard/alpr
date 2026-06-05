// lib/shared/playback/video_widget_stub.dart
// Desktop (non-web) stub. On Windows with proper VS toolchain, this would use media_kit.
// For now shows the file name and a placeholder.

import 'package:flutter/material.dart';
import 'playback_controller.dart';

Widget buildVideoWidget(PlaybackController controller) {
  final path = controller.sourceUrl;
  return Center(
    child: Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.video_file, size: 64, color: Colors.grey),
        const SizedBox(height: 12),
        if (path != null)
          Text(
            'Playing: $path',
            style: const TextStyle(color: Colors.grey, fontSize: 12),
            textAlign: TextAlign.center,
          )
        else
          const Text(
            'Video playback requires Visual Studio C++ toolchain.\n'
            'Use Chrome (web) for full video support.',
            style: TextStyle(color: Colors.grey, fontSize: 12),
            textAlign: TextAlign.center,
          ),
      ],
    ),
  );
}
