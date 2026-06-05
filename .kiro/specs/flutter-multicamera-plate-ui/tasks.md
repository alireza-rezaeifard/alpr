# Implementation Plan: Flutter Multi-Camera Plate UI

## Overview

This plan implements a Flutter client (Windows + Web, single codebase) that replaces the legacy React
frontend, plus additive backend extensions for multi-camera RTSP concurrency, frame-sampling validation,
plate metadata derivation, and per-camera detection attribution. Backend work is in Python; client work is
in Dart/Flutter. Tasks are ordered so each step builds on the previous and ends with all pieces wired
together.

## Tasks

- [x] 1. Backend foundation — DB schema migration and extended `save_detection`
  - [x] 1.1 Add `cameras` and `app_config` tables and migrate `detections` in `db.py`
    - In `init_db()`, add `CREATE TABLE IF NOT EXISTS cameras (...)` and `app_config (...)` as specified
      in the design's SQLite schema section
    - Add `_ensure_column` helper and call it for `detections.camera_id` and `detections.camera_name`
      after the `CREATE TABLE` block so the migration is safe to re-run on an existing database
    - _Requirements: 11.1, 11.8, 13.9_

  - [x] 1.2 Extend `save_detection` and add Camera CRUD helpers in `db.py`
    - Add optional `camera_id` and `camera_name` parameters (defaulting `None`) to `save_detection` and
      update its `INSERT` statement to include the two new columns
    - Add `create_camera`, `list_cameras`, `get_camera`, `update_camera`, `delete_camera` functions
      using the `cameras` table
    - Add `get_concurrency_limit` / `set_concurrency_limit` helpers that read/write the `app_config` table
      with key `concurrency_limit`, defaulting to 4
    - _Requirements: 11.1, 11.8, 12.7, 13.9_

  - [ ]* 1.3 Write property test for camera persistence round-trip
    - **Property 10: Camera persistence round-trip**
    - **Validates: Requirements 11.1, 11.8**
    - Use Hypothesis; generate random `(name, url, skip_frames | None)` tuples; call `create_camera`,
      reload via `get_camera`, assert name/url equal and skip_frames equals supplied value or default 15

- [x] 2. Backend: `plate_reference.py` and `plate_metadata.py`
  - [x] 2.1 Implement `plate_reference.py` with `LETTER_TO_CATEGORY`, `CATEGORY_TO_COLOR`, and
    `REGION_CODE_TO_PROVINCE`
    - Create `plate_reference.py` with the full dictionaries from the design's reference data section
    - Include every entry in the design table for letters, categories, color schemes, and region codes
    - _Requirements: 14.4, 14.2_

  - [x] 2.2 Implement `plate_metadata.py` — `normalize_plate` and `derive_metadata`
    - Implement `normalize_plate(raw) -> NormalizedPlate | None` following the design's 4-step strategy
      (reject empty, normalize Persian digits/letters, strip separators, validate token shape)
    - Build `PERSIAN_TO_CATEGORY` by mapping each Persian letter back through `DTRB_TO_PERSIAN` to its
      canonical category key in `LETTER_TO_CATEGORY`
    - Implement `derive_metadata(raw) -> PlateMetadata` that is total (never raises), returns
      `classified=False` with a reason for all malformed/empty/whitespace/null inputs, and returns
      `classified=True` with full metadata for conforming plates
    - _Requirements: 14.1, 14.3, 14.4, 14.5, 14.6, 14.8_

  - [ ]* 2.3 Write property test — metadata idempotence and encoding independence (Property 1)
    - **Property 1: Plate metadata derivation is idempotent and encoding-independent**
    - **Validates: Requirements 14.1, 14.4, 14.8, 16.2**
    - Generate conforming plates in both Persian and latin encodings; assert `derive_metadata` twice from
      the same value returns identical `category`, `color_scheme`, `region_code`; assert Persian-encoded
      and latin-encoded variants return identical results

  - [ ]* 2.4 Write property test — region-code round-trip and unknown-region handling (Property 2)
    - **Property 2: Region-code round-trip and unknown-region handling**
    - **Validates: Requirements 14.2, 14.3, 16.3**
    - For each known region code in `REGION_CODE_TO_PROVINCE`, assert the returned `region_name` maps
      back to that code; for random 2-digit strings absent from the map, assert the service returns the
      unknown-region indicator while still classifying by letter

  - [ ]* 2.5 Write property test — metadata never raises on malformed input (Property 3)
    - **Property 3: Metadata derivation never raises on malformed input**
    - **Validates: Requirements 14.6, 16.6**
    - Generate empty strings, whitespace-only, wrong-length, and arbitrary garbage values; assert
      `derive_metadata` always returns `classified=False` with a non-empty `reason` and never raises

