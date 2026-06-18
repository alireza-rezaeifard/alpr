# Requirements Document

## Introduction

This document specifies requirements for upgrading the recognition models and adding new vehicle-attribute features to the existing Persian License Plate Recognition system (a FastAPI backend with a Flutter primary frontend).

The system currently uses a YOLOv8 plate detector plus a DTRB (deep text recognition benchmark) OCR recognizer, which produce weak accuracy. This upgrade replaces those two models with the more accurate pretrained YOLO11 models from a local reference project (Multi-Task Iranian Vehicle Monitoring System), and adds three new capabilities that have no existing implementation: car color recognition, car type/name recognition, and city/region lookup derived from the plate code.

Scope boundaries:

- This spec focuses ONLY on the model upgrade and new car-attribute features. It does NOT re-specify Iranian plate validation, plate metadata (province/category/color scheme), real-time display, or database persistence, which are owned by the existing `realtime-plate-recognition` spec. Where this spec produces new fields, it defines how those fields flow through to the existing pipeline without duplicating that spec's behavior.
- The three existing input pipelines (image upload, video upload, live camera/RTSP feed) must remain functional. Only the inference performed inside those pipelines changes.
- The reference project's inference logic is to be WRAPPED, not rewritten.
- Accident detection (`accident_model.pt`) is explicitly out of scope.

## Glossary

- **System**: The Persian License Plate Recognition application (FastAPI backend plus Flutter frontend).
- **Backend**: The FastAPI Python server (Python 3.11+, ultralytics>=8.0).
- **Recognition_Service**: The new backend component that wraps the reference project's inference logic and exposes plate/character/color/car-type/region recognition to the existing pipelines.
- **Model_Registry**: The backend singleton responsible for loading and holding all `.pt` model weights and the city/region lookup table in memory for the process lifetime.
- **Plate_Detector_Model**: The reference YOLO11 weight `weights/plate_det_model.pt` used to locate license plates in an image or frame.
- **Char_Model**: The reference YOLO11 weight `weights/char_model.pt` used to detect and recognize Persian characters within a detected plate.
- **Car_Detector_Model**: The reference YOLO11 weight `weights/car_det_model.pt` used to detect car type/name.
- **Color_Model**: The reference YOLO11 weight `weights/color_model.pt` used to classify car color.
- **City_Lookup**: The mapping loaded from the reference file `Plates/city_plateinfo.txt` that resolves a city code to a city/region name.
- **Reference_Project**: The local Multi-Task Iranian Vehicle Monitoring System project whose inference logic and weights are wrapped by this System.
- **Recognition_Result**: A single structured detection result conforming to the Output JSON Contract defined in Requirement 7.
- **Result_Type**: A Result/Either return value carrying either a success value or an error value, used so callers never receive raw raised exceptions.
- **Frame_Sampling_Interval**: The configurable integer N controlling that every Nth frame of a video or live feed is submitted for recognition (default N=5).
- **Degraded_Operation**: The mode in which one or more optional models failed to load, so the System continues operating and returns `null` for the affected fields.
- **Detection_Pipeline**: One of the three input pipelines: image upload, video upload, or live camera/RTSP feed.
- **Results_Screen**: The existing Flutter screen that displays recognition results to the user.
- **Bounding_Box**: A rectangle expressed as `[x, y, w, h]` in pixel coordinates of the source image or frame.
- **Info_Card**: A new Flutter UI widget displaying a single new vehicle attribute (car color, car type, or region) below the existing plate text result.
- **Localization_Constants**: The existing Flutter string/constants pattern (including `lib/core/persian_format.dart` and `lib/shared/widgets/`) used in place of hardcoded strings.

## Requirements

### Requirement 1: Model Replacement

**User Story:** As a system operator, I want the weak YOLOv8 detector and DTRB recognizer replaced with the reference YOLO11 plate and character models, so that plate detection and reading accuracy improves.

#### Acceptance Criteria

