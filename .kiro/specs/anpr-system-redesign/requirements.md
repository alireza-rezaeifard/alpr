# Requirements Document

## Introduction

This document specifies requirements for a complete redesign of an existing Persian Automatic
Number Plate Recognition (ANPR) system. The redesign covers two layers:

1. **Frontend** — a Flutter desktop/web client (`flutter_app/`) rebuilt with a modern
   "Professional Security/Monitoring System" look. The frontend uses Fluent UI for Flutter,
   PlutoGrid, Syncfusion Flutter Widgets, Riverpod, and go_router. All user-facing text is in
   Persian (Farsi) with full right-to-left (RTL) layout support.
2. **Backend** — a FastAPI (Python) service modernized from the current implementation. It
   preserves existing detection, camera, and reporting capabilities while adding three new
   capability areas that the current system lacks: authentication, authorization (RBAC), and
   software license management.

The redesign incorporates best practices observed in established commercial ANPR products
(watchlist/hotlist matching with real-time alerts, role-based access control, audit logging,
configurable data retention, searchable and exportable detection records), adapted to the
Iranian/Persian plate domain and the existing YOLOv8 + DTRB detection pipeline.

The system runs as a single deployment: one operator-facing client connecting to one backend
service backed by a SQLite database, supporting multiple concurrent RTSP camera streams.

## Glossary

- **ANPR_System**: The complete redesigned system comprising the Flutter client and the FastAPI backend.
- **Backend**: The FastAPI service exposing REST endpoints, streaming endpoints, and background detection tasks.
- **Client**: The Flutter desktop/web application that operators interact with.
- **Detector**: The YOLOv8 model component that locates license plate regions within an image or frame.
- **Recognizer**: The DTRB (Deep Text Recognition Benchmark) model component that reads characters from a detected plate region.
- **Detection**: A single recognized plate record, including the DTRB text, Persian-formatted plate string, confidence score, source type, timestamp, and optional camera attribution.
- **Session**: A bounded detection run against one source (image, video, or RTSP stream), with start/end timestamps and aggregate counts.
- **Camera**: A persisted RTSP source definition (name, URL, skip-frame setting) that can be started, stopped, and monitored.
- **Camera_Manager**: The Backend component that manages concurrent RTSP processors under a configurable concurrency limit using a FIFO queue.
- **Plate_Metadata**: Classification data derived from a plate string, including category, color scheme, region code, and region name.
- **Pretty_Printer**: The component that formats a recognized plate into the standard Persian display string.
- **Plate_Parser**: The component that normalizes a raw plate string (Persian, Arabic, or Latin digits) into structured plate components.
- **User**: An authenticated person who interacts with the ANPR_System through the Client.
- **Role**: A named set of permissions assigned to a User (Admin, Operator, or Viewer).
- **Permission**: An authorization grant that allows a specific action on a specific resource type.
- **Session_Token**: A signed, time-limited credential issued at login and presented on subsequent requests to prove identity.
- **License**: A software activation record that authorizes use of the ANPR_System within defined limits and an expiry date.
- **License_Key**: The encoded credential a User supplies to activate a License.
- **Watchlist**: A named collection of plate entries flagged for monitoring (for example a blocklist or allowlist).
- **Watchlist_Entry**: A single plate value within a Watchlist, optionally with a label and reason.
- **Alert**: A record generated when a Detection matches a Watchlist_Entry.
- **Audit_Log**: An append-only record of security-relevant actions performed by Users.
- **Report**: A query-driven view or export of Detection and Session data, including analytics aggregations.
- **Retention_Policy**: The configured maximum age beyond which Detection records are eligible for deletion.
- **RTSP**: Real Time Streaming Protocol, used for live network camera feeds.
- **MJPEG**: Motion JPEG, the streaming format used to deliver annotated live frames to the Client.
- **RBAC**: Role-Based Access Control.

## Requirements

### Requirement 1: User Authentication

**User Story:** As a system operator, I want to log in with credentials, so that only authorized people can access the ANPR system.

#### Acceptance Criteria