- [x] 3. Backend: frame-sampling validation and `should_sample` extraction
  - [x] 3.1 Extract `should_sample(frame_index, skip_frames)` pure function in `video_processor.py`
    - Add `def should_sample(frame_index: int, skip_frames: int) -> bool: return frame_index % skip_frames == 0`
    - Replace the inline `frame_idx % skip_frames == 0` guard in `_run` with a call to `should_sample`
    - _Requirements: 8.5_

  - [x] 3.2 Add `ge=1, le=1000` constraints to `skip_frames` in `api.py` video and RTSP endpoints
    - Change `skip_frames: int = Form(30)` to `Form(30, ge=1, le=1000)` in `detect_video`
    - Change `skip_frames: int = Form(15)` to `Form(15, ge=1, le=1000)` in `detect_rtsp`
    - No other handler logic changes; FastAPI returns 422 before any session/task is created
    - _Requirements: 9.1_

  - [ ]* 3.3 Write property test — frame sampling submits exactly multiples of N (Property 4)
    - **Property 4: Frame-sampling submits exactly the multiples of N**
    - **Validates: Requirements 8.5, 16.5**
    - Use Hypothesis; for random N in 1..1000 and T in 0..5000, assert
      `{i for i in range(T) if should_sample(i, N)} == {i for i in range(T) if i % N == 0}`

  - [ ]* 3.4 Write property test — sampling-interval validation has no side effects (Property 7)
    - **Property 7: Sampling-interval validation rejects out-of-range values without side effects**
    - **Validates: Requirements 9.1, 9.2**
    - Use `httpx` or `requests` against a test FastAPI `TestClient`; submit skip_frames outside 1..1000;
      assert 422 is returned and no row is inserted in `sessions`

- [x] 4. Backend: `schemas.py`, camera endpoints, and `Camera_Manager`
  - [x] 4.1 Create `schemas.py` with all new Pydantic models
    - Define `CameraCreate`, `CameraUpdate`, `CameraView`, `StartResult`, `ConcurrencyConfig`,
      `ConcurrencyView`, and `PlateMetadata` exactly as specified in the design's schemas section
    - _Requirements: 11.1, 12.2, 14.7_

  - [x] 4.2 Implement `camera_manager.py` — `CameraManager` with concurrency and FIFO queue
    - Implement the class with `_lock`, `_cameras: dict[int, CameraRuntime]`, `_queue: deque[int]`,
      and `_concurrency_limit` (loaded from `get_concurrency_limit()`)
    - Implement `add_camera`, `list_cameras`, `update_camera`, `remove_camera` (write-through to DB)
    - Implement `start_camera`: if `len(running) < limit` start processor immediately, else enqueue;
      return `StartResult` with status `running` or `queued`
    - Implement `stop_camera`: stop processor, end session, free slot, call `_promote_from_queue()`
    - Implement `_promote_from_queue()` as the single choke-point; pops earliest queued camera and
      starts it if a slot is free
    - Implement `start_all`, `stop_all` (stops running, discards queue), `set_concurrency_limit`
    - Implement `restore_on_startup()`: load all `cameras` rows into `_cameras` with `status=stopped`
    - _Requirements: 11.1, 11.4, 11.8, 12.1, 12.3, 12.4, 12.5, 12.6, 12.7, 12.9_

  - [x] 4.3 Register camera and concurrency endpoints in `api.py`
    - Add `on_detection_factory(session_id, camera_id, camera_name)` closure builder
    - Register all 11 new endpoints from the design's endpoint table using `CameraManager` singleton
    - Register `/api/plate/metadata` GET endpoint calling `derive_metadata` and returning `PlateMetadata`
    - Call `camera_manager.restore_on_startup()` in app startup event
    - _Requirements: 11.2, 11.4, 11.5, 12.1, 12.2, 12.3, 12.6, 12.7, 12.8, 12.9, 13.9, 14.7_

  - [ ]* 4.4 Write property test — Camera_Manager concurrency invariants (Property 6)
    - **Property 6: Camera_Manager concurrency invariants hold for any operation sequence**
    - **Validates: Requirements 12.1, 12.3, 12.4, 12.5, 12.9, 13.2, 13.9, 16.4**
    - Inject a stub processor (no real OpenCV/RTSP); generate random sequences of add/start/stop/error/
      remove ops; after each op assert: running count ≤ L; FIFO promotion order; distinct task_id +
      session_id per running camera; isolated error leaves siblings running; detection attribution correct

  - [ ]* 4.5 Write property test — concurrency-limit validation (Property 11)
    - **Property 11: Concurrency-limit validation**
    - **Validates: Requirements 12.2, 12.8**
    - For random integers, assert `set_concurrency_limit` accepts 1..64, and that a rejected value
      leaves the previously applied limit unchanged

  - [ ]* 4.6 Write property test — duplicate camera-name detection (Property 9)
    - **Property 9: Duplicate camera-name detection is case-insensitive and whitespace-trimmed**
    - **Validates: Requirements 11.6**
    - Generate random name pairs; assert the duplicate check returns true iff names are equal after
      `.strip().casefold()` comparison

