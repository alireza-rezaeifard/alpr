// lib/main.dart
// App entry point: initialises Riverpod, then runs PlprApp.
// Requirements: 1.1

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'app/app.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: PlprApp()));
}
