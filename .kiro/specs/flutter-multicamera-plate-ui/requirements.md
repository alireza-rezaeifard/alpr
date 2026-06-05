# Requirements Document

## Introduction

This feature replaces the existing React web frontend (`frontend/`) of the Persian License Plate Recognition system with a new, modern Flutter application targeting Windows desktop and Web. The Flutter client consumes the existing Python FastAPI backend (`api.py`, `db.py`, `video_processor.py`) and an extended version of that backend that adds: concurrent multi-camera RTSP processing, user-configurable per-source frame sampling, and an Iranian license plate categorization/metadata reference module.

The feature is organized around five goals:

1. A polished Flutter UI that recreates the existing views (Dashboard, Detection, History, Analytics, Sessions) over the existing API endpoints.
2. Multi-camera RTSP support: add, name, and run an arbitrary number of named cameras concurrently with per-camera live view and per-camera results.
3. Frame-sampled plate reading during smooth playback: video (uploaded or RTSP) plays at normal speed while recognition runs on a configurable frame interval (e.g., every 24th frame).
4. Iranian plate categorization and details: derive plate category, color scheme, and province/region from the recognized plate and present a details panel, backed by a new reference/lookup module and metadata endpoint.
5. Verification: testing of backend endpoints, plate categorization correctness, multi-camera concurrency, and frame-sampling behavior.

The existing backend already exposes: `/api/stats`, `/api/detections` (+ `/timeline`, `/letters`, `/sources`, `/confidence`), `/api/sessions`, `/api/detect/image`, `/api/detect/video` (+ `/{task_id}` status, `/{task_id}/stop`), `/api/detect/rtsp` (+ `/{task_id}` status, `/{task_id}/stop`), `/api/health`, and static `/media`. It also already supports a `skip_frames` parameter on video and RTSP processing. These requirements build on those capabilities.

## Glossary

- **Flutter_Client**: The new Flutter application running on Windows desktop and Web that replaces the existing React frontend.
- **Backend_API**: The Python FastAPI service defined in `api.py` (and its extensions) that the Flutter_Client consumes.
- **Plate_Metadata_Service**: A new backend reference/lookup module (and its API endpoint) that derives Iranian plate category, color scheme, and province/region from a recognized plate.
- **Camera_Manager**: The backend component that creates, tracks, and tears down concurrent RTSP stream processors, each represented by a task identifier.
- **RTSP_Processor**: A single concurrent stream processor instance (`RTSPStreamProcessor`) bound to one camera source and task identifier.
- **Camera**: A user-defined RTSP source with a user-assigned name, a source URL, and a sampling interval.
- **Detection**: A recognized license plate record containing at minimum a recognized plate string (`plate_dtrb`), a Persian-formatted plate (`plate_persian`), a confidence value, a source type, and a timestamp.
- **Sampling_Interval**: The positive integer N such that every Nth decoded frame of a source is submitted for plate recognition; corresponds to the existing `skip_frames` parameter.
- **Playback_Stream**: The visual video feed displayed to the user at normal playback speed, independent of the Sampling_Interval.
- **Plate_Category**: The classification of a plate (for example: Private, Public/Taxi, Government, Military/Police, Diplomatic, Public_Transport, Disabled, Temporary/Transit, Free_Zone/Arvand, Agricultural, Motorcycle) derived from its letter and color scheme.
- **Region_Code**: The two right-most digits of an Iranian plate that map to a vehicle registration region/province.
- **Color_Scheme**: The background and text color convention associated with a Plate_Category (for example white, yellow, green, red, blue, black).
- **View**: A top-level screen of the Flutter_Client: Dashboard, Detection, History, Analytics, or Sessions.
- **Concurrency_Limit**: The user-configured maximum number of RTSP_Processors permitted to run simultaneously.

## Requirements

### Requirement 1: Flutter Application Shell and Navigation

**User Story:** As an operator, I want a modern Flutter application on Windows desktop and Web with navigation across all views, so that I can replace the legacy React interface with a polished experience.

#### Acceptance Criteria

