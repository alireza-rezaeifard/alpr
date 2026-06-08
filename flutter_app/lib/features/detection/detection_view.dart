// lib/features/detection/detection_view.dart
// Modern detection view with sleek tab selector.

import 'package:flutter/material.dart';
import '../../shared/app_icons.dart';
import 'package:flutter_animate/flutter_animate.dart';
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
    _tabController.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header + tabs
            Row(
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Detection',
                      style: TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                        letterSpacing: -0.5,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Detect license plates from images, videos, or live streams',
                      style: TextStyle(fontSize: 14, color: Colors.white.withOpacity(0.5)),
                    ),
                  ],
                ),
              ],
            ).animate().fadeIn(duration: 400.ms),
            const SizedBox(height: 20),
            // Tab bar
            _ModernTabBar(controller: _tabController),
            const SizedBox(height: 20),
            // Tab content
            Expanded(
              child: TabBarView(
                controller: _tabController,
                physics: const NeverScrollableScrollPhysics(),
                children: const [
                  ImageSubView(),
                  VideoSubView(),
                  RtspSubView(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ModernTabBar extends StatelessWidget {
  final TabController controller;
  const _ModernTabBar({required this.controller});

  @override
  Widget build(BuildContext context) {
    final tabs = [
      (AppIcons.image, 'Image'),
      (AppIcons.video, 'Video'),
      (AppIcons.radio, 'RTSP Stream'),
    ];

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.04),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: tabs.asMap().entries.map((e) {
          final isSelected = controller.index == e.key;
          return GestureDetector(
            onTap: () => controller.animateTo(e.key),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                color: isSelected ? const Color(0xFF3B82F6).withOpacity(0.15) : Colors.transparent,
                borderRadius: BorderRadius.circular(7),
                border: isSelected
                    ? Border.all(color: const Color(0xFF3B82F6).withOpacity(0.3))
                    : null,
              ),
              child: Row(
                children: [
                  Icon(
                    e.value.$1,
                    size: 16,
                    color: isSelected ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.4),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    e.value.$2,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: isSelected ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.5),
                    ),
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    ).animate().fadeIn(duration: 400.ms, delay: 100.ms);
  }
}