1. THE Recognition_Service SHALL use the Plate_Detector_Model for license plate detection in place of the previous YOLOv8 detector.
2. THE Recognition_Service SHALL use the Char_Model for character detection and recognition in place of the previous DTRB recognizer.
3. WHEN a plate region is detected by the Plate_Detector_Model, THE Recognition_Service SHALL run the Char_Model on that region to produce the recognized plate text.
4. THE Recognition_Service SHALL produce the recognized plate text as the `plate_text` field of the Recognition_Result for every successful plate recognition.
5. THE Recognition_Service SHALL wrap the Reference_Project inference logic rather than reimplementing the detection or recognition algorithms.

### Requirement 2: Car Color Recognition

**User Story:** As a user, I want the detected car's color recognized, so that I can identify vehicles by color in the results.

#### Acceptance Criteria

1. WHEN a car is detected in an image or frame, THE Recognition_Service SHALL run the Color_Model to classify the car color.
2. WHEN the Color_Model produces a color classification, THE Recognition_Service SHALL include the classified color as the `car_color` field of the Recognition_Result.
3. IF car color classification fails or no car is detected, THEN THE Recognition_Service SHALL set the `car_color` field to `null`.

### Requirement 3: Car Type Recognition

**User Story:** As a user, I want the detected car's type/name recognized, so that I can identify the vehicle model in the results.

#### Acceptance Criteria

1. WHEN a car is present in an image or frame, THE Recognition_Service SHALL run the Car_Detector_Model to detect the car type/name.
2. WHEN the Car_Detector_Model produces a car type/name, THE Recognition_Service SHALL include that value as the `car_type` field of the Recognition_Result.
3. WHEN the Car_Detector_Model detects a car, THE Recognition_Service SHALL include the car Bounding_Box as the `bounding_box.car` field of the Recognition_Result.
4. IF car type detection fails or no car is detected, THEN THE Recognition_Service SHALL set the `car_type` field to `null` and the `bounding_box.car` field to `null`.

### Requirement 4: City and Region Lookup

**User Story:** As a user, I want the city/region resolved from the recognized plate code, so that I know where the vehicle is registered.

#### Acceptance Criteria

1. WHEN the System starts, THE Model_Registry SHALL load the City_Lookup from the Reference_Project `Plates/city_plateinfo.txt` file.
2. WHEN a plate is recognized, THE Recognition_Service SHALL extract the city code from the recognized plate text.
3. WHEN the extracted city code exists in the City_Lookup, THE Recognition_Service SHALL include the resolved region name as the `region` field of the Recognition_Result.
4. WHEN the extracted city code does not exist in the City_Lookup, THE Recognition_Service SHALL set the `region` field to the value `"Unknown"`.
5. THE Recognition_Service SHALL include the extracted city code as the `city_code` field of the Recognition_Result.

### Requirement 5: Singleton Model Loading at Startup

**User Story:** As a system operator, I want all models loaded once at startup, so that requests are not slowed by repeated model loading.

#### Acceptance Criteria

1. WHEN the Backend starts, THE Model_Registry SHALL load the Plate_Detector_Model, Char_Model, Car_Detector_Model, and Color_Model into memory.
2. THE Model_Registry SHALL hold each loaded model as a single shared instance for the lifetime of the Backend process.
3. WHEN a Detection_Pipeline processes an image or frame, THE Recognition_Service SHALL reuse the already-loaded Model_Registry instances rather than loading any model per request.
4. WHERE more than one request is processed, THE Model_Registry SHALL serve every request from the same loaded model instances.

### Requirement 6: Graceful Degradation on Model Load Failure

**User Story:** As a system operator, I want the System to keep working when an optional model fails to load, so that a single missing or corrupt weight does not take the whole service down.

#### Acceptance Criteria

