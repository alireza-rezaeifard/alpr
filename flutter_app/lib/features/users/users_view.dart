// lib/features/users/users_view.dart
// User management (Admin) screen. Users are rendered with PlutoGrid
// (Requirement 17.5); management controls are gated by the manage_users
// permission (Requirement 18.4).

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pluto_grid/pluto_grid.dart';

import '../../core/persian_format.dart';
import '../../data/controllers/users_controller.dart';
import '../../data/models/user_model.dart';
import '../../shared/app_icons.dart';
import '../../shared/widgets/app_data_grid.dart';
import '../../shared/widgets/permission_gate.dart' show Permissions, PermissionDeniedView;
import '../../shared/widgets/screen_shell.dart';

const _roles = ['Admin', 'Operator', 'Viewer'];

String _roleLabel(String role) {
  switch (role) {
    case 'Admin':
      return 'مدیر';
    case 'Operator':
      return 'اپراتور';
    case 'Viewer':
      return 'بیننده';
    default:
      return role;
  }
}

class UsersView extends ConsumerStatefulWidget {
  const UsersView({super.key});

  @override
  ConsumerState<UsersView> createState() => _UsersViewState();
}

class _UsersViewState extends ConsumerState<UsersView> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(usersControllerProvider.notifier).loadUsers();
    });
  }

  @override
  Widget build(BuildContext context) {
    final canManage = sessionHasPermission(ref, Permissions.manageUsers);
    final state = ref.watch(usersControllerProvider);

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ScreenHeader(
            title: 'کاربران',
            subtitle: 'مدیریت حساب‌ها و نقش‌ها',
            actions: [
              ToolbarButton(
                icon: AppIcons.refreshCw,
                label: 'بازخوانی',
                onTap: () => ref.read(usersControllerProvider.notifier).loadUsers(),
              ),
              if (canManage) ...[
                const SizedBox(width: 8),
                ToolbarButton(
                  icon: AppIcons.plus,
                  label: 'کاربر جدید',
                  primary: true,
                  onTap: _showCreateUserDialog,
                ),
              ],
            ],
          ),
          const SizedBox(height: 20),
          Expanded(
            child: !canManage
                ? const PermissionDeniedView(
                    message: 'تنها مدیر می‌تواند کاربران را مدیریت کند.',
                  )
                : _buildBody(state),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(UsersState state) {
    if (state.loading && state.users.isEmpty) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }
    if (state.error != null && state.users.isEmpty) {
      return GridStatePlaceholder(
        icon: AppIcons.alertCircle,
        message: 'بارگیری کاربران ممکن نشد\n${state.error}',
        onRetry: () => ref.read(usersControllerProvider.notifier).loadUsers(),
      );
    }
    if (state.users.isEmpty) {
      return const GridStatePlaceholder(
        icon: AppIcons.fingerprint,
        message: 'کاربری یافت نشد.',
      );
    }
    return AppDataGrid(
      key: ValueKey('users_${state.users.length}'),
      columns: _columns(),
      rows: state.users.map(_rowFor).toList(),
    );
  }

  List<PlutoColumn> _columns() => [
        PlutoColumn(
          title: 'شناسه',
          field: 'id',
          type: PlutoColumnType.number(),
          width: 90,
          renderer: (ctx) => Text(
            PersianFormat.number(ctx.cell.value as num),
            style: const TextStyle(color: Color(0xFFFAFAFA), fontSize: 13),
          ),
        ),
        PlutoColumn(title: 'نام کاربری', field: 'username', type: PlutoColumnType.text(), minWidth: 160),
        PlutoColumn(
          title: 'نقش',
          field: 'role',
          type: PlutoColumnType.text(),
          width: 130,
          renderer: (ctx) => Text(
            _roleLabel(ctx.cell.value as String),
            style: const TextStyle(color: Color(0xFFFAFAFA), fontSize: 13, fontWeight: FontWeight.w500),
          ),
        ),
        PlutoColumn(
          title: 'وضعیت',
          field: 'status',
          type: PlutoColumnType.text(),
          width: 120,
          renderer: (ctx) {
            final enabled = ctx.cell.value == 'enabled';
            final color = enabled ? const Color(0xFF10B981) : const Color(0xFF6B7280);
            return Align(
              alignment: Alignment.centerRight,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: color.withValues(alpha: 0.3)),
                ),
                child: Text(
                  enabled ? 'فعال' : 'غیرفعال',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color),
                ),
              ),
            );
          },
        ),
        PlutoColumn(title: 'تاریخ ایجاد', field: 'created', type: PlutoColumnType.text(), minWidth: 160),
        PlutoColumn(
          title: 'عملیات',
          field: 'actions',
          type: PlutoColumnType.text(),
          width: 170,
          enableSorting: false,
          enableContextMenu: false,
          renderer: (ctx) {
            final cells = ctx.row.cells;
            final user = UserModel(
              id: cells['id']!.value as int,
              username: cells['username']!.value as String,
              role: cells['role']!.value as String,
              disabled: cells['status']!.value == 'disabled',
              createdAt: '',
            );
            return Align(
              alignment: Alignment.centerRight,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _IconBtn(icon: AppIcons.edit2, color: const Color(0xFF3B82F6), tooltip: 'تغییر نقش', onTap: () => _showEditRoleDialog(user)),
                  const SizedBox(width: 6),
                  _IconBtn(
                    icon: user.disabled ? AppIcons.checkCircle : AppIcons.xCircle,
                    color: user.disabled ? const Color(0xFF10B981) : const Color(0xFFF59E0B),
                    tooltip: user.disabled ? 'فعال‌سازی' : 'غیرفعال‌سازی',
                    onTap: () => ref.read(usersControllerProvider.notifier).updateUser(user.id, disabled: !user.disabled),
                  ),
                  const SizedBox(width: 6),
                  _IconBtn(icon: AppIcons.trash2, color: const Color(0xFFEF4444), tooltip: 'حذف', onTap: () => _confirmDelete(user)),
                ],
              ),
            );
          },
        ),
      ];

  PlutoRow _rowFor(UserModel u) => PlutoRow(cells: {
        'id': PlutoCell(value: u.id),
        'username': PlutoCell(value: u.username),
        'role': PlutoCell(value: u.role),
        'status': PlutoCell(value: u.disabled ? 'disabled' : 'enabled'),
        'created': PlutoCell(value: _formatTs(u.createdAt)),
        'actions': PlutoCell(value: u.id),
      });

  // ── Dialogs ────────────────────────────────────────────────────────────────

  Future<void> _showCreateUserDialog() async {
    final userCtrl = TextEditingController();
    final passCtrl = TextEditingController();
    String role = 'Viewer';
    String? error;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => _UserDialog(
          title: 'ایجاد کاربر',
          children: [
            _LabeledField(label: 'نام کاربری', controller: userCtrl, hint: 'نام کاربری'),
            const SizedBox(height: 12),
            _LabeledField(label: 'گذرواژه', controller: passCtrl, hint: 'گذرواژه اولیه', obscure: true),
            const SizedBox(height: 12),
            _RolePicker(value: role, onChanged: (r) => setLocal(() => role = r)),
            if (error != null) ...[
              const SizedBox(height: 10),
              Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
            ],
          ],
          onConfirm: () async {
            if (userCtrl.text.trim().isEmpty || passCtrl.text.isEmpty) {
              setLocal(() => error = 'نام کاربری و گذرواژه الزامی است');
              return;
            }
            try {
              await ref.read(usersControllerProvider.notifier).createUser(
                    username: userCtrl.text.trim(),
                    password: passCtrl.text,
                    role: role,
                  );
              if (ctx.mounted) Navigator.pop(ctx);
            } catch (e) {
              setLocal(() => error = e.toString());
            }
          },
        ),
      ),
    );
  }

  Future<void> _showEditRoleDialog(UserModel user) async {
    String role = user.role;
    final passCtrl = TextEditingController();
    String? error;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => _UserDialog(
          title: 'ویرایش «${user.username}»',
          children: [
            _RolePicker(value: role, onChanged: (r) => setLocal(() => role = r)),
            const SizedBox(height: 12),
            _LabeledField(label: 'گذرواژه جدید (اختیاری)', controller: passCtrl, hint: 'برای تغییر گذرواژه پر کنید', obscure: true),
            if (error != null) ...[
              const SizedBox(height: 10),
              Text(error!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12)),
            ],
          ],
          onConfirm: () async {
            try {
              await ref.read(usersControllerProvider.notifier).updateUser(
                    user.id,
                    role: role == user.role ? null : role,
                    password: passCtrl.text.isEmpty ? null : passCtrl.text,
                  );
              if (ctx.mounted) Navigator.pop(ctx);
            } catch (e) {
              setLocal(() => error = e.toString());
            }
          },
        ),
      ),
    );
  }

  Future<void> _confirmDelete(UserModel user) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => _UserDialog(
        title: 'حذف کاربر',
        confirmLabel: 'حذف',
        danger: true,
        children: [
          Text('آیا از حذف «${user.username}» مطمئن هستید؟',
              style: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 13)),
        ],
        onConfirm: () => Navigator.pop(ctx, true),
      ),
    );
    if (ok == true) {
      try {
        await ref.read(usersControllerProvider.notifier).deleteUser(user.id);
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.maybeOf(context)?.showSnackBar(
            SnackBar(content: Text('حذف ناموفق بود: $e'), backgroundColor: const Color(0xFF7F1D1D)),
          );
        }
      }
    }
  }
}