1. WHEN a User submits a username and password that match a stored account, THE Backend SHALL issue a Session_Token with an expiry timestamp.
2. IF a User submits credentials that do not match any stored account, THEN THE Backend SHALL reject the request with an authentication-failure response and SHALL NOT issue a Session_Token.
3. THE Backend SHALL store user passwords using a one-way salted hash.
4. WHEN a User submits a request with a valid, unexpired Session_Token, THE Backend SHALL process the request as that authenticated User.
5. IF a request presents an expired Session_Token, THEN THE Backend SHALL reject the request with an authentication-required response.
6. IF a request to a protected endpoint presents no Session_Token, THEN THE Backend SHALL reject the request with an authentication-required response.
7. WHEN a User logs out, THE Backend SHALL invalidate the current Session_Token so that subsequent requests using that token are rejected.
8. WHERE a User account is marked disabled, THE Backend SHALL reject login attempts for that account with an authentication-failure response.
9. WHEN the ANPR_System is initialized with no existing user accounts, THE Backend SHALL create one default Admin account.

### Requirement 2: Role-Based Authorization

**User Story:** As an administrator, I want to assign roles to users, so that each user can only perform actions appropriate to their responsibilities.

#### Acceptance Criteria

1. THE Backend SHALL support three Roles: Admin, Operator, and Viewer.
2. WHEN an authenticated User requests an action, THE Backend SHALL permit the action only if the User's Role holds the Permission required for that action.
3. IF an authenticated User requests an action for which the User's Role lacks the required Permission, THEN THE Backend SHALL reject the request with an authorization-denied response.
4. WHEN an authenticated User requests a protected action that defines no specific Permission requirement, THE Backend SHALL still subject the request to an authorization check before permitting the action.
5. THE Backend SHALL grant the Admin Role permission to manage users, manage roles, manage Licenses, manage system configuration, and perform all Operator and Viewer actions.
6. THE Backend SHALL grant the Operator Role permission to manage Cameras, run Detections, and manage Watchlists, in addition to all Viewer actions.
7. THE Backend SHALL grant the Viewer Role permission to view Detections, Sessions, Reports, and live camera streams.
8. WHEN an Admin creates a User, THE Backend SHALL require a username, an initial password, and a Role assignment.
9. WHEN an Admin changes a User's Role, THE Backend SHALL apply the new Role's Permissions to that User's subsequent requests.
10. IF an Admin attempts to delete or disable the last remaining Admin account, THEN THE Backend SHALL reject the request with a validation-error response.

### Requirement 3: Software License Management

**User Story:** As a system owner, I want the software to require a valid license, so that usage stays within authorized limits and the activation period.

#### Acceptance Criteria

1. WHEN a User submits a License_Key, THE Backend SHALL validate the License_Key and, if valid, store an active License record with its expiry date and camera limit.
2. IF a User submits a License_Key that fails validation, THEN THE Backend SHALL reject the activation with a validation-error response and SHALL NOT store an active License.
3. WHILE no active License exists, THE Backend SHALL reject Detection and Camera-start requests with a license-required response.
4. IF the active License expiry date is earlier than the current date, THEN THE Backend SHALL treat the License as expired and reject Detection and Camera-start requests with a license-expired response.
5. WHEN a User requests License status, THE Backend SHALL return the activation state, the expiry date, the camera limit, and the count of configured Cameras.
6. IF a Camera-start request would cause the number of running Cameras to exceed the License camera limit, THEN THE Backend SHALL reject the request with a license-limit response.
7. THE Backend SHALL allow authentication, License activation, and License status retrieval WHILE no active License exists.

### Requirement 4: Camera Management

**User Story:** As an operator, I want to create, edit, and remove camera definitions, so that I can manage the RTSP sources the system monitors.

#### Acceptance Criteria

1. WHEN an Operator submits a Camera with a name, an RTSP URL, and a skip-frame value, THE Backend SHALL persist the Camera and return its assigned identifier.
2. WHEN an Operator requests the camera list, THE Backend SHALL return all persisted Cameras with their current status.
3. WHEN an Operator updates a Camera's name, URL, or skip-frame value, THE Backend SHALL persist the changes and return the updated Camera.
4. IF an Operator updates or deletes a Camera identifier that does not exist, THEN THE Backend SHALL return a not-found response.
5. WHEN an Operator deletes a Camera, THE Backend SHALL stop any running processor for that Camera, close its Session, and remove the Camera record.
6. WHEN the Backend starts, THE Backend SHALL restore each persisted Camera to its last known status recorded before the previous shutdown.
7. THE Backend SHALL restrict the skip-frame value of a Camera to the inclusive range 1 to 1000.