1. IF the Plate_Detector_Model fails to load at startup, THEN THE Model_Registry SHALL log the failure with the model name and the underlying error.
2. IF the Char_Model fails to load at startup, THEN THE Model_Registry SHALL log the failure with the model name and the underlying error.
3. IF the Color_Model fails to load at startup, THEN THE Backend SHALL continue startup in Degraded_Operation and THE Recognition_Service SHALL set the `car_color` field to `null` for all results.
4. IF the Car_Detector_Model fails to load at startup, THEN THE Backend SHALL continue startup in Degraded_Operation and THE Recognition_Service SHALL set the `car_type` field and the `bounding_box.car` field to `null` for all results.
5. WHEN any model fails to load, THE Model_Registry SHALL record the load status of each model so that callers can determine which capabilities are available.

### Requirement 7: Output JSON Contract

**User Story:** As a frontend developer, I want a stable structured result for each recognition, so that I can render plate and vehicle attributes consistently.

#### Acceptance Criteria

1. THE Recognition_Service SHALL produce each Recognition_Result with the fields `plate_text`, `city_code`, `region`, `car_color`, `car_type`, `confidence`, `timestamp`, and `bounding_box`.
2. THE Recognition_Service SHALL always populate the `plate_text`, `city_code`, and `region` fields with non-null values for every Recognition_Result.
3. WHERE car color recognition did not produce a result, THE Recognition_Service SHALL set the `car_color` field to `null`.
4. WHERE car type recognition did not produce a result, THE Recognition_Service SHALL set the `car_type` field to `null`.
5. THE Recognition_Service SHALL populate the `bounding_box` field with a `plate` entry expressed as `[x, y, w, h]` pixel coordinates.
6. WHERE a car was not detected, THE Recognition_Service SHALL set the `bounding_box.car` field to `null`.
7. THE Recognition_Service SHALL express the `confidence` field as a number between 0 and 1 inclusive.
8. THE Recognition_Service SHALL express the `timestamp` field as an ISO 8601 datetime string.

### Requirement 8: Preserve Existing Detection Pipelines

**User Story:** As a user, I want image upload, video upload, and live camera recognition to keep working after the upgrade, so that no existing capability is lost.

#### Acceptance Criteria

1. WHEN a user uploads an image, THE System SHALL run recognition through the Recognition_Service and return Recognition_Results.
2. WHEN a user uploads a video, THE System SHALL run recognition through the Recognition_Service and return Recognition_Results.
3. WHEN a user provides a live camera or RTSP feed, THE System SHALL run recognition through the Recognition_Service and return Recognition_Results.
4. THE Backend SHALL keep the existing detection endpoint URLs unchanged.
5. THE System SHALL retain the existing image, video, and live-feed input handling after the model upgrade.

### Requirement 9: Frame Sampling for Video and Live Feed

**User Story:** As a system operator, I want video and live feeds to process every Nth frame, so that recognition stays performant on continuous input.

#### Acceptance Criteria

1. WHILE processing a video, THE Recognition_Service SHALL submit only every Nth frame for recognition, where N is the Frame_Sampling_Interval.
2. WHILE processing a live camera or RTSP feed, THE Recognition_Service SHALL submit only every Nth frame for recognition, where N is the Frame_Sampling_Interval.
3. WHERE no Frame_Sampling_Interval is configured, THE Recognition_Service SHALL use a default value of 5.
4. THE Recognition_Service SHALL accept the Frame_Sampling_Interval as a configurable value.

### Requirement 10: Result-Based Error Handling

**User Story:** As a backend developer, I want recognition errors returned as values rather than raised exceptions, so that callers handle failures predictably without crashing the pipeline.

#### Acceptance Criteria

1. WHEN a recognition operation succeeds, THE Recognition_Service SHALL return a Result_Type carrying the Recognition_Result.
2. IF a recognition operation fails, THEN THE Recognition_Service SHALL return a Result_Type carrying an error value describing the failure.
3. THE Recognition_Service SHALL return a Result_Type to callers rather than allowing a raised exception to propagate to the caller.
4. WHEN the Recognition_Service returns an error Result_Type, THE Detection_Pipeline SHALL continue processing subsequent images or frames.

### Requirement 11: Code Quality Standards for the Backend

