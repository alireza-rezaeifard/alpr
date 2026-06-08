// lib/features/sessions/sessions_view.dart
// Modern sessions view with clean card-based layout.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../shared/app_icons.dart';
import 'package:flutter_animate/flutter_animate.dart';
import '../../data/models/session_model.dart';
import '../../data/repositories/sessions_repo.dart';
import '../../core/api_client.dart';

// ── Providers ──────────────────────────────────────────────────────────────

final _sessionsRepoProvider = Provider((_) => SessionsRepo());

final sessionsProvider = FutureProvider<List<SessionModel>>((ref) =>
    ref.read(_sessionsRepoProvider).getSessions(limit: 20));

// ── View ───────────────────────────────────────────────────────────────────

class SessionsView extends ConsumerWidget {
  const SessionsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sessionsAsync = ref.watch(sessionsProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            _buildHeader(context, ref),
            const SizedBox(height: 24),
            // Content
            Expanded(
              child: sessionsAsync.when(
                loading: () => const Center(child: CircularProgressIndicator(strokeWidth: 2)),
                error: (e, _) => _ErrorState(
                  message: _errorMsg(e),
                  onRetry: () => ref.invalidate(sessionsProvider),
                ),
                data: (sessions) {
                  if (sessions.isEmpty) {
                    return Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(AppIcons.layers, size: 48, color: Colors.white.withOpacity(0.2)),
                          const SizedBox(height: 12),
                          Text('No sessions yet', style: TextStyle(color: Colors.white.withOpacity(0.4))),
                        ],
                      ),
                    );
                  }
                  return ListView.builder(
                    itemCount: sessions.length,
                    itemBuilder: (ctx, i) => _SessionCard(sessions[i])
                        .animate()
                        .fadeIn(duration: 300.ms, delay: (i * 50).ms)
                        .slideY(begin: 0.02),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context, WidgetRef ref) {
    return Row(
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Sessions',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Processing session history',
              style: TextStyle(fontSize: 14, color: Colors.white.withOpacity(0.5)),
            ),
          ],
        ),
        const Spacer(),
        _ActionButton(
          icon: AppIcons.refreshCw,
          label: 'Refresh',
          onTap: () => ref.invalidate(sessionsProvider),
        ),
      ],
    ).animate().fadeIn(duration: 400.ms);
  }
}

// ── Session card ───────────────────────────────────────────────────────────

class _SessionCard extends StatefulWidget {
  final SessionModel session;
  const _SessionCard(this.session);

  @override
  State<_SessionCard> createState() => _SessionCardState();
}

class _SessionCardState extends State<_SessionCard> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    final duration = session.durationSeconds;
    final durationText = duration != null ? _formatDuration(duration) : 'Running...';

    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: _hovered ? Colors.white.withOpacity(0.04) : const Color(0xFF111113),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white.withOpacity(0.06)),
        ),
        child: Row(
          children: [
            // Source icon
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: _sourceColor(session.sourceType).withOpacity(0.1),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(
                _sourceIcon(session.sourceType),
                size: 20,
                color: _sourceColor(session.sourceType),
              ),
            ),
            const SizedBox(width: 16),
            // Info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    session.sourceFile ?? session.sourceType,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                      color: Colors.white,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Icon(AppIcons.clock, size: 12, color: Colors.white.withOpacity(0.4)),
                      const SizedBox(width: 4),
                      Text(
                        _formatTimestamp(session.startedAt),
                        style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.4)),
                      ),
                      const SizedBox(width: 16),
                      Icon(AppIcons.timer, size: 12, color: Colors.white.withOpacity(0.4)),
                      const SizedBox(width: 4),
                      Text(
                        durationText,
                        style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.4)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            // Stats
            Row(
              children: [
                _MetricPill(
                  icon: AppIcons.creditCard,
                  value: '${session.totalPlates}',
                  color: const Color(0xFF3B82F6),
                ),
                const SizedBox(width: 8),
                _MetricPill(
                  icon: AppIcons.fingerprint,
                  value: '${session.uniquePlates}',
                  color: const Color(0xFF8B5CF6),
                ),
              ],
            ),
            const SizedBox(width: 16),
            // Status badge
            _StatusBadge(status: session.status),
          ],
        ),
      ),
    );
  }

  IconData _sourceIcon(String sourceType) {
    switch (sourceType) {
      case 'image': return AppIcons.image;
      case 'video': return AppIcons.video;
      default: return AppIcons.camera;
    }
  }

  Color _sourceColor(String sourceType) {
    switch (sourceType) {
      case 'image': return const Color(0xFF8B5CF6);
      case 'video': return const Color(0xFF06B6D4);
      default: return const Color(0xFF10B981);
    }
  }

  String _formatTimestamp(String ts) {
    if (ts.length >= 19) return ts.substring(0, 19).replaceFirst('T', ' ');
    return ts;
  }

  String _formatDuration(int seconds) {
    if (seconds < 60) return '${seconds}s';
    if (seconds < 3600) return '${seconds ~/ 60}m ${seconds % 60}s';
    return '${seconds ~/ 3600}h ${(seconds % 3600) ~/ 60}m';
  }
}

class _MetricPill extends StatelessWidget {
  final IconData icon;
  final String value;
  final Color color;
  const _MetricPill({required this.icon, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 4),
          Text(value, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color)),
        ],
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final String status;
  const _StatusBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    Color color;
    IconData icon;
    switch (status) {
      case 'done':
        color = const Color(0xFF10B981);
        icon = AppIcons.checkCircle;
        break;
      case 'error':
        color = const Color(0xFFEF4444);
        icon = AppIcons.xCircle;
        break;
      case 'running':
        color = const Color(0xFFF59E0B);
        icon = AppIcons.loader2;
        break;
      default:
        color = const Color(0xFF6B7280);
        icon = AppIcons.circle;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withOpacity(0.2)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 4),
          Text(
            status,
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color),
          ),
        ],
      ),
    );
  }
}

// ── Shared widgets ─────────────────────────────────────────────────────────

class _ActionButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const _ActionButton({required this.icon, required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.04),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.white.withOpacity(0.08)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: Colors.white.withOpacity(0.6)),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.6))),
          ],
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorState({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(AppIcons.alertCircle, size: 48, color: Colors.white.withOpacity(0.2)),
          const SizedBox(height: 12),
          Text(message, style: TextStyle(color: Colors.white.withOpacity(0.5))),
          const SizedBox(height: 12),
          TextButton.icon(
            icon: const Icon(AppIcons.refreshCw, size: 14),
            label: const Text('Retry'),
            onPressed: onRetry,
          ),
        ],
      ),
    );
  }
}

String _errorMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