- [x] 5. Backend: integration smoke tests
  - [x] 5.1 Write integration tests for all existing and new endpoints
    - Use FastAPI `TestClient`; send one valid request to `/api/health`, `/api/stats`, `/api/detections`,
      `/api/detections/timeline`, `/api/detections/letters`, `/api/detections/sources`,
      `/api/detections/confidence`, `/api/sessions`, `/api/plate/metadata`
    - Assert each returns a non-error response with the documented data fields
    - Add 1–3 example-based tests for plate metadata: one Persian-encoded plate, one latin-encoded plate
      with the same plate (assert identical metadata), and one free-zone plate (assert special_note)
    - _Requirements: 16.1, 14.5, 14.7, 14.8_

- [~] 6. Checkpoint — backend complete
  - Ensure all `pytest` tests pass. Confirm `api.py` starts without errors. Ask the user if any backend
    behavior needs adjustment before moving to the Flutter client.

- [x] 7. Flutter project setup and app shell
  - [x] 7.1 Create Flutter project targeting Windows and Web; add all dependencies to `pubspec.yaml`
    - Run `flutter create` with `--platforms=windows,web`; add `flutter_riverpod`, `go_router`, `dio`,
      `fl_chart`, `media_kit`, `media_kit_video`, `file_picker`, `glados` (dev), and `vazirmatn` font
    - Bundle the Vazirmatn font in `pubspec.yaml` and configure it as the app font
    - Create the directory structure from the design: `lib/app/`, `lib/core/`, `lib/data/`, `lib/features/`,
      `lib/shared/`
    - _Requirements: 1.1, 15.7_

  - [x] 7.2 Implement `RuntimeConfig`, `api_client.dart`, and `theme.dart`
    - In `config.dart`: read `BACKEND_URL` from `--dart-define`; on Web also check `window`-injected value
      / `config.json`; validate it is a non-empty absolute http(s) URL; expose `isValid` flag
    - In `api_client.dart`: create `dio` instance with base URL from `RuntimeConfig`; set per-request
      timeouts (5s health, 10s views, 60s image upload); add central error-mapping interceptor that
      produces typed `ApiFailure(status, message)` values
    - In `theme.dart`: configure `MaterialApp` theme and `Directionality` for RTL Persian text
    - _Requirements: 1.5, 1.8, 2.1_

  - [x] 7.3 Implement `app.dart`, `router.dart`, and the navigation shell
    - Define `go_router` routes for `/dashboard`, `/history`, `/analytics`, `/sessions`, `/detection`,
      `/cameras`; set `/dashboard` as the initial route
    - Build a `ScaffoldWithNavigation` shell widget using `NavigationRail` for wide screens and
      `NavigationBar`/drawer for narrow screens
    - Wrap each route's content in an error-boundary widget that retains the previous route on render
      failure and shows an error indicator
    - _Requirements: 1.2, 1.3, 1.4, 1.6, 1.9_

  - [x] 7.4 Implement `HealthController` and connectivity badge widget
    - Create a Riverpod `AsyncNotifier` that calls `GET /api/health` on startup with a 5s timeout;
      transitions to connected/disconnected state based on `status == "ok"`
    - Implement the 30s periodic re-poll while disconnected; implement retry-on-demand
    - Display a persistent connectivity badge in the navigation shell; show configuration-error indicator
      when `RuntimeConfig.isValid` is false and suppress all backend calls
    - _Requirements: 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 8. Flutter: data models and repositories
  - [x] 8.1 Define all Dart data models in `lib/data/models/`
    - Create `StatsModel`, `DetectionModel`, `SessionModel`, `VideoTaskStatusModel`, `RTSPTaskStatusModel`,
      `CameraModel`, `StartResultModel`, `PlateMetadataModel`, `ConcurrencyConfigModel` as Dart classes
      with `fromJson` factories mirroring the API contracts from the design
    - _Requirements: 3.1, 4.1, 6.1, 7.2, 10.3, 11.7, 14.1_

  - [x] 8.2 Implement repositories in `lib/data/repositories/`
    - Implement `StatsRepo`, `DetectionsRepo`, `SessionsRepo` against the existing read-only endpoints
    - Implement `DetectRepo` with `detectImage`, `startVideoTask`, `pollVideoTask`, `stopVideoTask`,
      `startRtsp`, `pollRtsp`, `stopRtsp` methods
    - Implement `CameraRepo` with full CRUD + start/stop/start-all/stop-all + concurrency config methods
    - Implement `PlateMetaRepo` with `getMetadata(plate)` against `/api/plate/metadata`
    - _Requirements: 3.1, 4.1, 5.1, 6.1, 7.1, 8.1, 10.1, 11.1, 14.7_

