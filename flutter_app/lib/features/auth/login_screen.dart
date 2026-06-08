// lib/features/auth/login_screen.dart
// Persian RTL login screen built with Fluent UI.
// Calls the auth controller's login(username, password); on success the router's
// redirect guard navigates to the dashboard automatically.
// Requirements: 18.1, 18.2

import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/controllers/auth_controller.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _submitting = false;
  String? _errorMessage;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) return;

    final username = _usernameController.text.trim();
    final password = _passwordController.text;

    if (username.isEmpty || password.isEmpty) {
      setState(() => _errorMessage = 'نام کاربری و گذرواژه را وارد کنید.');
      return;
    }

    setState(() {
      _submitting = true;
      _errorMessage = null;
    });

    try {
      await ref
          .read(authControllerProvider.notifier)
          .login(username, password);
      // On success the router's redirect guard observes the auth state change
      // and navigates to the dashboard. Nothing else to do here.
    } catch (_) {
      if (mounted) {
        setState(() {
          _errorMessage = 'ورود ناموفق بود. نام کاربری یا گذرواژه نادرست است.';
        });
      }
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);

    return ScaffoldPage(
      content: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Card(
              padding: const EdgeInsets.all(32),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _BrandHeader(theme: theme),
                  const SizedBox(height: 28),
                  if (_errorMessage != null) ...[
                    InfoBar(
                      title: const Text('خطا'),
                      content: Text(_errorMessage!),
                      severity: InfoBarSeverity.error,
                      isLong: true,
                      onClose: () => setState(() => _errorMessage = null),
                    ),
                    const SizedBox(height: 16),
                  ],
                  InfoLabel(
                    label: 'نام کاربری',
                    child: TextBox(
                      controller: _usernameController,
                      placeholder: 'نام کاربری خود را وارد کنید',
                      textDirection: TextDirection.rtl,
                      enabled: !_submitting,
                      autofocus: true,
                      onSubmitted: (_) => _submit(),
                    ),
                  ),
                  const SizedBox(height: 16),
                  InfoLabel(
                    label: 'گذرواژه',
                    child: PasswordBox(
                      controller: _passwordController,
                      placeholder: 'گذرواژه خود را وارد کنید',
                      enabled: !_submitting,
                      onSubmitted: (_) => _submit(),
                    ),
                  ),
                  const SizedBox(height: 24),
                  SizedBox(
                    height: 40,
                    child: FilledButton(
                      onPressed: _submitting ? null : _submit,
                      child: _submitting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: ProgressRing(strokeWidth: 2.5),
                            )
                          : const Text('ورود'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _BrandHeader extends StatelessWidget {
  const _BrandHeader({required this.theme});

  final FluentThemeData theme;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          width: 56,
          height: 56,
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [Color(0xFF0078D4), Color(0xFF106EBE)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: BorderRadius.circular(12),
          ),
          child: const Icon(
            FluentIcons.number_symbol,
            color: Colors.white,
            size: 28,
          ),
        ),
        const SizedBox(height: 16),
        Text(
          'سامانه تشخیص پلاک خودرو',
          textAlign: TextAlign.center,
          style: theme.typography.subtitle?.copyWith(
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          'برای ادامه وارد حساب کاربری خود شوید',
          textAlign: TextAlign.center,
          style: theme.typography.caption?.copyWith(
            color: const Color(0xFF9CA3AF),
          ),
        ),
      ],
    );
  }
}