1. THE Flutter_Client SHALL build and run as a Windows desktop application and as a Web application from a single codebase.
2. THE Flutter_Client SHALL provide navigation to the Dashboard, Detection, History, Analytics, and Sessions views.
3. WHEN the user selects a navigation entry, THE Flutter_Client SHALL display the corresponding view within 1 second.
4. THE Flutter_Client SHALL change the active view only in response to an explicit user navigation selection.
5. THE Flutter_Client SHALL read the Backend_API base URL from a runtime configuration value.
6. WHILE no view has been selected by the user, THE Flutter_Client SHALL display the Dashboard view as the default view on startup.
7. IF the Backend_API connectivity check does not succeed within 5 seconds on startup, THEN THE Flutter_Client SHALL display the Dashboard view together with a connection-error indicator and SHALL keep navigation available.
8. IF the Backend_API base URL configuration value is missing or invalid, THEN THE Flutter_Client SHALL display a configuration-error indicator and SHALL NOT attempt a backend connection.
9. IF a selected view fails to render, THEN THE Flutter_Client SHALL retain the previously displayed view and SHALL display an error indicator.

### Requirement 2: Backend Connectivity and Health

**User Story:** As an operator, I want the Flutter client to verify backend availability, so that I know whether the system is operational.

#### Acceptance Criteria

1. WHEN the Flutter_Client starts, THE Flutter_Client SHALL request `/api/health` from the Backend_API with a request timeout of 5 seconds.
2. WHEN the `/api/health` request returns a successful response whose `status` field equals `ok` within the timeout, THE Flutter_Client SHALL display a connected indicator.
3. IF the `/api/health` request returns an unsuccessful response, returns a `status` value other than `ok`, or does not complete within 5 seconds, THEN THE Flutter_Client SHALL display a disconnected indicator and SHALL provide a retry control.
4. IF the Flutter_Client is unable to send the `/api/health` request, THEN THE Flutter_Client SHALL continue startup and display a disconnected indicator.
5. THE Backend_API SHALL respond to `/api/health` with a JSON object containing a string `status` field whose value is `ok` when the service is operational.
6. WHILE the Flutter_Client is displaying a disconnected indicator, THE Flutter_Client SHALL re-request `/api/health` at an interval of 30 seconds.
7. WHEN the user activates the retry control, THE Flutter_Client SHALL re-request `/api/health` and SHALL update the connectivity indicator according to the response.

### Requirement 3: Dashboard View

**User Story:** As an operator, I want a dashboard summarizing system activity, so that I can see overall detection metrics at a glance.

#### Acceptance Criteria

1. WHEN the Dashboard view is opened, THE Flutter_Client SHALL request `/api/stats` and display total detections, unique plates, total sessions, and average confidence.
2. WHEN the Dashboard view is opened, THE Flutter_Client SHALL request `/api/detections/timeline`, `/api/detections/sources`, `/api/detections/confidence`, and `/api/detections/letters` and render each as a chart.
3. WHEN the Dashboard view is opened, THE Flutter_Client SHALL request the 10 most recent detections from `/api/detections` using the `limit` query parameter set to 10, ordered by descending timestamp, and display them in a recent-detections list.
4. WHILE one or more Dashboard data requests are in progress, THE Flutter_Client SHALL display a loading indicator.
5. IF `/api/stats` reports `avg_confidence` as null, THEN THE Flutter_Client SHALL display a non-numeric placeholder for average confidence.
6. WHEN the average confidence value is displayed, THE Flutter_Client SHALL format the value as a percentage with one decimal place.
7. IF the `/api/stats` request fails or does not respond within 10 seconds, THEN THE Flutter_Client SHALL display an error indicator in place of the summary metrics and SHALL provide a retry control.
8. IF an individual chart request among `/api/detections/timeline`, `/api/detections/sources`, `/api/detections/confidence`, and `/api/detections/letters` fails or does not respond within 10 seconds, THEN THE Flutter_Client SHALL display an error indicator for that chart and SHALL render the charts whose requests succeeded.
9. IF the recent-detections request to `/api/detections` fails or does not respond within 10 seconds, THEN THE Flutter_Client SHALL display an error indicator in the recent-detections list and SHALL provide a retry control.

### Requirement 4: History View

