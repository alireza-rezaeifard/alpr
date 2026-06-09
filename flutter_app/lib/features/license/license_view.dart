// lib/features/license/license_view.dart
// License screen: shows current license status and (for authorized roles)
// allows activating a license key. The activation control is hidden when the
// current role lacks the `manage_licenses` permission.
// Requirements: 3.1, 3.2, 3.5, 18.4

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/persian_format.dart';
import '../../data/controllers/licenses_controller.dart';
import '../../data/models/license_status.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/permission_gate.dart';

class LicenseView extends ConsumerStatefulWidget {
  const LicenseView({super.key});

  @override
  ConsumerState<LicenseView> createState() => _LicenseViewState();
}

class _LicenseViewState extends ConsumerState<LicenseView> {
  final _keyController = TextEditingController();

  @override
  void initState() {
    super.initState();
    // Load current status once the first frame is scheduled.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(licensesControllerProvider.notifier).loadStatus();
    });
  }

  @override
  void dispose() {
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _activate() async {
    final key = _keyController.text.trim();
    if (key.isEmpty) return;
    try {
      await ref.read(licensesControllerProvider.notifier).activateLicense(key);
      _keyController.clear();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('مجوز با موفقیت فعال شد')),
        );
      }
    } catch (_) {
      // Error is surfaced via the controller state banner below.
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(licensesControllerProvider);
    final status = state.status;

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _Header(),
            const SizedBox(height: 20),
            if (state.error != null) ...[
              _ErrorBanner(message: state.error!),
              const SizedBox(height: 12),
            ],
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _StatusCard(status: status, loading: state.loading),
                    const SizedBox(height: 16),
                    // Activation is only available to roles that may manage licenses.
                    PermissionGate(
                      permission: Permissions.manageLicenses,
                      fallback: const _NoActivationPermissionCard(),
                      child: _ActivationCard(
                        controller: _keyController,
                        loading: state.loading,
                        onActivate: _activate,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'مجوز',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            color: Colors.white,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          'وضعیت مجوز و فعال‌سازی کلید مجوز',
          style: TextStyle(fontSize: 14, color: Colors.white.withOpacity(0.5)),
        ),
      ],
    );
  }
}

class _StatusCard extends StatelessWidget {
  final LicenseStatus? status;
  final bool loading;
  const _StatusCard({required this.status, required this.loading});

  @override
  Widget build(BuildContext context) {
    final active = status?.isValid ?? false;
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(AppIcons.fingerprint, size: 16, color: Colors.white.withOpacity(0.5)),
              const SizedBox(width: 8),
              const Text(
                'وضعیت مجوز',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: Colors.white,
                ),
              ),
              const Spacer(),
              if (loading)
                SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white.withOpacity(0.4),
                  ),
                )
              else
                _StatusPill(active: active),
            ],
          ),
          const SizedBox(height: 16),
          if (status == null && !loading)
            Text(
              'اطلاعات مجوز در دسترس نیست.',
              style: TextStyle(fontSize: 13, color: Colors.white.withOpacity(0.4)),
            )
          else if (status != null) ...[
            _InfoRow(
              label: 'تاریخ انقضا',
              value: status!.expiry != null
                  ? PersianFormat.date(
                      DateTime.tryParse(status!.expiry!) ?? DateTime.now())
                  : '—',
            ),
            _InfoRow(
              label: 'سقف دوربین‌ها',
              value: status!.cameraLimit != null
                  ? PersianFormat.number(status!.cameraLimit!)
                  : 'نامحدود',
            ),
            _InfoRow(
              label: 'دوربین‌های پیکربندی‌شده',
              value: PersianFormat.number(status!.configuredCameras),
            ),
            if (status!.daysUntilExpiry != null)
              _InfoRow(
                label: 'روزهای باقی‌مانده',
                value: PersianFormat.number(status!.daysUntilExpiry!.clamp(0, 1 << 31)),
              ),
          ],
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  final bool active;
  const _StatusPill({required this.active});

  @override
  Widget build(BuildContext context) {
    final color = active ? const Color(0xFF10B981) : const Color(0xFFEF4444);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(active ? AppIcons.checkCircle : AppIcons.xCircle, size: 13, color: color),
          const SizedBox(width: 6),
          Text(
            active ? 'فعال' : 'غیرفعال',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color),
          ),
        ],
      ),
    );
  }
}

class _ActivationCard extends StatelessWidget {
  final TextEditingController controller;
  final bool loading;
  final VoidCallback onActivate;
  const _ActivationCard({
    required this.controller,
    required this.loading,
    required this.onActivate,
  });

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'فعال‌سازی مجوز',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'کلید مجوز خود را وارد کنید',
            style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.4)),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: controller,
            enabled: !loading,
            maxLines: 2,
            minLines: 1,
            style: const TextStyle(color: Colors.white, fontSize: 13),
            decoration: InputDecoration(
              hintText: 'کلید مجوز',
              hintStyle: TextStyle(color: Colors.white.withOpacity(0.3)),
              filled: true,
              fillColor: Colors.white.withOpacity(0.03),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide(color: Colors.white.withOpacity(0.08)),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: const BorderSide(color: Color(0xFF3B82F6)),
              ),
              disabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide(color: Colors.white.withOpacity(0.04)),
              ),
            ),
          ),
          const SizedBox(height: 12),
          _PrimaryButton(
            icon: loading ? AppIcons.loader2 : AppIcons.checkCircle,
            label: loading ? 'در حال فعال‌سازی…' : 'فعال‌سازی',
            onTap: loading ? null : onActivate,
          ),
        ],
      ),
    );
  }
}

class _NoActivationPermissionCard extends StatelessWidget {
  const _NoActivationPermissionCard();

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Row(
        children: [
          Icon(AppIcons.alertCircle, size: 16, color: Colors.white.withOpacity(0.4)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              'شما اجازه فعال‌سازی مجوز را ندارید. تنها مدیر می‌تواند مجوز را فعال کند.',
              style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.5)),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Shared building blocks ───────────────────────────────────────────────

class _Card extends StatelessWidget {
  final Widget child;
  const _Card({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111113),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: child,
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  const _InfoRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Text(label, style: TextStyle(fontSize: 13, color: Colors.white.withOpacity(0.5))),
          const Spacer(),
          Text(
            value,
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Colors.white),
          ),
        ],
      ),
    );
  }
}

class _PrimaryButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  const _PrimaryButton({required this.icon, required this.label, this.onTap});

  @override
  Widget build(BuildContext context) {
    const color = Color(0xFF3B82F6);
    final enabled = onTap != null;
    return GestureDetector(
      onTap: onTap,
      child: MouseRegion(
        cursor: enabled ? SystemMouseCursors.click : SystemMouseCursors.basic,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
          decoration: BoxDecoration(
            color: enabled ? color.withOpacity(0.12) : Colors.white.withOpacity(0.02),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: enabled ? color.withOpacity(0.3) : Colors.white.withOpacity(0.04),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: enabled ? color : Colors.white.withOpacity(0.3)),
              const SizedBox(width: 8),
              Text(
                label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: enabled ? color : Colors.white.withOpacity(0.3),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;
  const _ErrorBanner({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFEF4444).withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.2)),
      ),
      child: Row(
        children: [
          const Icon(AppIcons.alertCircle, size: 14, color: Color(0xFFEF4444)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(message, style: const TextStyle(fontSize: 12, color: Color(0xFFEF4444))),
          ),
        ],
      ),
    );
  }
}
