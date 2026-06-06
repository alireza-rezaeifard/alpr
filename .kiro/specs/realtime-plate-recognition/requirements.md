# Requirements Document

## Introduction

This document specifies requirements for enhancing the Persian License Plate Recognition system with real-time plate display, real-time database persistence, Iranian plate format validation, metadata display, and Flutter build warning fixes. The system processes video files and RTSP streams, detecting license plates frame-by-frame and presenting validated Iranian plates to users as they are detected — not after processing completes.

## Glossary

- **System**: The Persian License Plate Recognition application (backend + frontend)
- **Validator**: The IranianPlateValidator component that checks detected plate text against Iranian plate formats
- **VideoProcessor**: The backend component that processes video frames for plate detection
- **RTSPProcessor**: The backend component that processes RTSP stream frames for plate detection
- **PlateListPanel**: The Flutter UI widget that displays detected plates in real-time
- **DTRB_Text**: The raw text string output by the deep text recognition model (DTRB)
- **Iranian_Plate_Format**: A plate string of exactly 8 characters: 2 digits (prefix) + 1 series letter + 3 digits (number) + 2 digits (region code)
- **Plate_Metadata**: Derived information including vehicle category, category display name, plate color scheme, region code, and province name
- **Detection_Session**: A database record tracking a single video or RTSP processing run
- **Polling_Interval**: The 1-second interval at which the Flutter frontend fetches updated detection results from the backend

## Requirements

### Requirement 1: Flutter Build Warning Fixes

**User Story:** As a developer, I want the Flutter project to build without warnings related to missing fonts or outdated packages, so that the development experience is clean and CI pipelines pass without noise.

#### Acceptance Criteria

1. WHEN the Flutter project is built, THE System SHALL produce no warnings related to the cupertino_icons font package
2. WHEN the Flutter project is built, THE System SHALL produce no warnings related to outdated or incompatible package versions
3. THE System SHALL retain all existing functionality after dependency updates

### Requirement 2: Real-Time Plate Display During Video Processing

**User Story:** As a user, I want to see detected license plates appear in the UI as soon as they are recognized during video processing, so that I can monitor detections without waiting for the entire video to finish.

#### Acceptance Criteria

1. WHEN the VideoProcessor detects a valid plate during processing, THE PlateListPanel SHALL display that plate within the next Polling_Interval
2. WHILE video processing is active, THE PlateListPanel SHALL update its plate list on every poll response that contains new detections
3. WHEN new plates are added to the PlateListPanel, THE PlateListPanel SHALL auto-scroll to show the most recently detected plate
4. WHILE video processing is active, THE System SHALL accumulate plates monotonically in the plate log — plates are never removed during processing
5. WHEN the backend poll response contains an annotated frame, THE System SHALL display the annotated frame as a live preview alongside the plate list

### Requirement 3: Real-Time Plate Display During RTSP Processing

**User Story:** As a user, I want to see detected license plates appear in the UI as soon as they are recognized during RTSP stream processing, so that I can monitor a live camera feed with immediate plate feedback.

#### Acceptance Criteria

1. WHEN the RTSPProcessor detects a valid plate during streaming, THE PlateListPanel SHALL display that plate within the next Polling_Interval
2. WHILE RTSP processing is active, THE PlateListPanel SHALL update its history list on every poll response that contains new detections
3. WHEN the same plate is detected multiple times in an RTSP stream, THE System SHALL increment the detection count for that plate rather than creating duplicate entries
4. WHEN the backend poll response contains an annotated frame, THE System SHALL display the annotated frame as a live preview

### Requirement 4: Real-Time Database Saving During Processing

**User Story:** As a system operator, I want detected plates to be saved to the database immediately when detected, so that detection data is preserved even if the processing session is interrupted.

#### Acceptance Criteria