- [x] 9. Flutter: Dashboard, History, Analytics, Sessions views
  - [x] 9.1 Implement Dashboard view
    - Use `FutureProvider` for parallel requests to `/api/stats`, four chart endpoints, and
      `/api/detections?limit=10`; render stats summary, four `fl_chart` charts, and recent-detections list
    - Show per-request loading indicators; render error+retry per failing data source without blocking
      sibling charts; format `avg_confidence` as `"N.N%"` or placeholder when null
    - Apply 10s timeout to each request via the dio interceptor
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 9.2 Implement History view
    - Request `/api/detections?limit=50&offset=0`; display `timestamp`, `plate_persian`, `source_type`,
      `confidence`, and `source_file` for each record
    - Wire source-type filter dropdown (resets offset), debounced search field (300 ms, resets offset),
      and next/prev pagination controls (`offset` steps, `limit` clamped 1–1000, hidden when `total ≤ limit`)
    - Show empty-state message when `data` is empty; retain previous results + error banner on failure
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 9.3 Implement Analytics view
    - Load timeline (default `days=7`), sources, confidence, letters endpoints; render each as
      an `fl_chart` chart; provide 7/14/30/90-day selector that re-requests only the timeline endpoint
    - Sort letter-frequency entries by descending count then ascending letter before rendering the chart
    - Show per-chart empty-state and per-chart error indicators; failed charts do not block siblings
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 9.4 Implement Sessions view
    - Request `/api/sessions?limit=20`; display start time, source type, status, total plates, duration
    - Compute duration as `(endAt - startAt).inSeconds` when both are present (non-negative); show
      running-duration indicator when `ended_at` is null
    - Style `running`/`done`/`error` status values distinctly; refresh control re-requests the list;
      error -> error indicator + retry + retain previous list
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 9.5 Write property tests for client-side pure formatting functions (Properties 12, 13, 14)
    - **Property 12: Letter-frequency ordering**
    - **Property 13: Session duration is a non-negative integer number of seconds**
    - **Property 14: Percentage formatting to one decimal place**
    - **Validates: Requirements 3.5, 3.6, 5.4, 6.3, 7.2**
    - Use `glados`; generate random letter-frequency lists (assert sort order), session time pairs (assert
      non-negative integer seconds), and confidence values incl. null (assert formatting)

- [x] 10. Flutter: shared playback abstraction
  - [x] 10.1 Implement `lib/shared/playback/` platform-abstracted video player
    - Create `PlaybackController` wrapping `media_kit` with a `play(source)` method that accepts a local
      file path (Windows) or object URL/bytes (Web) and always sets playback rate to 1.0×
    - Expose a `VideoWidget` that renders the `media_kit_video` player; ensure rate is never modified by
      polling state or `skip_frames` changes
    - Document `video_player` as the fallback in a code comment
    - _Requirements: 8.3, 10.7_

  - [ ]* 10.2 Write property test — playback rate invariant to sampling interval (Property 5)
    - **Property 5: Playback rate is invariant to the sampling interval**
    - **Validates: Requirements 8.3, 10.7**
    - Use `glados`; for random N in 1..1000, instantiate `PlaybackController` with `skip_frames=N` and
      assert `controller.playbackRate == 1.0`

