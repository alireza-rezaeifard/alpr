// lib/core/persian_format.dart
// Persian locale formatting for numbers, dates, and times.
// Requirement 17.4

import 'package:intl/intl.dart';
import 'package:shamsi_date/shamsi_date.dart';

class PersianFormat {
  PersianFormat._();

  // Persian digit mapping
  static const Map<String, String> _persianDigits = {
    '0': '۰',
    '1': '۱',
    '2': '۲',
    '3': '۳',
    '4': '۴',
    '5': '۵',
    '6': '۶',
    '7': '۷',
    '8': '۸',
    '9': '۹',
  };

  /// Convert Latin digits to Persian digits
  static String toPersianDigits(String text) {
    String result = text;
    _persianDigits.forEach((latin, persian) {
      result = result.replaceAll(latin, persian);
    });
    return result;
  }

  /// Format a number with Persian digits
  static String number(num value) {
    final formatted = NumberFormat('#,###', 'en').format(value);
    return toPersianDigits(formatted);
  }

  /// Format a double with precision and Persian digits
  static String decimal(double value, {int decimals = 2}) {
    final formatted = value.toStringAsFixed(decimals);
    return toPersianDigits(formatted);
  }

  /// Format percentage with Persian digits
  static String percentage(double value, {int decimals = 1}) {
    final formatted = (value * 100).toStringAsFixed(decimals);
    return '${toPersianDigits(formatted)}٪';
  }

  /// Format DateTime to Persian date string (Shamsi calendar)
  static String date(DateTime dateTime) {
    final shamsi = Jalali.fromDateTime(dateTime);
    final year = toPersianDigits(shamsi.year.toString());
    final month = toPersianDigits(shamsi.month.toString().padLeft(2, '0'));
    final day = toPersianDigits(shamsi.day.toString().padLeft(2, '0'));
    return '$year/$month/$day';
  }

  /// Format DateTime to Persian time string (24-hour format)
  static String time(DateTime dateTime) {
    final hour = toPersianDigits(dateTime.hour.toString().padLeft(2, '0'));
    final minute = toPersianDigits(dateTime.minute.toString().padLeft(2, '0'));
    final second = toPersianDigits(dateTime.second.toString().padLeft(2, '0'));
    return '$hour:$minute:$second';
  }

  /// Format DateTime to Persian date and time string
  static String dateTime(DateTime dt) {
    return '${date(dt)} - ${time(dt)}';
  }

  /// Format DateTime to relative time in Persian
  static String relativeTime(DateTime dateTime) {
    final now = DateTime.now();
    final difference = now.difference(dateTime);

    if (difference.inDays > 365) {
      final years = difference.inDays ~/ 365;
      return '${toPersianDigits(years.toString())} سال پیش';
    } else if (difference.inDays > 30) {
      final months = difference.inDays ~/ 30;
      return '${toPersianDigits(months.toString())} ماه پیش';
    } else if (difference.inDays > 0) {
      return '${toPersianDigits(difference.inDays.toString())} روز پیش';
    } else if (difference.inHours > 0) {
      return '${toPersianDigits(difference.inHours.toString())} ساعت پیش';
    } else if (difference.inMinutes > 0) {
      return '${toPersianDigits(difference.inMinutes.toString())} دقیقه پیش';
    } else {
      return 'همین الان';
    }
  }

  /// Format duration in Persian
  static String duration(Duration duration) {
    if (duration.inHours > 0) {
      final hours = toPersianDigits(duration.inHours.toString());
      final minutes = toPersianDigits((duration.inMinutes % 60).toString().padLeft(2, '0'));
      final seconds = toPersianDigits((duration.inSeconds % 60).toString().padLeft(2, '0'));
      return '$hours:$minutes:$seconds';
    } else if (duration.inMinutes > 0) {
      final minutes = toPersianDigits(duration.inMinutes.toString());
      final seconds = toPersianDigits((duration.inSeconds % 60).toString().padLeft(2, '0'));
      return '$minutes:$seconds';
    } else {
      return '${toPersianDigits(duration.inSeconds.toString())} ثانیه';
    }
  }
}