### Requirement 5: Concurrent Camera Streaming

**User Story:** As an operator, I want to start and stop multiple camera streams under a concurrency limit, so that the system stays within its processing capacity.

#### Acceptance Criteria

1. WHEN an Operator starts a Camera AND the count of running Cameras is below the concurrency limit, THE Camera_Manager SHALL start a processor for that Camera and report status running.
2. WHEN an Operator starts a Camera AND the count of running Cameras equals the concurrency limit, THE Camera_Manager SHALL enqueue the Camera and report status queued.
3. WHEN an Operator stops a running Camera, THE Camera_Manager SHALL stop its processor, close its Session, and start the earliest-queued Camera if one is waiting.
4. WHEN an Operator requests start-all, THE Camera_Manager SHALL attempt to start every stopped Camera subject to the concurrency limit.
5. WHEN an Operator requests stop-all, THE Camera_Manager SHALL stop every running Camera, close their Sessions, and clear the queue.
6. WHEN a request sets the concurrency limit to a value within the inclusive range 1 to 64, THE Backend SHALL persist and apply the new limit.
7. IF a request sets the concurrency limit to a value outside the inclusive range 1 to 64, THEN THE Backend SHALL reject the request with a validation-error response.
8. IF a running processor enters an error state, THEN THE Camera_Manager SHALL set the Camera status to error, close its Session, and start the earliest-queued Camera if one is waiting.

### Requirement 6: Live Stream Delivery

**User Story:** As a viewer, I want to watch annotated live camera feeds, so that I can monitor detections in real time.

#### Acceptance Criteria

1. WHILE a Camera processor is streaming, THE Backend SHALL provide an MJPEG stream of annotated frames for that processor.
2. WHEN the Client requests the latest frame for a running processor, THE Backend SHALL return the most recent annotated frame and the processor status.
3. IF the Client requests a stream or frame for a task identifier that does not exist, THEN THE Backend SHALL return a not-found response.
4. WHEN a Detection occurs on a live stream, THE Backend SHALL include the Detection in the processor's recent-detection history returned to the Client.

### Requirement 7: Network Camera Discovery

**User Story:** As an operator, I want to scan my network for RTSP cameras and probe their stream paths, so that I can add cameras without knowing their exact URLs.

#### Acceptance Criteria

1. WHEN an Operator starts a network scan over an IP range, THE Backend SHALL probe the range for RTSP-responsive hosts and report progress as a count of completed checks over a total.
2. WHEN the Backend identifies an RTSP-responsive host, THE Backend SHALL record the host address, port, and detected brand.
3. WHEN an Operator requests scan status, THE Backend SHALL return the running state, the discovered hosts, and the current progress.
4. WHEN an Operator stops a running scan, THE Backend SHALL halt further probing and report the scan as stopped.
5. IF an Operator starts a scan WHILE a scan is already running, THEN THE Backend SHALL reject the request with a conflict response.
6. WHEN an Operator tests an RTSP URL, THE Backend SHALL report whether a frame can be retrieved from that URL.

### Requirement 8: Image Plate Detection

**User Story:** As an operator, I want to upload an image and get recognized plates, so that I can identify vehicles from still photos.

#### Acceptance Criteria

1. WHEN an Operator submits a valid image file, THE Backend SHALL run the Detector and Recognizer and return the recognized plates with their confidence scores and an annotated image.
2. IF an Operator submits a file that cannot be decoded as an image, THEN THE Backend SHALL return a validation-error response.
3. WHEN the Backend completes an image Detection, THE Backend SHALL store each recognized plate as a Detection within a new image Session.
4. IF storing the Detection records for an image Detection fails, THEN THE Backend SHALL fail the entire request with an error response.
5. WHEN the Backend returns a recognized plate, THE Backend SHALL include the Persian-formatted plate string produced by the Pretty_Printer.

### Requirement 9: Video Plate Detection

**User Story:** As an operator, I want to upload a video and track its detection progress, so that I can extract plates from recorded footage.

#### Acceptance Criteria