- [x] 11. Flutter: Image Detection and Plate Details Panel
  - [x] 11.1 Implement Image Detection sub-view in `lib/features/detection/`
    - Use `file_picker` with JPEG/PNG/BMP filter; validate file ≤ 10 MB client-side and show
      file-validation message if exceeded
    - POST via `DetectRepo.detectImage`; show processing indicator + disable submit while in flight;
      retain previous results during request; 60s timeout via dio → clear indicator + re-enable + timeout
      message
    - Render annotated base64 image and plate list with confidence as `"N.N%"`; show no-plate message
      when list is empty; show error with status on failure
    - Each plate row is tappable and opens the plate details panel
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10_

  - [x] 11.2 Implement Plate Details Panel in `lib/features/plate_details/`
    - Accept a `plate_dtrb` or `plate_persian` string; call `PlateMetaRepo.getMetadata`; show loading
      indicator while in flight; 10s timeout → stop loader + error message + retry
    - Render `Plate_Category`, `Color_Scheme` as text plus a filled color swatch widget (one of white,
      yellow, green, red, blue, black), `region_name`, `special_note`, and `plate_persian` RTL text
    - Show not-classified state with reason when `classified == false`
    - Apply `Directionality.rtl` to Persian text rendering
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7_

- [x] 12. Flutter: Video Detection with polling and smooth playback
  - [x] 12.1 Implement `VideoTaskController` Riverpod `AsyncNotifier`
    - On submit: validate `skip_frames` is an integer 1–1000 (default 30); POST via `DetectRepo.startVideoTask`
    - Poll `/api/detect/video/{task_id}` every 1000 ms while status ∈ {queued, opening, processing}
    - Compute progress as `(frame_idx / total_frames * 100).round()` when `total_frames > 0`, else
      indeterminate; expose plate log, error detail, output path
    - On `done` expose output via `/media/{output_path}`; on `error` show detail and partial output if
      present (retain until success); on `cancelled` stop polling + cancelled state
    - Stop control calls `/stop` endpoint
    - _Requirements: 8.1, 8.2, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12_

  - [x] 12.2 Implement Video Detection sub-view wiring playback + polling
    - After POST returns `task_id`, call `PlaybackController.play` on the locally-picked file
    - Render `VideoWidget` for local playback (rate 1.0× always); render progress indicator, running
      plate log, and terminal state widgets alongside; polling and playback advance independently
    - _Requirements: 8.3, 9.2, 9.3_

  - [ ]* 12.3 Write property test — video progress percentage computation (Property 15)
    - **Property 15: Video progress percentage computation**
    - **Validates: Requirements 8.2, 8.11**
    - Use `glados`; for random `frame_idx` and `total_frames > 0`, assert displayed progress equals
      `(frame_idx / total_frames * 100).round()`; for `total_frames == 0` assert indeterminate

- [x] 13. Flutter: Single RTSP Detection
  - [x] 13.1 Implement Single RTSP sub-view and `RTSPPollController`
    - Validate URL is non-empty and starts with `rtsp://`; validate `skip_frames` 1–1000 (default 15);
      POST via `DetectRepo.startRtsp`; retain `task_id`
    - Poll `/api/detect/rtsp/{task_id}` every 1000 ms while status ∈ {initialized, connecting, connected,
      streaming}; render annotated base64 frame (retain last / show waiting placeholder when none),
      live detection lines, and plate history
    - On status beginning with `error` stop polling within one cycle and display the error
    - Stop control calls `stopRtsp`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 9.4_

  - [ ]* 13.2 Write property test — RTSP URL validation (Property 8)
    - **Property 8: RTSP URL validation**
    - **Validates: Requirements 10.2**
    - Use `glados`; generate arbitrary strings; assert the validator returns true iff the string is
      non-empty and starts with `"rtsp://"`

  - [ ]* 13.3 Write property test — sampling-interval client validation (Property 7 — client side)
    - **Property 7 (client): Sampling-interval client validation**
    - **Validates: Requirements 9.2**
    - Use `glados`; for random integers, assert the client validator accepts values in 1..1000 and
      rejects all others

