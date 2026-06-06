// lib/features/cameras/scanner_view.dart
// Network camera scanner: scan user-defined IP range for RTSP IP cameras,
// verify they respond on port 554, let user enter credentials and save.

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import '../../core/api_client.dart';
import '../../data/repositories/camera_repo.dart';
import 'cameras_view.dart' show cameraListProvider;

class ScannerView extends ConsumerStatefulWidget {
  const ScannerView({super.key});

  @override
  ConsumerState<ScannerView> createState() => _ScannerViewState();
}

class _ScannerViewState extends ConsumerState<ScannerView> {
  final _dio = ApiClient.instance;
  final _cameraRepo = CameraRepo();
  final _startIpCtrl = TextEditingController(text: '192.168.1.1');
  final _endIpCtrl = TextEditingController(text: '192.168.1.254');
  final _nameCtrl = TextEditingController();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _pathCtrl = TextEditingController(text: '/stream1');

  bool _scanning = false;
  int _progress = 0;
  int _total = 0;
  List<Map<String, dynamic>> _results = [];
  String? _selectedIp;
  Timer? _pollTimer;
  bool _testing = false;
  String? _testResult;
  bool _saving = false;
  String? _rangeError;

  // Stream probing state
  bool _probing = false;
  List<Map<String, dynamic>> _streams = [];
  String? _selectedStream;
  int _selectedPort = 554;

  @override
  void dispose() {
    _pollTimer?.cancel();
    _startIpCtrl.dispose();
    _endIpCtrl.dispose();
    _nameCtrl.dispose();
    _userCtrl.dispose();
    _passCtrl.dispose();
    _pathCtrl.dispose();
    super.dispose();
  }