1. WHEN an Operator submits a video file with a skip-frame value and a processing mode, THE Backend SHALL start a background Detection task and return a task identifier and a Session identifier.
2. WHEN the Client requests the status of a video task, THE Backend SHALL return the processing status, the current frame index, the total frame count, the accumulated plate log, and the latest annotated frame.
3. WHEN an Operator stops a running video task, THE Backend SHALL halt processing, mark the task cancelled, and close its Session immediately.
4. WHEN a video task completes processing, THE Backend SHALL close its Session with the total frame count, total plate count, and unique plate count.
5. IF the Client requests the status of a task identifier that does not exist, THEN THE Backend SHALL return a not-found response.
6. THE Backend SHALL restrict the video skip-frame value to the inclusive range 1 to 1000.

### Requirement 10: RTSP Plate Detection

**User Story:** As an operator, I want to start ad-hoc RTSP detection on a stream URL, so that I can monitor a live feed without first saving it as a camera.

#### Acceptance Criteria

1. WHEN an Operator submits an RTSP URL with a skip-frame value and a processing mode, THE Backend SHALL start an RTSP Detection task and return a task identifier and a Session identifier.
2. WHEN the Client requests the status of an RTSP task, THE Backend SHALL return the processing status, the detection history, and the latest annotated frame.
3. WHEN an Operator stops a running RTSP task, THE Backend SHALL halt the stream, close its Session with the detection counts, and mark the task stopped.
4. WHEN a Detection occurs during an RTSP task, THE Backend SHALL store the Detection within the task's Session.

### Requirement 11: Persian Plate Formatting and Classification

**User Story:** As an operator, I want recognized plates formatted and classified in the Persian standard, so that I can understand each plate's category and region.

#### Acceptance Criteria

1. WHEN the Pretty_Printer receives a recognized plate, THE Pretty_Printer SHALL produce a Persian-formatted plate string.
2. WHEN the Plate_Parser receives a plate string containing Persian, Arabic, or Latin digits, THE Plate_Parser SHALL normalize the digits to a single canonical digit form.
3. WHEN a plate string conforms to the standard Iranian structure of two digits, one letter, three digits, and a two-digit region code, THE Backend SHALL return Plate_Metadata containing the category, color scheme, region code, and region name.
4. IF a plate string does not conform to the standard Iranian structure, THEN THE Backend SHALL return Plate_Metadata marked unclassified with a reason.
5. IF a plate value is empty or contains only whitespace, THEN THE Backend SHALL return Plate_Metadata marked unclassified with a reason.
6. WHERE a plate belongs to a free-zone category, THE Backend SHALL include the free-zone special note in the Plate_Metadata.
7. FOR ALL recognized plates, parsing a plate string and then formatting it with the Pretty_Printer and then parsing the result again SHALL yield equivalent plate components (round-trip property).

### Requirement 12: Watchlist Management and Alerting

**User Story:** As an operator, I want to maintain watchlists of plates and be alerted when they appear, so that I can act on vehicles of interest in real time.

#### Acceptance Criteria

1. WHEN an Operator creates a Watchlist with a name and a list type, THE Backend SHALL persist the Watchlist and return its identifier.
2. WHEN an Operator adds a Watchlist_Entry with a plate value to a Watchlist, THE Backend SHALL persist the entry under that Watchlist.
3. WHEN an Operator removes a Watchlist_Entry, THE Backend SHALL delete that entry from its Watchlist.
4. WHEN a Detection's plate value matches an active Watchlist_Entry, THE Backend SHALL create an Alert that references the Detection and the matched Watchlist_Entry.
5. IF a Watchlist_Entry has been deleted, THEN THE Backend SHALL treat the entry as inactive and SHALL NOT create an Alert for it.
6. WHEN a Viewer requests the Alert list, THE Backend SHALL return Alerts ordered from most recent to least recent.
7. WHEN comparing a Detection plate value to a Watchlist_Entry, THE Backend SHALL normalize both values to the canonical digit form before comparison.

### Requirement 13: Detection Reporting and Analytics

**User Story:** As a viewer, I want to search, filter, and visualize detection data, so that I can analyze plate activity over time.

#### Acceptance Criteria