**User Story:** As an operator, I want a searchable, filterable detection history, so that I can review past plate detections.

#### Acceptance Criteria

1. WHEN the History view is opened, THE Flutter_Client SHALL request `/api/detections` with `limit` set to 50 and `offset` set to 0, and display each returned detection's timestamp, plate, source type, confidence, and source file.
2. WHEN the user selects a source-type filter of image, video, rtsp, or all, THE Flutter_Client SHALL request `/api/detections` with the selected `source_type` value and `offset` reset to 0.
3. WHEN the user has stopped changing the plate search term for 300 milliseconds, THE Flutter_Client SHALL request `/api/detections` with the `search` query parameter set to the entered term and `offset` reset to 0.
4. WHEN a `/api/detections` response is received, THE Flutter_Client SHALL display the total record count reported by the response `total` field.
5. WHILE the `total` value reported by `/api/detections` exceeds the current `limit`, THE Flutter_Client SHALL provide controls that request subsequent pages using the `limit` (constrained to 1 through 1000) and `offset` query parameters.
6. IF a `/api/detections` request fails to complete or returns a non-success response, THEN THE Flutter_Client SHALL display an error indication that the history could not be loaded and SHALL retain the previously displayed results.
7. WHEN a `/api/detections` response contains zero records in its `data` field, THE Flutter_Client SHALL display an empty-state message indicating that no detections match the current source-type filter and search term.

### Requirement 5: Analytics View

**User Story:** As an operator, I want detailed analytics with an adjustable time range, so that I can analyze detection trends.

#### Acceptance Criteria

1. WHEN the Analytics view is opened, THE Flutter_Client SHALL request `/api/detections/timeline` with the `days` parameter set to 7, and SHALL request `/api/detections/sources`, `/api/detections/confidence`, and `/api/detections/letters`, and SHALL render each response's `data` array as a chart.
2. WHEN the user selects a timeline range of 7, 14, 30, or 90 days, THE Flutter_Client SHALL request `/api/detections/timeline` with the `days` parameter set to the selected value.
3. THE Backend_API SHALL accept a `days` value between 1 and 90 inclusive for `/api/detections/timeline`.
4. WHEN the letter-frequency dataset is rendered, THE Flutter_Client SHALL order the entries by descending count, and SHALL order entries with equal counts in ascending order of their letter value.
5. WHEN a chart endpoint returns an empty `data` array, THE Flutter_Client SHALL display an empty-state message in place of that chart while continuing to render the other charts.
6. IF a request to `/api/detections/timeline`, `/api/detections/sources`, `/api/detections/confidence`, or `/api/detections/letters` fails or times out, THEN THE Flutter_Client SHALL display an error indicator for the affected chart and SHALL continue rendering the charts whose requests succeeded.
7. IF a `days` value less than 1 or greater than 90 is supplied to `/api/detections/timeline`, THEN THE Backend_API SHALL reject the request with a validation error and SHALL NOT return timeline data.

### Requirement 6: Sessions View

**User Story:** As an operator, I want a list of processing sessions, so that I can review each run's source, status, plate count, and duration.

#### Acceptance Criteria

1. WHEN the Sessions view is opened, THE Flutter_Client SHALL request `/api/sessions` with the `limit` parameter set to a value between 1 and 100 inclusive (default 20) and display each returned session's start time, source type, status, total plates, and duration.
2. WHEN the user activates the refresh control, THE Flutter_Client SHALL request `/api/sessions` again and replace the displayed list with the sessions returned by that response.
3. WHEN a session has both a start time and an end time, THE Flutter_Client SHALL display the session duration as a non-negative integer number of seconds computed as the difference between the end time and the start time.
4. WHEN a session has a start time but no end time, THE Flutter_Client SHALL display a running-duration indicator in place of a computed duration value.
5. WHERE a session status is running, done, or error, THE Flutter_Client SHALL render that status value with a visual style distinguishable from the other two status values.
6. IF the `/api/sessions` request fails, does not respond within 10 seconds, or returns an error status, THEN THE Flutter_Client SHALL display an error indicator, provide a retry control, and retain the previously displayed session list.

