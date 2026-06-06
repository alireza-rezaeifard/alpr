# Implementation Plan: Real-Time Plate Recognition

## Overview

This plan implements real-time plate recognition with Iranian plate validation, metadata display, immediate database persistence, and Flutter build fixes. Tasks are ordered by dependency — backend validation first, then pipeline integration, then frontend UI.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": [1, 2] },
    { "id": 1, "tasks": [3, 4] },
    { "id": 2, "tasks": [5, 7] },
    { "id": 3, "tasks": [6, 8] },
    { "id": 4, "tasks": [9] },
    { "id": 5, "tasks": [10, 11] },
    { "id": 6, "tasks": [12, 13] }
  ]
}
```

## Tasks

- [x] 1. Fix Flutter build warnings: Remove `cupertino_icons` from `flutter_app/pubspec.yaml`, remove any cupertino_icons imports from Dart files, run `flutter pub get`, verify build produces no font or outdated package warnings
  - Requirements: 1.1, 1.2, 1.3

- [ ] 2. Create `plate_validator.py` with `ValidationResult` dataclass (is_valid, plate_text, metadata, rejection_reason) and `validate_iranian_plate(dtrb_text, confidence, min_confidence=0.4)` function implementing: confidence threshold check, Persian/Arabic digit normalization, separator stripping, length==8 check, structural validation (positions 0-1 digits, position 2 valid letter, positions 3-5 digits, positions 6-7 digits), series letter validation against LETTER_TO_CATEGORY/PERSIAN_LETTER_TO_CATEGORY, region code validation against REGION_CODE_TO_PROVINCE, call derive_metadata() for valid plates, return rejection reason for invalid plates
  - Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11

- [ ] 3. Write unit tests for `validate_iranian_plate()` covering: valid plates with various letters/regions, invalid lengths, invalid letter positions, unknown region codes, low confidence rejection, Persian/Arabic digit normalization, separator stripping, empty/None/whitespace inputs
  - Requirements: 5.1, 5.2, 5.3, 5.5, 5.8, 5.9, 5.10, 5.11

- [ ] 4. Write property-based tests (Hypothesis) for plate validator: Property 1 (valid plate acceptance with metadata), Property 2 (invalid length rejection), Property 3 (invalid structure rejection), Property 4 (low confidence rejection), Property 5 (rejection reason completeness)
  - Requirements: 5.1, 5.2, 5.3, 5.5, 5.8, 5.9, 5.10, 5.11

- [ ] 5. Integrate validator into VideoProcessor: import validate_iranian_plate in video_processor.py, call it for each detected plate in the processing loop, extend plate_log entries with persian_display/is_valid_iranian/metadata fields, call save_detection() immediately for valid plates within frame loop, skip DB save for invalid plates, handle DB write failures gracefully (log and continue)
  - Requirements: 4.1, 4.3, 4.4, 7.1, 7.3, 7.4, 7.5
  - Depends on: 2

- [ ] 6. Update `api.py` video_status endpoint to return enhanced plate_log entries including persian_display, is_valid_iranian, and metadata in the poll response
  - Requirements: 2.1, 7.5
  - Depends on: 5

- [ ] 7. Integrate validator into RTSPStreamProcessor: call validate_iranian_plate() for each detection, extend history entries with persian_display/is_valid_iranian/metadata, implement deduplication (increment count for repeated plate text), call save_detection() immediately for valid plates, exclude invalid plates from DB
  - Requirements: 3.3, 4.2, 4.3, 7.2, 7.3, 7.4, 7.5
  - Depends on: 2

- [ ] 8. Update `api.py` rtsp_status endpoint to return enhanced history entries including persian_display, is_valid_iranian, metadata, and count
  - Requirements: 3.1, 3.2, 7.5
  - Depends on: 7

- [ ] 9. Create/update Flutter `EnhancedPlateLogEntry` model with fields: frame, time, timeSec, plateText, dtrbText, confidence, bbox, persianDisplay, isValidIranian, metadata; create/update `PlateMetadataModel` with fields: classified, category, categoryDisplay, colorScheme, regionCode, regionName, specialNote; implement fromJson factories with safe defaults
  - Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.5
  - Depends on: 6, 8

- [ ] 10. Update VideoTaskController and RTSP poll controller to parse enhanced plate_log/history entries using the new models
  - Requirements: 2.1, 2.2, 3.1, 3.2
  - Depends on: 9

- [ ] 11. Create `PlateDetailCard` widget displaying: Persian formatted plate text, color swatch indicator, category badge, province/region name, confidence percentage, frame/timestamp; differentiate valid Iranian plates from unclassified detections
  - Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
  - Depends on: 9

- [ ] 12. Update `_PlateLogPanel` in video_sub_view.dart and RTSP view to use PlateDetailCard, implement auto-scroll to newest detection, show count badge for repeated RTSP detections
  - Requirements: 2.2, 2.3, 2.4, 3.2, 3.3
  - Depends on: 11

- [ ] 13. Write integration tests: verify plates appear in poll responses during processing (not only after), verify detection timestamps distributed during session, verify monotonic plate_log growth (Property 6), verify only valid Iranian plates saved to DB (Property 8)
  - Requirements: 2.1, 4.1, 4.2, 4.5
  - Depends on: 5, 7

## Notes

- Property-based tests in Task 4 use Hypothesis library (Python) with minimum 100 iterations per property
- The existing `on_detection` callback signature in VideoProcessor is preserved for backward compatibility
- Flutter UI changes require Vazirmatn or similar Persian font for proper RTL plate display
- All database operations use existing parameterized queries in db.py — no SQL injection risk