1. WHEN a Viewer requests Detections with a limit, an offset, a source-type filter, and a search term, THE Backend SHALL return the matching Detections and the total matching count.
2. THE Backend SHALL restrict the Detection list limit to the inclusive range 1 to 1000.
3. WHEN a Viewer requests the detection timeline for a number of days within the inclusive range 1 to 90, THE Backend SHALL return per-day detection counts for that range.
4. WHEN a Viewer requests aggregate statistics, THE Backend SHALL return the total detection count, unique plate count, average confidence, total session count, and recent activity counts.
5. WHEN a Viewer requests the source distribution, THE Backend SHALL return detection counts grouped by source type.
6. WHEN a Viewer requests the confidence distribution, THE Backend SHALL return detection counts grouped into confidence bins.
7. WHEN a Viewer requests the session history with a limit, THE Backend SHALL return Sessions ordered from most recent to least recent.

### Requirement 14: Detection Export

**User Story:** As a viewer, I want to export detection records, so that I can use them in external tools and share them with others.

#### Acceptance Criteria

1. WHEN a Viewer requests an export with a source-type filter and a search term, THE Backend SHALL produce a downloadable file containing the matching Detection records.
2. THE Backend SHALL include the timestamp, source type, DTRB plate text, Persian plate string, and confidence for each Detection in the export.
3. WHERE the export results contain one or more Detections that originated from a Camera, THE Backend SHALL include a camera name column populated with the camera name for each Camera-sourced Detection.
4. IF an export request matches no Detections, THEN THE Backend SHALL produce a file containing only the column headers.

### Requirement 15: Audit Logging

**User Story:** As an administrator, I want security-relevant actions recorded, so that I can review who did what and when.

#### Acceptance Criteria

1. WHEN a User logs in or fails to log in, THE Backend SHALL append an Audit_Log entry recording the username, the action, the outcome, and the timestamp.
2. WHEN a User creates, updates, or deletes a Camera, a User account, a Watchlist, or a License, THE Backend SHALL append an Audit_Log entry recording the User, the action, the affected resource, and the timestamp.
3. WHEN an Admin requests the Audit_Log with a limit greater than zero, THE Backend SHALL return that number of Audit_Log entries ordered from most recent to least recent.
4. WHEN an Admin requests the Audit_Log with a limit of zero, THE Backend SHALL return all Audit_Log entries ordered from most recent to least recent.
5. THE Backend SHALL reject any request to modify or delete existing Audit_Log entries.

### Requirement 16: Data Retention

**User Story:** As an administrator, I want old detection data automatically pruned, so that storage stays bounded and retention complies with policy.

#### Acceptance Criteria

1. WHEN an Admin sets a Retention_Policy to a number of days greater than zero, THE Backend SHALL persist the Retention_Policy.
2. WHILE a Retention_Policy is active, THE Backend SHALL delete Detection records whose timestamp is older than the Retention_Policy period.
3. WHERE no Retention_Policy is configured, THE Backend SHALL retain all Detection records.
4. IF an Admin sets a Retention_Policy to a value of zero or less, THEN THE Backend SHALL reject the request with a validation-error response.

### Requirement 17: Persian RTL Fluent User Interface

**User Story:** As a Persian-speaking operator, I want the entire interface in Persian with right-to-left layout, so that I can use the system naturally in my language.

#### Acceptance Criteria

1. THE Client SHALL render all user-facing text in the Persian language.
2. THE Client SHALL lay out all screens in right-to-left reading order.
3. THE Client SHALL render the interface using the Fluent design language.
4. THE Client SHALL display numeric data, dates, and times using Persian-locale formatting.
5. WHERE a screen presents tabular data, THE Client SHALL render the table using a data grid with sorting and column controls.
6. WHERE a screen presents analytics, THE Client SHALL render charts and gauges visualizing the analytics data.

### Requirement 18: Client Navigation and Session Handling

**User Story:** As a user, I want consistent navigation and automatic handling of my login session, so that I can move through the app and stay secure.

#### Acceptance Criteria

1. WHILE no valid Session_Token is held, THE Client SHALL present the login screen and SHALL restrict access to protected screens.
2. WHEN a User authenticates successfully, THE Client SHALL store the Session_Token and navigate to the dashboard.
3. WHEN the Client receives an authentication-required response from the Backend, THE Client SHALL clear the stored Session_Token and return the User to the login screen.
4. WHERE a User's Role lacks the Permission for a screen action, THE Client SHALL hide or disable the control for that action.
5. WHEN a User selects a navigation destination, THE Client SHALL route to the corresponding screen while preserving the authenticated session.
