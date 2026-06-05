// Chart data models for Dashboard and Analytics views.

class TimelineEntry {
  final String dt;
  final int cnt;
  const TimelineEntry({required this.dt, required this.cnt});
  factory TimelineEntry.fromJson(Map<String, dynamic> json) =>
      TimelineEntry(dt: json['dt'] as String, cnt: json['cnt'] as int);
}

class SourceEntry {
  final String sourceType;
  final int cnt;
  const SourceEntry({required this.sourceType, required this.cnt});
  factory SourceEntry.fromJson(Map<String, dynamic> json) =>
      SourceEntry(sourceType: json['source_type'] as String, cnt: json['cnt'] as int);
}

class ConfidenceEntry {
  final double bin;
  final int cnt;
  const ConfidenceEntry({required this.bin, required this.cnt});
  factory ConfidenceEntry.fromJson(Map<String, dynamic> json) =>
      ConfidenceEntry(bin: (json['bin'] as num).toDouble(), cnt: json['cnt'] as int);
}

class LetterEntry {
  final String platePersian;
  final int cnt;
  const LetterEntry({required this.platePersian, required this.cnt});
  factory LetterEntry.fromJson(Map<String, dynamic> json) =>
      LetterEntry(platePersian: json['plate_persian'] as String? ?? '', cnt: json['cnt'] as int);
}