**User Story:** As a backend developer, I want the new backend code to follow consistent typing and documentation standards, so that the wrapper is maintainable.

#### Acceptance Criteria

1. THE Recognition_Service SHALL provide type hints on every public method signature.
2. THE Recognition_Service SHALL provide a docstring on every public method.
3. THE Model_Registry SHALL provide type hints and docstrings on every public method.
4. THE Backend SHALL target Python 3.11 or newer and ultralytics 8.0 or newer.

### Requirement 12: Display New Vehicle Attributes in the Flutter Results Screen

**User Story:** As a user, I want car color, car type, and region shown in the results screen, so that I can read the new attributes alongside the plate text.

#### Acceptance Criteria

1. WHEN a Recognition_Result is displayed, THE Results_Screen SHALL show the `car_color`, `car_type`, and `region` fields as Info_Cards positioned below the existing plate text result.
2. WHERE a displayed Recognition_Result has a `car_color` value of `null`, THE Results_Screen SHALL show a placeholder dash in the car color Info_Card.
3. WHERE a displayed Recognition_Result has a `car_type` value of `null`, THE Results_Screen SHALL show a placeholder dash in the car type Info_Card.
4. THE Results_Screen SHALL retain the existing plate text result display unchanged.
5. THE Results_Screen SHALL source all displayed labels from the Localization_Constants rather than hardcoded strings.

### Requirement 13: Preserve Existing Flutter Input Screens

**User Story:** As a user, I want the existing camera, upload, and video picker screens to stay the same, so that the way I provide input does not change.

#### Acceptance Criteria

1. THE System SHALL retain the existing Flutter camera screen unchanged.
2. THE System SHALL retain the existing Flutter image upload screen unchanged.
3. THE System SHALL retain the existing Flutter video picker screen unchanged.
4. WHERE a new vehicle attribute has no existing UI, THE System SHALL add a new Info_Card widget rather than modifying an existing input screen.

### Requirement 14: Bounding Box Overlay in the Flutter UI

**User Story:** As a user, I want plate and car bounding boxes drawn over the image or frame, so that I can see what was detected.

#### Acceptance Criteria

1. WHEN a Recognition_Result includes a `bounding_box.plate` value, THE Results_Screen SHALL draw a plate overlay box at the given coordinates over the image or frame.
2. WHEN a Recognition_Result includes a non-null `bounding_box.car` value, THE Results_Screen SHALL draw a car overlay box at the given coordinates over the image or frame.
3. WHERE a Recognition_Result has a `bounding_box.car` value of `null`, THE Results_Screen SHALL draw only the plate overlay box.
4. THE Results_Screen SHALL draw the bounding box overlay for image input, video frame input, and live camera frame input.

### Requirement 15: Null-Safe Handling of Nullable Result Fields in Flutter

**User Story:** As a user, I want the results screen to handle missing attributes without errors, so that degraded results still display cleanly.

#### Acceptance Criteria

1. WHEN the Flutter client parses a Recognition_Result, THE System SHALL treat the `car_color`, `car_type`, and `bounding_box.car` fields as nullable.
2. IF the `car_color` field is `null`, THEN THE Results_Screen SHALL display a placeholder dash without raising a runtime error.
3. IF the `car_type` field is `null`, THEN THE Results_Screen SHALL display a placeholder dash without raising a runtime error.
4. IF the `bounding_box.car` field is `null`, THEN THE Results_Screen SHALL omit the car overlay box without raising a runtime error.

### Requirement 16: Explicit Dependency Declaration

**User Story:** As a developer, I want every new dependency listed explicitly, so that the build is reproducible.

#### Acceptance Criteria

1. WHERE the upgrade introduces a new Python dependency, THE Backend SHALL declare that dependency with a pinned version in the Python dependency manifest.
2. WHERE the upgrade introduces a new Flutter or Dart dependency, THE System SHALL declare that dependency with a pinned version in the Flutter dependency manifest.
3. THE Backend SHALL declare ultralytics with a version of 8.0 or newer in the Python dependency manifest.