### Requirement 7: Image Detection

**User Story:** As an operator, I want to upload an image for plate detection, so that I can recognize plates in still photos.

#### Acceptance Criteria

1. WHEN the user selects an image file in JPEG, PNG, or BMP format no larger than 10 megabytes and submits it, THE Flutter_Client SHALL send the file to `/api/detect/image` as multipart form data.
2. WHEN the `/api/detect/image` response is received, THE Flutter_Client SHALL display the annotated image and the list of recognized plates, each with its confidence value formatted as a percentage with one decimal place.
3. IF the `/api/detect/image` response contains no plates, THEN THE Flutter_Client SHALL display a no-plate-detected message.
4. IF the Backend_API returns an error status for `/api/detect/image`, THEN THE Flutter_Client SHALL display an error message indicating that the image could not be processed and including the returned status.
5. WHILE the image detection request is in progress, THE Flutter_Client SHALL display a processing indicator and disable the submit control.
6. WHILE the image detection request is in progress, THE Flutter_Client SHALL continue to display previously rendered plate lists and error messages.
7. IF the user selects a file whose format is not JPEG, PNG, or BMP or whose size exceeds 10 megabytes, THEN THE Flutter_Client SHALL prevent submission and SHALL display a file-validation message.
8. WHEN the image detection request completes, whether successfully or with an error, THE Flutter_Client SHALL clear the processing indicator and re-enable the submit control.
9. IF the image detection request does not complete within 60 seconds, THEN THE Flutter_Client SHALL clear the processing indicator, re-enable the submit control, and display a timeout error message.
10. WHEN the user selects a recognized plate from the results, THE Flutter_Client SHALL open the plate details panel for that plate.

### Requirement 8: Video Detection with Smooth Playback and Frame Sampling

**User Story:** As an operator, I want to upload a video that plays smoothly while plates are read on a configurable frame interval, so that recognition cadence does not slow down display.

#### Acceptance Criteria

1. WHEN the user selects a video file and submits it, THE Flutter_Client SHALL send the file and the configured Sampling_Interval to `/api/detect/video` as multipart form data using the `skip_frames` field.
2. WHILE a video detection task status is queued, opening, or processing, THE Flutter_Client SHALL poll `/api/detect/video/{task_id}` at an interval of 1000 milliseconds and SHALL display the task status, the processed-frame progress percentage computed as (`frame_idx` ÷ `total_frames`) × 100 rounded to the nearest whole percent when `total_frames` is greater than 0, and the running plate log.
3. WHILE a video is displayed, THE Flutter_Client SHALL play the Playback_Stream at a 1.0× real-time playback rate independently of the configured Sampling_Interval.
4. THE Flutter_Client SHALL accept a user-entered Sampling_Interval as an integer between 1 and 1000 inclusive for video detection.
5. WHEN the configured Sampling_Interval is N, THE Backend_API SHALL submit for plate recognition every decoded frame whose zero-based frame index is a multiple of N.
6. WHEN the user activates the stop control for a running video task, THE Flutter_Client SHALL request `/api/detect/video/{task_id}/stop`.
7. WHEN a video task status becomes done, THE Flutter_Client SHALL provide access to the processed output identified by the status `output_path` via the `/media` path.
8. IF a video task status becomes error after partial output exists, THEN THE Flutter_Client SHALL provide access to the partial processed output via the `/media` path in addition to displaying the error detail.
9. IF a video task status becomes error, THEN THE Flutter_Client SHALL display the error detail returned by the Backend_API.
10. WHILE a video task that previously reported an error has not completed successfully, THE Flutter_Client SHALL keep the previous error detail visible.
11. WHILE a video task status is queued or opening, or the reported `total_frames` is 0, THE Flutter_Client SHALL display an indeterminate progress indicator in place of a progress percentage.
12. WHEN a video task status becomes cancelled, THE Flutter_Client SHALL stop polling that task and display a cancelled state.

### Requirement 9: Sampling Interval Validation

**User Story:** As an operator, I want the sampling interval to be validated, so that invalid values do not break processing.

#### Acceptance Criteria

