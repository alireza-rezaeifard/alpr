// lib/features/sessions/sessions_view.dart
// Sessions view — lists recent processing sessions with status, duration, and plate counts.
// Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/session_model.dart';
import '../../data/repositories/sessions_repo.dart';
import '../../core/api_client.dart';

// ── Providers ──────────────────────────────────────────────────────────────

final _sessionsRepoProvider = Provider((_) => SessionsRepo());

/// Fetches the 20 most recent sessions. Invalidate to refresh (Req 6.2).
final sessionsProvider = FutureProvider<List<SessionModel>>((ref) =>
    ref.read(_sessionsRepoProvider).getSessions(limit: 20));

// ── View ───────────────────────────────────────────────────────────────────

class SessionsView extends ConsumerWidget {
  const SessionsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sessionsAsync = ref.watch(sessionsProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Sessions'),
        actions: [
          // Req 6.2 — explicit refresh control
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(sessionsProvider),
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: sessionsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        // Req 6.6 — error indicator + retry; prior list is retained by the
        // FutureProvider until a new response arrives.
        error: (e, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, color: Colors.red, size: 48),
              const SizedBox(height: 12),
              Text(
                'Failed to load sessions: ${_errorMsg(e)}',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              ElevatedButton.icon(
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
                onPressed: () => ref.invalidate(sessionsProvider),
              ),
            ],
          ),
        ),
        data: (sessions) {
          if (sessions.isEmpty) {
            return const Center(child: Text('No sessions yet.'));
          }
          return ListView.builder(
            itemCount: sessions.length,
            itemBuilder: (ctx, i) => _SessionTile(sessions[i]),
          );
        },
      ),
    );
  }
}

// ── Session tile ───────────────────────────────────────────────────────────

class _SessionTile extends StatelessWidget {
  final SessionModel session;
  const _SessionTile(this.session);

  @override
  Widget build(BuildContext context) {
    // Req 6.3 — non-negative integer seconds when both timestamps present.
    // Req 6.4 — running indicator when endedAt is null.
    final duration = session.durationSeconds;
    final durationText = duration != null ? '${duration}s' : '⏱ running…';

    // Req 6.5 — visually distinct styles for running / done / error.
    final Color statusColor;
    switch (session.status) {
      case 'done':
        statusColor = Colors.green;
        break;
      case 'error':
        statusColor = Colors.red;
        break;
      case 'running':
        statusColor = Colors.orange;
        break;
      default:
        statusColor = Colors.grey;
    }

    // Req 6.1 — display start time, source type, status, total plates, duration.
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: ListTile(
        leading: Icon(_sourceIcon(session.sourceType)),
        title: Text(session.sourceFile ?? session.sourceType),
        subtitle: Text(
          '${_formatTimestamp(session.startedAt)}  •  '
          '${session.totalPlates} plates  •  $durationText',
          style: const TextStyle(fontSize: 12),
        ),
        trailing: _StatusBadge(
          label: session.status,
          color: statusColor,
        ),
      ),
    );
  }

  IconData _sourceIcon(String sourceType) {
    switch (sourceType) {
      case 'image':
        return Icons.image;
      case 'video':
        return Icons.video_file;
      default:
        return Icons.videocam; // rtsp / unknown
    }
  }

  /// Trims an ISO-8601 timestamp to "YYYY-MM-DD HH:MM:SS" for display.
  String _formatTimestamp(String ts) {
    if (ts.length >= 19) return ts.substring(0, 19).replaceFirst('T', ' ');
    return ts;
  }
}

// ── Status badge ───────────────────────────────────────────────────────────

class _StatusBadge extends StatelessWidget {
  final String label;
  final Color color;
  const _StatusBadge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.bold,
          fontSize: 12,
        ),
      ),
    );
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────

String _errorMsg(Object e) {
  if (e is ApiException) return e.failure.message;
  return e.toString();
}