String _formatTs(String ts) {
  final dt = DateTime.tryParse(ts);
  if (dt == null) return ts;
  return PersianFormat.dateTime(dt);
}

// ── Small widgets ─────────────────────────────────────────────────────────────

class _RolePicker extends StatelessWidget {
  final String value;
  final ValueChanged<String> onChanged;
  const _RolePicker({required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('نقش', style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.6))),
        const SizedBox(height: 6),
        Row(
          children: [
            for (final r in _roles)
              Padding(
                padding: const EdgeInsets.only(left: 8),
                child: MouseRegion(
                  cursor: SystemMouseCursors.click,
                  child: GestureDetector(
                    onTap: () => onChanged(r),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                      decoration: BoxDecoration(
                        color: value == r ? const Color(0xFF3B82F6).withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.04),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: value == r ? const Color(0xFF3B82F6).withValues(alpha: 0.3) : Colors.white.withValues(alpha: 0.08)),
                      ),
                      child: Text(_roleLabel(r), style: TextStyle(fontSize: 12.5, color: value == r ? const Color(0xFF3B82F6) : Colors.white.withValues(alpha: 0.6))),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }
}

class _LabeledField extends StatelessWidget {
  final String label;
  final TextEditingController controller;
  final String hint;
  final bool obscure;
  const _LabeledField({required this.label, required this.controller, required this.hint, this.obscure = false});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.6))),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          obscureText: obscure,
          textDirection: TextDirection.rtl,
          style: const TextStyle(fontSize: 13, color: Colors.white),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.3)),
            filled: true,
            fillColor: Colors.white.withValues(alpha: 0.04),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
            ),
            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          ),
        ),
      ],
    );
  }
}

class _IconBtn extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String tooltip;
  final VoidCallback onTap;
  const _IconBtn({required this.icon, required this.color, required this.tooltip, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        child: GestureDetector(
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Icon(icon, size: 15, color: color),
          ),
        ),
      ),
    );
  }
}

class _UserDialog extends StatelessWidget {
  final String title;
  final List<Widget> children;
  final VoidCallback onConfirm;
  final String confirmLabel;
  final bool danger;
  const _UserDialog({
    required this.title,
    required this.children,
    required this.onConfirm,
    this.confirmLabel = 'تأیید',
    this.danger = false,
  });

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: const Color(0xFF18181B),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Container(
        padding: const EdgeInsets.all(24),
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: Colors.white)),
            const SizedBox(height: 18),
            ...children,
            const SizedBox(height: 20),
            Row(
              children: [
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: danger ? const Color(0xFFEF4444) : const Color(0xFF3B82F6),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  onPressed: onConfirm,
                  child: Text(confirmLabel),
                ),
                const SizedBox(width: 8),
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text('انصراف', style: TextStyle(color: Colors.white.withValues(alpha: 0.5))),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
