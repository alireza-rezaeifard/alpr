// lib/features/detection/detection_view.dart
// Detection view with Image / Video / RTSP tab selector.
// Requirements: 7.1–7.10, 8.1–8.12, 9.2, 9.3, 9.4, 10.1–10.7

import 'package:flutter/material.dart';
import 'image_sub_view.dart';
import 'video_sub_view.dart';
import 'rtsp_sub_view.dart';

class DetectionView extends StatefulWidget {
  const DetectionView({super.key});

  @override
  State<DetectionView> createState() => _DetectionViewState();
}

class _DetectionViewState extends State<DetectionView>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Detection'),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(icon: Icon(Icons.image), text: 'Image'),
            Tab(icon: Icon(Icons.video_file), text: 'Video'),
            Tab(icon: Icon(Icons.videocam), text: 'RTSP'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        // Prevent swipe from discarding ongoing detections
        physics: const NeverScrollableScrollPhysics(),
        children: const [
          ImageSubView(),
          VideoSubView(),
          RtspSubView(),
        ],
      ),
    );
  }
}