1. IF a submitted Sampling_Interval is less than 1 or greater than 1000, THEN THE Backend_API SHALL reject the request without creating a processing task or session and SHALL return a validation-error response that identifies Sampling_Interval as the invalid field.
2. IF a submitted Sampling_Interval is not an integer or is outside the range 1 to 1000 inclusive, THEN THE Flutter_Client SHALL prevent submission and SHALL display an input-validation message stating that Sampling_Interval must be an integer between 1 and 1000 inclusive.
3. WHERE the user does not specify a Sampling_Interval for a video source, THE Flutter_Client SHALL apply a default Sampling_Interval of 30.
4. WHERE the user does not specify a Sampling_Interval for an RTSP source, THE Flutter_Client SHALL apply a default Sampling_Interval of 15.

### Requirement 10: Single RTSP Stream Detection

**User Story:** As an operator, I want to start a single RTSP stream for live detection, so that I can recognize plates from a camera feed.

#### Acceptance Criteria

1. WHEN the user submits a non-empty RTSP URL beginning with the `rtsp://` scheme and a Sampling_Interval, THE Flutter_Client SHALL send `url` and `skip_frames` to `/api/detect/rtsp` as form data and SHALL retain the returned `task_id` for polling.
2. IF the user submits an empty RTSP URL or a URL that does not begin with the `rtsp://` scheme, THEN THE Flutter_Client SHALL prevent submission and SHALL display an input-validation message.
3. WHILE an RTSP task status is initialized, connecting, connected, or streaming, THE Flutter_Client SHALL poll `/api/detect/rtsp/{task_id}` at an interval of 1000 milliseconds and display the latest annotated frame, the live detection lines, and the plate history.
4. IF an RTSP task status reports no annotated frame, THEN THE Flutter_Client SHALL retain the last displayed annotated frame or show a waiting placeholder when no frame has yet been received.
5. WHEN the user activates the stop control for a running RTSP task, THE Flutter_Client SHALL request `/api/detect/rtsp/{task_id}/stop` and SHALL stop polling that task.
6. IF an RTSP task status begins with the `error` prefix, THEN THE Flutter_Client SHALL display the error status and SHALL stop polling that task within one poll cycle.
7. WHILE a video is displayed for an RTSP source, THE Flutter_Client SHALL play the Playback_Stream at normal speed independently of the Sampling_Interval.

### Requirement 11: Multi-Camera Management

**User Story:** As an operator, I want to add, name, and remove multiple RTSP cameras, so that I can manage a set of monitored feeds.

#### Acceptance Criteria

1. WHEN the user adds a Camera with an RTSP URL and a name of 0 to 100 characters, THE Camera_Manager SHALL create a Camera record associating the name, URL, and Sampling_Interval, and SHALL apply the documented default Sampling_Interval when none is supplied.
2. THE Flutter_Client SHALL allow creation of a Camera whose name contains no non-whitespace character (an empty name).
3. WHILE a Camera's name contains no non-whitespace character, THE Flutter_Client SHALL prevent that Camera from starting and SHALL display a name-required message.
4. WHEN the user removes a Camera, THE Camera_Manager SHALL stop any associated RTSP_Processor, end any associated session, and delete the Camera record.
5. WHEN the user renames a Camera, THE Flutter_Client SHALL display the updated name in all per-camera views for that Camera.
6. IF the user attempts to assign a Camera a name that matches an existing Camera's name under a case-insensitive, whitespace-trimmed comparison, THEN THE Flutter_Client SHALL reject the assignment and SHALL display a duplicate-name message.
7. THE Flutter_Client SHALL display each Camera's name, connection status as one of {stopped, connecting, connected, error}, and Sampling_Interval in a camera list.
8. THE Camera_Manager SHALL persist each Camera record's name, URL, and Sampling_Interval and SHALL restore the persisted Camera records on restart of the Backend_API.

### Requirement 12: Concurrent Multi-Camera Processing

**User Story:** As an operator, I want an arbitrary number of cameras processed simultaneously up to a configured limit, so that I can monitor many feeds at once.

#### Acceptance Criteria

