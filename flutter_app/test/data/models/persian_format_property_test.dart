// Feature: anpr-system-redesign, Property 31
// Property 31: Persian-locale formatting round-trips numbers and dates.
// Validates: Requirements 17.4
//
// Dart's `test` package has no built-in property-testing engine (no Hypothesis
// equivalent), so each property is exercised by generating a large number of
// random inputs in a loop (>= 100 examples per property) using a seeded RNG for
// reproducibility. For every generated value we assert that:
//   1. the Persian-locale formatter emits Persian digits (no ASCII digits leak), and
//   2. parsing the formatted output recovers the original value.

import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_app/data/models/persian_format.dart';

/// Minimum number of generated examples per property.
const int _examples = 500;

/// The ten Persian digit glyphs (۰-۹).
const String _persianDigitGlyphs = '۰۱۲۳۴۵۶۷۸۹';

/// True when [s] contains no ASCII digit (0-9). Used to assert the formatter
/// fully localizes numeric output into Persian digits.
bool _hasNoAsciiDigit(String s) => !RegExp(r'[0-9]').hasMatch(s);

/// Parse a Persian-digit integer string back into an int.
int _parsePersianInt(String s) => int.parse(PersianFormat.toLatinDigits(s));

void main() {
  group('Property 31: Persian-locale formatting round-trips (Requirement 17.4)',
      () {
    test('integers round-trip through Persian digits', () {
      // Seeded for reproducibility.
      final rng = Random(31);
      for (var i = 0; i < _examples; i++) {
        // Cover positive, negative and zero across a wide magnitude range.
        final value = rng.nextInt(2000000001) - 1000000000;

        final formatted = PersianFormat.number(value);

        // (1) Output uses Persian digits, never ASCII digits.
        expect(_hasNoAsciiDigit(formatted), isTrue,
            reason: 'number($value) -> "$formatted" leaked an ASCII digit');
        // Every glyph is either a Persian digit or the minus sign.
        for (final ch in formatted.split('')) {
          expect(_persianDigitGlyphs.contains(ch) || ch == '-', isTrue,
              reason: 'unexpected glyph "$ch" in "$formatted"');
        }

        // (2) Parsing the Persian output recovers the original integer.
        final restored = _parsePersianInt(formatted);
        expect(restored, value,
            reason: 'round-trip failed for integer $value');
      }
    });

    test('decimals round-trip through Persian digits at fixed precision', () {
      final rng = Random(132);
      for (var i = 0; i < _examples; i++) {
        final decimalPlaces = rng.nextInt(5); // 0..4 fractional digits
        final magnitude = (rng.nextDouble() - 0.5) * 2.0e6; // ~[-1e6, 1e6]

        // The faithful target is the value as rendered at this precision; the
        // helper formats via toStringAsFixed, so compare against the same.
        final expected =
            double.parse(magnitude.toStringAsFixed(decimalPlaces));

        final formatted =
            PersianFormat.decimal(magnitude, decimalPlaces: decimalPlaces);

        expect(_hasNoAsciiDigit(formatted), isTrue,
            reason: 'decimal($magnitude) -> "$formatted" leaked an ASCII digit');

        final restored =
            double.parse(PersianFormat.toLatinDigits(formatted));
        expect(restored, expected,
            reason:
                'round-trip failed for $magnitude at $decimalPlaces dp -> "$formatted"');
      }
    });

    test('dates round-trip (year/month/day recovered from formatted output)',
        () {
      final rng = Random(233);
      for (var i = 0; i < _examples; i++) {
        final year = 1 + rng.nextInt(9999); // 1..9999
        final month = 1 + rng.nextInt(12); // 1..12
        final day = 1 + rng.nextInt(28); // 1..28 (valid in every month)
        final dt = DateTime(year, month, day);

        final formatted = PersianFormat.date(dt);

        expect(_hasNoAsciiDigit(formatted), isTrue,
            reason: 'date($dt) -> "$formatted" leaked an ASCII digit');

        // Parse YYYY/MM/DD back from Persian digits.
        final parts = PersianFormat.toLatinDigits(formatted).split('/');
        expect(parts.length, 3, reason: 'unexpected date format "$formatted"');
        expect(int.parse(parts[0]), year, reason: 'year mismatch for $dt');
        expect(int.parse(parts[1]), month, reason: 'month mismatch for $dt');
        expect(int.parse(parts[2]), day, reason: 'day mismatch for $dt');
      }
    });

    test('times round-trip (hour/minute/second recovered from formatted output)',
        () {
      final rng = Random(334);
      for (var i = 0; i < _examples; i++) {
        final hour = rng.nextInt(24);
        final minute = rng.nextInt(60);
        final second = rng.nextInt(60);
        final dt = DateTime(2025, 1, 1, hour, minute, second);

        final formatted = PersianFormat.time(dt);

        expect(_hasNoAsciiDigit(formatted), isTrue,
            reason: 'time($dt) -> "$formatted" leaked an ASCII digit');

        final parts = PersianFormat.toLatinDigits(formatted).split(':');
        expect(parts.length, 3, reason: 'unexpected time format "$formatted"');
        expect(int.parse(parts[0]), hour, reason: 'hour mismatch for $dt');
        expect(int.parse(parts[1]), minute, reason: 'minute mismatch for $dt');
        expect(int.parse(parts[2]), second, reason: 'second mismatch for $dt');
      }
    });

    test('date-times round-trip (full DateTime recovered from formatted output)',
        () {
      final rng = Random(435);
      for (var i = 0; i < _examples; i++) {
        final year = 1 + rng.nextInt(9999);
        final month = 1 + rng.nextInt(12);
        final day = 1 + rng.nextInt(28);
        final hour = rng.nextInt(24);
        final minute = rng.nextInt(60);
        final second = rng.nextInt(60);
        final dt = DateTime(year, month, day, hour, minute, second);

        final formatted = PersianFormat.dateTime(dt);

        expect(_hasNoAsciiDigit(formatted), isTrue,
            reason: 'dateTime($dt) -> "$formatted" leaked an ASCII digit');

        // Output is "YYYY/MM/DD HH:MM:SS" in Persian digits.
        final latin = PersianFormat.toLatinDigits(formatted);
        final segments = latin.split(' ');
        expect(segments.length, 2,
            reason: 'unexpected dateTime format "$formatted"');
        final dateParts = segments[0].split('/');
        final timeParts = segments[1].split(':');
        expect(dateParts.length, 3);
        expect(timeParts.length, 3);

        final restored = DateTime(
          int.parse(dateParts[0]),
          int.parse(dateParts[1]),
          int.parse(dateParts[2]),
          int.parse(timeParts[0]),
          int.parse(timeParts[1]),
          int.parse(timeParts[2]),
        );
        expect(restored, dt, reason: 'date-time round-trip failed for $dt');
      }
    });

    test('digit conversion is an exact inverse (Persian <-> ASCII)', () {
      final rng = Random(536);
      for (var i = 0; i < _examples; i++) {
        // Build a random ASCII-digit string of length 1..12.
        final len = 1 + rng.nextInt(12);
        final buf = StringBuffer();
        for (var j = 0; j < len; j++) {
          buf.write(rng.nextInt(10).toString());
        }
        final original = buf.toString();

        final persian = PersianFormat.toPersianDigits(original);
        expect(_hasNoAsciiDigit(persian), isTrue,
            reason: 'toPersianDigits("$original") -> "$persian" kept ASCII');

        // Round-trips back to the original ASCII string.
        expect(PersianFormat.toLatinDigits(persian), original,
            reason: 'digit conversion not an inverse for "$original"');
      }
    });
  });
}