  bool _validateRange() {
    final start = _startIpCtrl.text.trim();
    final end = _endIpCtrl.text.trim();
    final ipRegex = RegExp(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$');
    if (!ipRegex.hasMatch(start) || !ipRegex.hasMatch(end)) {
      setState(() => _rangeError = 'Invalid IP format');
      return false;
    }
    setState(() => _rangeError = null);
    return true;
  }

  Future<void> _startScan() async {
    if (!_validateRange()) return;
    setState(() {
      _scanning = true;
      _progress = 0;
      _results = [];
      _selectedIp = null;
      _testResult = null;
    });
    try {
      await _dio.post('/scanner/scan',
          data: FormData.fromMap({
            'start_ip': _startIpCtrl.text.trim(),
            'end_ip': _endIpCtrl.text.trim(),
            'timeout': '0.8',
          }));
      _pollTimer = Timer.periodic(
          const Duration(milliseconds: 500), (_) => _pollScan());
    } catch (e) {
      setState(() => _scanning = false);
    }
  }

  Future<void> _pollScan() async {
    try {
      final res = await _dio.get('/scanner/status');
      final data = res.data as Map<String, dynamic>;
      setState(() {
        _results = List<Map<String, dynamic>>.from(data['results'] as List);
        _progress = data['progress'] as int;
        _total = data['total'] as int;
        _scanning = data['running'] as bool;
      });
      if (!_scanning) _pollTimer?.cancel();
    } catch (_) {}
  }

  Future<void> _stopScan() async {
    _pollTimer?.cancel();
    try {
      await _dio.post('/scanner/stop');
    } catch (_) {}
    setState(() => _scanning = false);
  }

  String _buildRtspUrl() {
    final user = _userCtrl.text.trim();
    final pass = _passCtrl.text.trim();
    final path = _pathCtrl.text.trim();
    final cred = user.isNotEmpty ? '$user:$pass@' : '';
    return 'rtsp://$cred$_selectedIp:$_selectedPort$path';
  }

  Future<void> _probeStreams() async {
    if (_selectedIp == null) return;
    final cam = _results.firstWhere(
      (r) => r['ip'] == _selectedIp,
      orElse: () => <String, dynamic>{},
    );
    setState(() {
      _probing = true;
      _streams = [];
      _selectedStream = null;
    });
    try {
      final res = await _dio.post('/scanner/probe',
          data: FormData.fromMap({
            'ip': _selectedIp!,
            'port': (cam['port'] ?? 554).toString(),
            'brand': cam['brand'] ?? 'Unknown',
            'username': _userCtrl.text.trim(),
            'password': _passCtrl.text.trim(),
          }),
          options: Options(receiveTimeout: const Duration(seconds: 120)));
      final data = res.data as Map<String, dynamic>;
      final streams = List<Map<String, dynamic>>.from(data['streams'] as List);
      setState(() {
        _probing = false;
        _streams = streams;
        if (streams.isNotEmpty) {
          _selectedStream = streams.first['path'] as String;
          _selectedPort = streams.first['port'] as int? ?? 554;
          _pathCtrl.text = _selectedStream!;
        }
      });
    } catch (e) {
      setState(() {
        _probing = false;
      });
    }
  }

  Future<void> _testConnection() async {
    if (_selectedIp == null) return;
    setState(() {
      _testing = true;
      _testResult = null;
    });
    try {
      final url = _buildRtspUrl();
      final res = await _dio.post('/scanner/test',
          data: FormData.fromMap({'url': url}),
          options: Options(receiveTimeout: const Duration(seconds: 15)));
      final data = res.data as Map<String, dynamic>;
      setState(() {
        _testing = false;
        _testResult = data['success'] == true
            ? '✓ Connection successful'
            : '✗ ${data['error'] ?? 'Failed'}';
      });
    } catch (e) {
      setState(() {
        _testing = false;
        _testResult = '✗ Error: $e';
      });
    }
  }

  Future<void> _saveCamera() async {
    if (_selectedIp == null) return;
    setState(() => _saving = true);
    try {
      final url = _buildRtspUrl();
      final name = _nameCtrl.text.trim().isEmpty
          ? 'Camera $_selectedIp'
          : _nameCtrl.text.trim();
      await _cameraRepo.createCamera(name, url, 15);
      // Refresh the cameras list so "My Cameras" tab shows the new camera
      ref.invalidate(cameraListProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Camera "$name" saved!')),
        );
        setState(() {
          _selectedIp = null;
          _testResult = null;
          _nameCtrl.clear();
          _userCtrl.clear();
          _passCtrl.clear();
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to save: $e')),
        );
      }
    } finally {
      setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // IP range input + scan button
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 160,
                child: TextField(
                  controller: _startIpCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Start IP',
                    isDense: true,
                  ),
                  enabled: !_scanning,
                ),
              ),
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                child: Text('—'),
              ),
              SizedBox(
                width: 160,
                child: TextField(
                  controller: _endIpCtrl,
                  decoration: const InputDecoration(
                    labelText: 'End IP',
                    isDense: true,
                  ),
                  enabled: !_scanning,
                ),
              ),
              const SizedBox(width: 16),
              ElevatedButton.icon(
                icon: _scanning
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.radar),
                label: Text(_scanning ? 'Scanning…' : 'Scan'),
                onPressed: _scanning ? null : _startScan,
              ),
              if (_scanning) ...[
                const SizedBox(width: 8),
                ElevatedButton.icon(
                  icon: const Icon(Icons.stop),
                  label: const Text('Stop'),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                  onPressed: _stopScan,
                ),
              ],
              const SizedBox(width: 16),
              if (_scanning || _progress > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                      '$_progress/$_total checked • ${_results.length} cameras'),
                ),
            ],
          ),
          if (_rangeError != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child:
                  Text(_rangeError!, style: const TextStyle(color: Colors.red)),
            ),
          if (_scanning)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: LinearProgressIndicator(
                value: _total > 0 ? _progress / _total : null,
              ),
            ),

          const SizedBox(height: 16),

          // Results + config
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Left: found IP cameras
                Expanded(
                  flex: 1,
                  child: Card(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(12),
                          child: Text(
                            'IP Cameras Found (${_results.length})',
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                        ),
                        const Divider(height: 1),
                        Expanded(
                          child: _results.isEmpty
                              ? Center(
                                  child: Text(
                                    _scanning
                                        ? 'Scanning for IP cameras…'
                                        : 'No IP cameras found. Set range and scan.',
                                    style: const TextStyle(color: Colors.grey),
                                  ),
                                )
                              : ListView.builder(
                                  itemCount: _results.length,
                                  itemBuilder: (_, i) {
                                    final r = _results[i];
                                    final ip = r['ip'] as String;
                                    final brand = r['brand'] as String? ?? 'Unknown';
                                    final port = r['port'] as int? ?? 554;
                                    final server = r['server'] as String? ?? '';
                                    final selected = ip == _selectedIp;
                                    return ListTile(
                                      leading: Icon(
                                        Icons.videocam,
                                        color: selected
                                            ? Theme.of(context)
                                                .colorScheme
                                                .primary
                                            : null,
                                      ),
                                      title: Text('$ip:$port'),
                                      subtitle: Text(
                                        '$brand${server.isNotEmpty ? ' • $server' : ''}',
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                      selected: selected,
                                      onTap: () {
                                        setState(() {
                                          _selectedIp = ip;
                                          _selectedPort = port;
                                          _testResult = null;
                                          _streams = [];
                                          _selectedStream = null;
                                          // Auto-fill name with brand if available
                                          if (brand != 'Unknown') {
                                            _nameCtrl.text = '$brand $ip';
                                          }
                                        });
                                        // Auto-probe for streams
                                        _probeStreams();
                                      },
                                    );
                                  },
                                ),
                        ),
                      ],
                    ),
                  ),
                ),

                const SizedBox(width: 16),

                // Right: credentials + save
                Expanded(
                  flex: 1,
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: _selectedIp == null
                          ? const Center(
                              child: Text(
                                'Select a camera from the list',
                                style: TextStyle(color: Colors.grey),
                              ),
                            )
                          : SingleChildScrollView(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Configure: $_selectedIp',
                                    style:
                                        Theme.of(context).textTheme.titleSmall,
                                  ),
                                  const SizedBox(height: 16),
                                  TextField(
                                    controller: _nameCtrl,
                                    decoration: const InputDecoration(
                                      labelText: 'Camera Name (optional)',
                                      prefixIcon: Icon(Icons.label),
                                    ),
                                  ),
                                  const SizedBox(height: 12),
                                  TextField(
                                    controller: _userCtrl,
                                    decoration: const InputDecoration(
                                      labelText: 'Username',
                                      prefixIcon: Icon(Icons.person),
                                    ),
                                  ),
                                  const SizedBox(height: 12),
                                  TextField(
                                    controller: _passCtrl,
                                    obscureText: true,
                                    decoration: const InputDecoration(
                                      labelText: 'Password',
                                      prefixIcon: Icon(Icons.lock),
                                    ),
                                  ),
                                  const SizedBox(height: 12),

                                  // Probe button + streams
                                  Row(
                                    children: [
                                      ElevatedButton.icon(
                                        icon: _probing
                                            ? const SizedBox(
                                                width: 14,
                                                height: 14,
                                                child: CircularProgressIndicator(strokeWidth: 2))
                                            : const Icon(Icons.search),
                                        label: Text(_probing ? 'Probing…' : 'Detect Streams'),
                                        onPressed: _probing ? null : _probeStreams,
                                      ),
                                      if (_streams.isNotEmpty) ...[
                                        const SizedBox(width: 8),
                                        Text(
                                          '${_streams.length} found',
                                          style: TextStyle(
                                            color: Colors.green[700],
                                            fontWeight: FontWeight.bold,
                                          ),
                                        ),
                                      ],
                                    ],
                                  ),
                                  if (_probing)
                                    const Padding(
                                      padding: EdgeInsets.only(top: 8),
                                      child: Text(
                                        'Testing stream paths… this may take a moment.',
                                        style: TextStyle(color: Colors.grey, fontSize: 12),
                                      ),
                                    ),
                                  if (_streams.isNotEmpty) ...[
                                    const SizedBox(height: 12),
                                    const Text('Available Streams:',
                                        style: TextStyle(fontWeight: FontWeight.bold)),
                                    const SizedBox(height: 4),
                                    Container(
                                      constraints: const BoxConstraints(maxHeight: 180),
                                      decoration: BoxDecoration(
                                        border: Border.all(color: Colors.grey.shade300),
                                        borderRadius: BorderRadius.circular(8),
                                      ),
                                      child: ListView.builder(
                                        shrinkWrap: true,
                                        itemCount: _streams.length,
                                        itemBuilder: (_, i) {
                                          final stream = _streams[i];
                                          final path = stream['path'] as String;
                                          final label = stream['label'] as String? ?? path;
                                          final streamPort = stream['port'] as int? ?? 554;
                                          final isSelected = path == _selectedStream && streamPort == _selectedPort;
                                          return ListTile(
                                            dense: true,
                                            leading: Icon(
                                              isSelected ? Icons.radio_button_checked : Icons.radio_button_off,
                                              size: 20,
                                              color: isSelected ? Theme.of(context).colorScheme.primary : null,
                                            ),
                                            title: Text(label, style: const TextStyle(fontSize: 13)),
                                            subtitle: Text('Port $streamPort • $path', style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
                                            selected: isSelected,
                                            onTap: () => setState(() {
                                              _selectedStream = path;
                                              _selectedPort = stream['port'] as int? ?? 554;
                                              _pathCtrl.text = path;
                                            }),
                                          );
                                        },
                                      ),
                                    ),
                                  ],
                                  if (!_probing && _streams.isEmpty && _selectedIp != null) ...[
                                    const SizedBox(height: 8),
                                    const Text(
                                      'Enter credentials above and tap "Detect Streams" to auto-discover paths.',
                                      style: TextStyle(color: Colors.grey, fontSize: 12),
                                    ),
                                  ],

                                  const SizedBox(height: 12),
                                  TextField(
                                    controller: _pathCtrl,
                                    decoration: const InputDecoration(
                                      labelText: 'Stream Path',
                                      prefixIcon: Icon(Icons.link),
                                      hintText: '/stream1',
                                    ),
                                  ),
                                  const SizedBox(height: 8),
                                  Text(
                                    'URL: ${_buildRtspUrl()}',
                                    style:
                                        Theme.of(context).textTheme.bodySmall,
                                  ),
                                  const SizedBox(height: 16),
                                  Row(
                                    children: [
                                      ElevatedButton.icon(
                                        icon: _testing
                                            ? const SizedBox(
                                                width: 14,
                                                height: 14,
                                                child:
                                                    CircularProgressIndicator(
                                                        strokeWidth: 2))
                                            : const Icon(Icons.wifi_find),
                                        label: const Text('Test'),
                                        onPressed:
                                            _testing ? null : _testConnection,
                                      ),
                                      const SizedBox(width: 12),
                                      ElevatedButton.icon(
                                        icon: _saving
                                            ? const SizedBox(
                                                width: 14,
                                                height: 14,
                                                child:
                                                    CircularProgressIndicator(
                                                        strokeWidth: 2))
                                            : const Icon(Icons.save),
                                        label: const Text('Save Camera'),
                                        onPressed:
                                            _saving ? null : _saveCamera,
                                      ),
                                    ],
                                  ),
                                  if (_testResult != null) ...[
                                    const SizedBox(height: 12),
                                    Container(
                                      padding: const EdgeInsets.all(10),
                                      decoration: BoxDecoration(
                                        color: _testResult!.startsWith('✓')
                                            ? Colors.green.withOpacity(0.1)
                                            : Colors.red.withOpacity(0.1),
                                        borderRadius: BorderRadius.circular(8),
                                      ),
                                      child: Text(
                                        _testResult!,
                                        style: TextStyle(
                                          color: _testResult!.startsWith('✓')
                                              ? Colors.green
                                              : Colors.red,
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