1. WHEN the user starts multiple Cameras, THE Camera_Manager SHALL run one independent RTSP_Processor per started Camera concurrently, up to the Concurrency_Limit.
2. THE Flutter_Client SHALL allow the user to configure the Concurrency_Limit as an integer between 1 and 64 inclusive.
3. WHILE the number of running RTSP_Processors equals the Concurrency_Limit, IF the user starts an additional Camera, THEN THE Camera_Manager SHALL place the additional Camera into a first-in-first-out queue until a running RTSP_Processor stops.
4. IF an individual RTSP_Processor encounters a stream error, THEN THE Camera_Manager SHALL stop only the failing RTSP_Processor, mark its Camera with an error status, and continue running the other RTSP_Processors without interruption.
5. THE Camera_Manager SHALL associate each RTSP_Processor with a distinct task identifier and a distinct session.
6. WHEN the user stops all Cameras, THE Camera_Manager SHALL stop every running RTSP_Processor, end each associated session, and discard every queued Camera.
7. WHERE the user has not configured a Concurrency_Limit, THE Camera_Manager SHALL apply a default Concurrency_Limit of 4.
8. IF the user submits a Concurrency_Limit that is not an integer or is outside the range 1 to 64 inclusive, THEN THE Flutter_Client SHALL reject the value, retain the previously applied Concurrency_Limit, and display an input-validation message.
9. WHEN a running RTSP_Processor stops or enters an error state while the queue is non-empty, THE Camera_Manager SHALL start the earliest-queued Camera.

### Requirement 13: Per-Camera Live View and Results

**User Story:** As an operator, I want a live view and detection results for each camera individually, so that I can tell which camera produced which plate.

#### Acceptance Criteria

1. WHILE one or more Cameras are running, THE Flutter_Client SHALL display one per-camera panel for each running Camera, each panel showing that Camera's name, its latest annotated frame, and its live detection lines from that Camera's `live_detections` field.
2. WHEN a Detection is produced by a Camera, THE Flutter_Client SHALL attribute the Detection to that Camera's name in the per-camera results.
3. WHILE a Camera's RTSP task is running, THE Flutter_Client SHALL poll that Camera's `/api/detect/rtsp/{task_id}` task status at a fixed interval of 1000 milliseconds and update that Camera's per-camera live view from the returned status.
4. WHEN a Camera's `/api/detect/rtsp/{task_id}` status reports a terminal state of done or error, THE Flutter_Client SHALL stop polling that Camera's task and retain that Camera's last displayed annotated frame and detection lines.
5. WHEN the user selects a single Camera, THE Flutter_Client SHALL display an enlarged live view and the full plate history for that Camera.
6. IF the plate history for a selected Camera fails to load, THEN THE Flutter_Client SHALL display the enlarged live view together with a history-unavailable message and SHALL retain the previously displayed live view.
7. IF a Camera's task status contains no annotated frame or an undecodable annotated frame, THEN THE Flutter_Client SHALL display a frame-unavailable placeholder in that Camera's panel and SHALL continue displaying that Camera's live detection lines.
8. WHILE the number of running Cameras exceeds the count that fits in the visible per-camera grid, THE Flutter_Client SHALL arrange the panels in a scrollable grid that displays every running Camera up to the Concurrency_Limit without overlap.
9. THE Backend_API SHALL include a per-camera identifier in stored detections so that detections can be attributed to their originating Camera.

### Requirement 14: Iranian Plate Metadata Service

**User Story:** As a developer, I want a backend service that derives Iranian plate metadata from a recognized plate, so that the client can present categorized details.

#### Acceptance Criteria

