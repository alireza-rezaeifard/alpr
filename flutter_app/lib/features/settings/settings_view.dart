// lib/features/settings/settings_view.dart
// Settings screen: camera-processing concurrency limit and detection retention
// policy. Editing controls are hidden when the current role lacks the
// `manage_config` permission; the whole screen falls back to a denied view for
// roles without that permission.
// Requirements: 5.6, 16.1, 18.4

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/persian_format.dart';
import '../../data/controllers/cameras_controller.dart';
import '../../data/controllers/reports_controller.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/permission_gate.dart';

class SettingsView extends ConsumerWidget {
  const SettingsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return const Scaffold(
      backgroundColor: Colors.transparent,
      body: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _Header(),
            SizedBox(height: 20),
            Expanded(
              // The entire settings surface is configuration management, so it
              // is gated behind `manage_config`; other roles see a denied view.
              child: PermissionGate(
                permission: Permissions.manageConfig,
                fallback: PermissionDeniedView(
                  message: 'تنظیمات سامانه تنها برای مدیر در دسترس است.',
                ),
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _ConcurrencyCard(),
                      SizedBox(height: 16),
                      _RetentionCard(),
                    ],
                  ),
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
          'تنظیمات',
          style: TextStyle(fontSize: 28, fontWeight: FontWeight.w700, color: Colors.white),
        ),
        const SizedBox(height: 4),
        Text(
          'پیکربندی همزمانی پردازش دوربین و سیاست نگهداری داده‌ها',
          style: TextStyle(fontSize: 14, color: Colors.white.withOpacity(0.5)),
        ),
      ],
    );
  }
}

// ── Concurrency limit (1..64) ─────────────────────────────────────────────

class _ConcurrencyCard extends ConsumerStatefulWidget {
  const _ConcurrencyCard();

  @override
  ConsumerState<_ConcurrencyCard> createState() => _ConcurrencyCardState();
}

class _ConcurrencyCardState extends ConsumerState<_ConcurrencyCard> {
  final _controller = TextEditingController();
  String? _validationError;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(camerasControllerProvider.notifier).loadConcurrencyLimit();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final value = int.tryParse(_controller.text.trim());
    if (value == null || value < 1 || value > 64) {
      setState(() => _validationError = 'مقدار باید بین ۱ تا ۶۴ باشد');
      return;
    }
    setState(() => _validationError = null);
    try {
      await ref.read(camerasControllerProvider.notifier).setConcurrencyLimit(value);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('سقف همزمانی ذخیره شد')),
        );
      }
    } catch (_) {
      // surfaced via state.error
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(camerasControllerProvider);
    final current = state.concurrencyLimit;

    return _SettingCard(
      icon: AppIcons.layers,
      title: 'سقف همزمانی پردازش',
      subtitle: 'حداکثر تعداد دوربین‌هایی که هم‌زمان پردازش می‌شوند (۱ تا ۶۴)',
      children: [
        _InfoRow(
          label: 'مقدار فعلی',
          value: current != null ? PersianFormat.number(current) : '—',
        ),
        const SizedBox(height: 12),
        _NumberField(
          controller: _controller,
          hint: 'مقدار جدید (۱ تا ۶۴)',
          enabled: !state.loading,
          errorText: _validationError,
        ),
        const SizedBox(height: 12),
        _PrimaryButton(
          icon: state.loading ? AppIcons.loader2 : AppIcons.checkCircle,
          label: state.loading ? 'در حال ذخیره…' : 'ذخیره',
          onTap: state.loading ? null : _save,
        ),
        if (state.error != null) ...[
          const SizedBox(height: 12),
          _ErrorBanner(message: state.error!),
        ],
      ],
    );
  }
}

// ── Retention policy (days > 0) ───────────────────────────────────────────

class _RetentionCard extends ConsumerStatefulWidget {
  const _RetentionCard();

  @override
  ConsumerState<_RetentionCard> createState() => _RetentionCardState();
}

class _RetentionCardState extends ConsumerState<_RetentionCard> {
  final _controller = TextEditingController();
  String? _validationError;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(reportsControllerProvider.notifier).loadRetentionPolicy();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final value = int.tryParse(_controller.text.trim());
    if (value == null || value < 1) {
      setState(() => _validationError = 'تعداد روز باید بزرگ‌تر از صفر باشد');
      return;
    }
    setState(() => _validationError = null);
    try {
      await ref.read(reportsControllerProvider.notifier).setRetentionPolicy(value);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('سیاست نگهداری ذخیره شد')),
        );
      }
    } catch (_) {
      // surfaced via state.error
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(reportsControllerProvider);
    final days = state.retentionConfig?.days;

    return _SettingCard(
      icon: AppIcons.history,
      title: 'سیاست نگهداری داده‌ها',
      subtitle: 'تشخیص‌های قدیمی‌تر از این تعداد روز حذف می‌شوند',
      children: [
        _InfoRow(
          label: 'سیاست فعلی',
          value: days != null ? '${PersianFormat.number(days)} روز' : 'بدون محدودیت',
        ),
        const SizedBox(height: 12),
        _NumberField(
          controller: _controller,
          hint: 'تعداد روز (بزرگ‌تر از صفر)',
          enabled: !state.loading,
          errorText: _validationError,
        ),
        const SizedBox(height: 12),
        _PrimaryButton(
          icon: state.loading ? AppIcons.loader2 : AppIcons.checkCircle,
          label: state.loading ? 'در حال ذخیره…' : 'ذخیره',
          onTap: state.loading ? null : _save,
        ),
        if (state.error != null) ...[
          const SizedBox(height: 12),
          _ErrorBanner(message: state.error!),
        ],
      ],
    );
  }
}

// ── Shared building blocks ────────────────────────────────────────────────

class _SettingCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final List<Widget> children;
  const _SettingCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.children,
  });

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
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: Colors.white.withOpacity(0.5)),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: Colors.white,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(subtitle, style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.4))),
          const SizedBox(height: 16),
          ...children,
        ],
      ),
    );
  }
}

class _NumberField extends StatelessWidget {
  final TextEditingController controller;
  final String hint;
  final bool enabled;
  final String? errorText;
  const _NumberField({
    required this.controller,
    required this.hint,
    required this.enabled,
    this.errorText,
  });

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      enabled: enabled,
      keyboardType: TextInputType.number,
      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
      style: const TextStyle(color: Colors.white, fontSize: 13),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: TextStyle(color: Colors.white.withOpacity(0.3)),
        errorText: errorText,
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
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  const _InfoRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(label, style: TextStyle(fontSize: 13, color: Colors.white.withOpacity(0.5))),
        const Spacer(),
        Text(
          value,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Colors.white),
        ),
      ],
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