1. WHEN a valid Iranian plate is detected during video processing, THE System SHALL persist the detection to the database immediately within the same processing cycle
2. WHEN a valid Iranian plate is detected during RTSP processing, THE System SHALL persist the detection to the database immediately within the same processing cycle
3. WHEN a detection is saved to the database, THE System SHALL record the session ID, source type, plate text, Persian display text, confidence score, frame number, and frame time
4. IF a database write fails during processing, THEN THE System SHALL continue processing subsequent frames without interruption
5. WHEN a processing session ends, THE System SHALL have already persisted all valid detections — no batch save at session end is required

### Requirement 5: Iranian Plate Format Validation

**User Story:** As a user, I want only plates matching the valid Iranian license plate format to be accepted and saved, so that random OCR noise and non-plate text are filtered out.

#### Acceptance Criteria

1. WHEN a DTRB_Text is received for validation, THE Validator SHALL normalize Persian and Arabic digits to ASCII digits before structural checks
2. WHEN a DTRB_Text is received for validation, THE Validator SHALL strip separator characters (spaces, dashes, underscores) before structural checks
3. WHEN the normalized text length is not exactly 8 characters, THE Validator SHALL reject the plate as invalid
4. WHEN positions 0-1 of the normalized text are not digits, THE Validator SHALL reject the plate as invalid
5. WHEN position 2 of the normalized text is not a recognized Iranian plate series letter, THE Validator SHALL reject the plate as invalid
6. WHEN positions 3-5 of the normalized text are not digits, THE Validator SHALL reject the plate as invalid
7. WHEN positions 6-7 of the normalized text are not digits, THE Validator SHALL reject the plate as invalid
8. WHEN the region code (positions 6-7) does not exist in the known region code registry, THE Validator SHALL reject the plate as invalid
9. WHEN the detection confidence is below the minimum threshold (0.4), THE Validator SHALL reject the plate regardless of text format
10. WHEN validation fails, THE Validator SHALL provide a rejection reason describing which check failed
11. WHEN all structural and confidence checks pass, THE Validator SHALL return a valid result with complete Plate_Metadata

### Requirement 6: Iranian Plate Metadata Display

**User Story:** As a user, I want to see detailed Iranian plate metadata (province, vehicle type, plate color) for each detected plate, so that I can understand the plate classification at a glance.

#### Acceptance Criteria

1. WHEN a valid Iranian plate is displayed in the PlateListPanel, THE System SHALL show the plate text formatted in Persian display style (e.g., "۱۲ ب ۳۴۵-۶۷")
2. WHEN a valid Iranian plate is displayed, THE System SHALL show the vehicle category display name (e.g., "شخصی (Private)", "تاکسی (Taxi)")
3. WHEN a valid Iranian plate is displayed, THE System SHALL show the province name derived from the region code
4. WHEN a valid Iranian plate is displayed, THE System SHALL show a color indicator matching the plate color scheme (white, yellow, green, red, blue, or black)
5. WHEN a valid Iranian plate is displayed, THE System SHALL show the detection confidence as a percentage
6. WHEN a plate is marked as invalid (not matching Iranian format), THE System SHALL display the raw text without metadata fields

### Requirement 7: Validation and Metadata Integration with Processing Pipeline

**User Story:** As a developer, I want the validation and metadata logic to be integrated into the detection pipeline, so that every detected plate is automatically validated and enriched before being stored or displayed.

#### Acceptance Criteria

1. WHEN the VideoProcessor detects a plate, THE System SHALL call the Validator before adding the plate to the plate log or saving to the database
2. WHEN the RTSPProcessor detects a plate, THE System SHALL call the Validator before adding the plate to the history or saving to the database
3. WHEN the Validator returns a valid result, THE System SHALL attach the full Plate_Metadata to the plate log entry sent to the frontend
4. WHEN the Validator returns an invalid result, THE System SHALL exclude the plate from database persistence
5. THE System SHALL include the validation status (is_valid_iranian) and metadata in the API poll response for each plate log entry