1. WHEN the Plate_Metadata_Service receives a recognized plate value in either Persian or latin (dtrb) letter encoding, THE Plate_Metadata_Service SHALL derive and return the Plate_Category, the Color_Scheme, the Region_Code, and the region/province name.
2. WHEN a plate's Region_Code matches a known registration region in the reference data, THE Plate_Metadata_Service SHALL return the corresponding region/province name.
3. IF a plate's Region_Code does not match any known registration region, THEN THE Plate_Metadata_Service SHALL return an unknown-region indicator.
4. WHEN a plate's letter corresponds to a defined Plate_Category, THE Plate_Metadata_Service SHALL derive the Color_Scheme from that letter and return the corresponding Plate_Category.
5. WHERE a plate corresponds to a Free_Zone/Arvand category, THE Plate_Metadata_Service SHALL return the Free_Zone/Arvand category and any associated special note.
6. IF the recognized plate value does not conform to the known Iranian plate structure (2 digits, 1 letter, 3 digits, and a 2-digit Region_Code), is empty, is null, or contains only whitespace, THEN THE Plate_Metadata_Service SHALL return a not-classified result with a descriptive reason and SHALL NOT return partial metadata.
7. THE Backend_API SHALL expose an endpoint that accepts a supplied plate value in either Persian or latin (dtrb) encoding and returns the derived plate metadata, including not-classified results.
8. WHEN the same plate is supplied once in Persian encoding and once in latin (dtrb) encoding, THE Plate_Metadata_Service SHALL return identical Plate_Category, Color_Scheme, and Region_Code for both.

### Requirement 15: Plate Details Panel in the Client

**User Story:** As an operator, I want a details panel for each detected plate, so that I can see its category, color scheme, region, and special notes.

#### Acceptance Criteria

1. WHEN the user selects a Detection, THE Flutter_Client SHALL request plate metadata from the Backend_API for the selected Detection's recognized plate value and SHALL display the returned Plate_Category, Color_Scheme, region/province name, and any special notes in the details panel.
2. WHILE the plate metadata request is in progress, THE Flutter_Client SHALL display a loading indicator in the details panel.
3. IF the Plate_Metadata_Service returns a not-classified result, THEN THE Flutter_Client SHALL display the not-classified state together with the returned reason in the details panel.
4. WHEN the Color_Scheme is displayed, THE Flutter_Client SHALL render both the Color_Scheme name as text and a color indicator filled with the color corresponding to the returned Color_Scheme value (one of white, yellow, green, red, blue, or black).
5. WHEN a recognized plate's Persian-formatted plate (`plate_persian`) is available, THE Flutter_Client SHALL display the Persian-formatted plate alongside the metadata in the details panel.
6. IF the plate metadata request fails or does not complete within 10 seconds, THEN THE Flutter_Client SHALL stop the loading indicator, display an error indication in the details panel that includes the returned status, and provide a retry control.
7. WHEN the details panel displays Persian text (the Persian-formatted plate, the region/province name, or special notes), THE Flutter_Client SHALL render that text with right-to-left text direction.

### Requirement 16: System Verification and Testing

**User Story:** As a developer, I want the system verified end to end, so that I can trust backend endpoints, plate categorization, multi-camera concurrency, and frame sampling behave correctly.

#### Acceptance Criteria

1. WHEN the integration test suite sends at least one valid request to each of `/api/health`, `/api/stats`, `/api/detections` (including its `/timeline`, `/letters`, `/sources`, and `/confidence` sub-endpoints), `/api/sessions`, and the plate metadata endpoint, THE Backend_API SHALL respond to every such request with a non-error response that contains the data fields documented for that endpoint.
2. FOR ALL plate values whose structure conforms to a known Iranian plate, tested over at least 100 distinct generated values, deriving metadata from a value and re-deriving metadata from the same value SHALL produce identical Plate_Category, Color_Scheme, and Region_Code (idempotence property).
3. FOR ALL known Region_Codes defined in the reference data, the Plate_Metadata_Service SHALL return a region/province name that maps back to that same Region_Code in the reference data (round-trip property).
4. WHEN at least three Cameras are processed concurrently in a test, THE Camera_Manager SHALL assign each Camera a task identifier distinct from every other concurrently running Camera, and SHALL attribute every Detection produced during the test to the Camera that produced it.
5. WHEN a test submits a video with Sampling_Interval N, for each N in a set of at least three distinct positive integers, THE Backend_API SHALL submit for plate recognition exactly the decoded frames whose zero-based frame index is an integer multiple of N.
6. FOR ALL malformed plate inputs that do not conform to a known Iranian plate structure, tested over at least 100 distinct generated values, THE Plate_Metadata_Service SHALL return a not-classified result and SHALL complete without raising an unhandled error (error-condition property).
