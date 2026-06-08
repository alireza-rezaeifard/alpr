import 'package:intl/intl.dart';

/// Helper class for converting numbers, dates, and times to Persian locale format.
/// Validates: Requirements 17.4
class PersianFormat {
  // Persian digit characters (۰-۹)
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

  // Reverse mapping for converting Persian to Latin
  static const Map<String, String> _latinDigits = {
    '۰': '0',
    '۱': '1',
    '۲': '2',
    '۳': '3',
    '۴': '4',
    '۵': '5',
    '۶': '6',
    '۷': '7',
    '۸': '8',
    '۹': '9',
  };

  /// Convert a string containing Latin digits (0-9) to Persian digits (۰-۹)
  static String toPersianDigits(String input) {
    String result = input;
    _persianDigits.forEach((latin, persian) {
      result = result.replaceAll(latin, persian);
    });
    return result;
  }

  /// Convert a string containing Persian digits (۰-۹) to Latin digits (0-9)
  static String toLatinDigits(String input) {
    String result = input;
    _latinDigits.forEach((persian, latin) {
      result = result.replaceAll(persian, latin);
    });
    return result;
  }

  /// Format an integer number with Persian digits
  static String number(int value) {
    return toPersianDigits(value.toString());
  }

  /// Format a double number with Persian digits
  static String decimal(double value, {int? decimalPlaces}) {
    final formatted = decimalPlaces != null
        ? value.toStringAsFixed(decimalPlaces)
        : value.toString();
    return toPersianDigits(formatted);
  }

  /// Format a number with thousand separators and Persian digits
  static String numberWithSeparator(num value, {String separator = '٬'}) {
    final formatter = NumberFormat('#,###');
    final formatted = formatter.format(value);
    return toPersianDigits(formatted.replaceAll(',', separator));
  }

  /// Format a DateTime as Persian date (YYYY/MM/DD with Persian digits)
  static String date(DateTime dateTime) {
    final formatted =
        '${dateTime.year.toString().padLeft(4, '0')}/${dateTime.month.toString().padLeft(2, '0')}/${dateTime.day.toString().padLeft(2, '0')}';
    return toPersianDigits(formatted);
  }

  /// Format a DateTime as Persian time (HH:MM:SS with Persian digits)
  static String time(DateTime dateTime, {bool includeSeconds = true}) {
    final formatted = includeSeconds
        ? '${dateTime.hour.toString().padLeft(2, '0')}:${dateTime.minute.toString().padLeft(2, '0')}:${dateTime.second.toString().padLeft(2, '0')}'
        : '${dateTime.hour.toString().padLeft(2, '0')}:${dateTime.minute.toString().padLeft(2, '0')}';
    return toPersianDigits(formatted);
  }

  /// Format a DateTime as Persian date and time
  static String dateTime(DateTime dateTime, {bool includeSeconds = true}) {
    return '${date(dateTime)} ${time(dateTime, includeSeconds: includeSeconds)}';
  }

  /// Format an ISO-8601 string as Persian date
  static String? dateFromIso(String? isoString) {
    if (isoString == null || isoString.isEmpty) return null;
    final dt = DateTime.tryParse(isoString);
    return dt != null ? date(dt) : null;
  }

  /// Format an ISO-8601 string as Persian time
  static String? timeFromIso(String? isoString, {bool includeSeconds = true}) {
    if (isoString == null || isoString.isEmpty) return null;
    final dt = DateTime.tryParse(isoString);
    return dt != null ? time(dt, includeSeconds: includeSeconds) : null;
  }

  /// Format an ISO-8601 string as Persian date and time
  static String? dateTimeFromIso(String? isoString,
      {bool includeSeconds = true}) {
    if (isoString == null || isoString.isEmpty) return null;
    final dt = DateTime.tryParse(isoString);
    return dt != null ? dateTime(dt, includeSeconds: includeSeconds) : null;
  }

  /// Format a duration in Persian (e.g., "۲۳ دقیقه" or "۱ ساعت و ۱۵ دقیقه")
  static String duration(Duration duration) {
    if (duration.inDays > 0) {
      final days = duration.inDays;
      final hours = duration.inHours.remainder(24);
      if (hours > 0) {
        return '${number(days)} روز و ${number(hours)} ساعت';
      }
      return '${number(days)} روز';
    } else if (duration.inHours > 0) {
      final hours = duration.inHours;
      final minutes = duration.inMinutes.remainder(60);
      if (minutes > 0) {
        return '${number(hours)} ساعت و ${number(minutes)} دقیقه';
      }
      return '${number(hours)} ساعت';
    } else if (duration.inMinutes > 0) {
      final minutes = duration.inMinutes;
      final seconds = duration.inSeconds.remainder(60);
      if (seconds > 0) {
        return '${number(minutes)} دقیقه و ${number(seconds)} ثانیه';
      }
      return '${number(minutes)} دقیقه';
    } else {
      return '${number(duration.inSeconds)} ثانیه';
    }
  }

  /// Format a confidence percentage (0.0-1.0) as Persian percentage
  static String confidence(double value) {
    final percentage = (value * 100).round();
    return '${number(percentage)}٪';
  }

  /// Format a relative time string (e.g., "۵ دقیقه پیش")
  static String relativeTime(DateTime dateTime) {
    final now = DateTime.now();
    final difference = now.difference(dateTime);

    if (difference.inSeconds < 60) {
      return 'هم‌اکنون';
    } else if (difference.inMinutes < 60) {
      return '${number(difference.inMinutes)} دقیقه پیش';
    } else if (difference.inHours < 24) {
      return '${number(difference.inHours)} ساعت پیش';
    } else if (difference.inDays < 7) {
      return '${number(difference.inDays)} روز پیش';
    } else if (difference.inDays < 30) {
      final weeks = (difference.inDays / 7).floor();
      return '${number(weeks)} هفته پیش';
    } else if (difference.inDays < 365) {
      final months = (difference.inDays / 30).floor();
      return '${number(months)} ماه پیش';
    } else {
      final years = (difference.inDays / 365).floor();
      return '${number(years)} سال پیش';
    }
  }

  /// Format a relative time from an ISO-8601 string
  static String? relativeTimeFromIso(String? isoString) {
    if (isoString == null || isoString.isEmpty) return null;
    final dt = DateTime.tryParse(isoString);
    return dt != null ? relativeTime(dt) : null;
  }
}