- [x] 14. Flutter: Multi-Camera Management and Grid
  - [x] 14.1 Implement Camera Management view (`lib/features/cameras/`)
    - Camera list displaying name, status badge (stopped/connecting/connected/error), and `skip_frames`
    - Add-camera form: name 0–100 chars, RTSP URL, optional `skip_frames`; call `CameraRepo.createCamera`
    - Block start when camera name has no non-whitespace chars, showing name-required message
    - Rename via PUT; reflect new name in all views immediately; client-side duplicate-name rejection
      (case-insensitive, whitespace-trimmed) with duplicate-name message
    - Remove calls `CameraRepo.deleteCamera`; concurrency-limit input validates 1–64 and sends
      `PUT /api/config/concurrency`
    - _Requirements: 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 12.2, 12.8_

  - [x] 14.2 Implement `CameraPollController` and per-camera live panel
    - Each running camera gets an independent Riverpod `AsyncNotifier` polling
      `/api/detect/rtsp/{task_id}` at exactly 1000 ms
    - Panel renders camera name, annotated base64 frame (frame-unavailable placeholder when
      missing/undecodable), and live detection lines; on `done`/`error` stop polling and retain last frame
    - Tapping a panel opens the enlarged single-camera view (enlarged frame + full plate history; if
      history fails to load show history-unavailable message and retain live view)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 14.3 Implement responsive multi-camera `GridView` and start/stop-all controls
    - Use `LayoutBuilder` to determine column count; render every running camera in a scrollable `GridView`
      up to the concurrency limit without overlap; queued cameras show a queued badge
    - Start-all and stop-all buttons call `CameraRepo.startAll` / `CameraRepo.stopAll`
    - _Requirements: 12.1, 12.3, 12.6, 13.8_

  - [ ]* 14.4 Write property test — duplicate camera-name validation (client, Property 9 — client side)
    - **Property 9 (client): Duplicate camera-name detection is case-insensitive and whitespace-trimmed**
    - **Validates: Requirements 11.6**
    - Generate random name pairs and assert the client-side duplicate check returns the same result as
      `nameA.trim().toLowerCase() == nameB.trim().toLowerCase()`

  - [ ]* 14.5 Write property test — concurrency-limit client validation (Property 11 — client side)
    - **Property 11 (client): Concurrency-limit validation**
    - **Validates: Requirements 12.2, 12.8**
    - For random integers, assert the client-side validator accepts 1..64 and rejects all others

- [x] 15. Integration wiring and final checkout
  - [x] 15.1 Wire Detection view tabs (Image / Video / RTSP) into `go_router`
    - Create a `DetectionView` with tab/segment switcher routing to the image, video, and RTSP sub-views
    - Ensure `skip_frames` defaults of 30 (video) and 15 (RTSP) are applied when the user leaves the
      field empty; connect plate-row taps to the plate details panel
    - _Requirements: 8.1, 9.3, 9.4, 7.10_

  - [x] 15.2 Verify build targets and run full test suite
    - Run `flutter build windows` and `flutter build web` from the Flutter project root; fix any
      compilation errors
    - Run `pytest` in the repo root; fix any failing Python tests
    - Run `flutter test` in the Flutter project; fix any failing Dart tests
    - _Requirements: 1.1, 16.1_

- [x] 16. Final checkpoint — ensure all tests pass
  - Run `pytest` and `flutter test`; confirm both build targets compile cleanly. Ask the user if any
    functionality needs adjustment before the feature is considered complete.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core functionality is fully
  covered by the non-optional tasks.
- Each task references specific requirements for full traceability.
- Backend tasks (1–5) are entirely independent of Flutter tasks (7–14) and can be developed in parallel.
- Property tests are placed close to the implementation task they validate to catch regressions early.
- `glados` is the idiomatic Dart PBT library; use `@Arbitrary` generators for domain types.
- `Hypothesis` is used for all Python PBT; annotate every test with the property number comment.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "7.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "3.1", "7.2", "7.3"] },
    { "id": 2, "tasks": ["1.3", "2.2", "3.2", "4.1", "7.4", "8.1"] },
    { "id": 3, "tasks": ["2.3", "2.4", "2.5", "3.3", "3.4", "4.2", "8.2"] },
    { "id": 4, "tasks": ["4.3", "4.6", "9.1", "9.2", "9.3", "9.4", "10.1"] },
    { "id": 5, "tasks": ["4.4", "4.5", "5.1", "9.5", "10.2", "11.1"] },
    { "id": 6, "tasks": ["11.2", "12.1", "13.1"] },
    { "id": 7, "tasks": ["12.2", "12.3", "13.2", "13.3", "14.1"] },
    { "id": 8, "tasks": ["14.2", "14.3", "15.1"] },
    { "id": 9, "tasks": ["14.4", "14.5", "15.2"] }
  ]
}
```
