import os

# Force FFmpeg to use TCP transport with minimal buffering for RTSP. This is
# read by OpenCV's FFmpeg backend the first time a VideoCapture is opened, so
# it must be set BEFORE cv2 imports (FFmpeg is loaded lazily on first capture).
# Without this the FFmpeg internal buffer adds 1-3s of latency to live streams
# regardless of CAP_PROP_BUFFERSIZE.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0"
    "|reorder_queue_size;0|stimeout;5000000"
    "|analyzeduration;500000|probesize;500000",
)

import cv2
import numpy as np
import threading
import time
import logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

from plate_validator import validate_iranian_plate, format_plate_persian as validator_format_persian
from error_handler import (
    report_error, report_exception, report_stream_error, report_detection_error,
    report_db_error, ErrorCategory, ErrorSeverity,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = "io/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

FONT_PATH = "C:/Windows/Fonts/arial.ttf"
FONT_PATH_ALT = "C:/Windows/Fonts/tahoma.ttf"

DTRB_TO_PERSIAN = {
    'a': 'ا', 'b': 'ب', 'c': 'چ', 'd': 'د', 'e': 'ه',
    'f': 'ف', 'g': 'گ', 'h': 'ح', 'i': 'ی', 'j': 'ج',
    'k': 'ک', 'l': 'ل', 'm': 'م', 'n': 'ن', 'o': 'و',
    'p': 'پ', 'q': 'ق', 'r': 'ر', 's': 'س', 't': 'ت',
    'u': 'و', 'v': 'و', 'w': 'و', 'x': 'خ', 'y': 'ی',
    'z': 'ز',
}


def should_sample(frame_index: int, skip_frames: int) -> bool:
    """Return True if this frame index should be submitted for plate recognition.

    Every frame whose zero-based index is a multiple of skip_frames is sampled.
    This pure function is extracted so it can be property-tested independently.
    Requirements: 8.5, 16.5
    """
    return frame_index % skip_frames == 0


def dtrb_to_persian(text):
    result = []
    for ch in text:
        if ch.isdigit():
            result.append(ch)
        elif ch in DTRB_TO_PERSIAN:
            result.append(DTRB_TO_PERSIAN[ch])
        else:
            result.append(ch)
    return "".join(result)


def format_plate_persian(text):
    persian_text = dtrb_to_persian(text)
    if len(persian_text) >= 8:
        return persian_text[:2] + " " + persian_text[2] + " " + persian_text[3:6] + "-" + persian_text[6:8]
    return persian_text


def get_persian_font(size=24):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except:
        try:
            return ImageFont.truetype(FONT_PATH_ALT, size)
        except:
            return ImageFont.load_default()


def group_detections(detections, y_iou_thresh=0.3):
    if not detections:
        return []
    sorted_dets = sorted(detections, key=lambda d: d["bbox"][1])
    groups = [[sorted_dets[0]]]
    for det in sorted_dets[1:]:
        _, y1, _, y2 = det["bbox"]
        _, gy1, _, gy2 = groups[-1][0]["bbox"]
        intersection = min(y2, gy2) - max(y1, gy1)
        union = max(y2, gy2) - min(y1, gy1)
        if union > 0 and intersection / union > y_iou_thresh:
            groups[-1].append(det)
        else:
            groups.append([det])
    result = []
    for g in groups:
        g.sort(key=lambda d: d["bbox"][0])
        plate_chars = "".join(d["char"] for d in g)
        x1 = min(d["bbox"][0] for d in g)
        y1 = min(d["bbox"][1] for d in g)
        x2 = max(d["bbox"][2] for d in g)
        y2 = max(d["bbox"][3] for d in g)
        avg_conf = np.mean([d["confidence"] for d in g])
        result.append({
            "bbox": (x1, y1, x2, y2),
            "plate_text": plate_chars,
            "confidence": float(avg_conf),
            "chars": g,
        })
    result.sort(key=lambda r: r["bbox"][1])
    return result


def draw_plate_overlay_fast(image_np, plates, dtrb_results):
    """Lightweight overlay using pure OpenCV — no PIL, no RGBA compositing.

    Used for non-sampled RTSP frames where speed matters more than fancy text
    rendering. Draws green bounding boxes and ASCII-safe plate text with cv2.
    This is ~10-20x faster than draw_plate_template() because it avoids:
    - BGR→RGB→RGBA→composite→RGB→BGR conversion chain
    - PIL Image object allocation per frame
    - TrueType font rendering via Pillow
    """
    frame = image_np.copy()
    h, w = frame.shape[:2]

    for idx, plate in enumerate(plates):
        x1, y1, x2, y2 = plate["bbox"]
        confidence = plate["confidence"]

        pad = 6
        bx1 = max(0, x1 - pad)
        by1 = max(0, y1 - pad)
        bx2 = min(w, x2 + pad)
        by2 = min(h, y2 + pad)

        # Green bounding box
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), (0, 200, 50), 2)

        # Draw car bounding box (blue)
        car_bbox = plate.get("car_bbox")
        if car_bbox is not None:
            cx1, cy1, cx2, cy2 = car_bbox
            cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), (50, 100, 255), 2)

        # Confidence + raw plate text (ASCII) above the box
        dtrb_text = dtrb_results[idx] if idx < len(dtrb_results) else "?"
        label = f"{dtrb_text} ({confidence:.0%})"
        font_scale = 0.55
        thickness = 1
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)

        # Dark label background — only blend the small ROI, not the full frame
        label_y = max(0, by1 - th - 10)
        lbl_x2 = min(w, bx1 + tw + 10)
        lbl_y2 = min(h, label_y + th + 8)
        roi = frame[label_y:lbl_y2, bx1:lbl_x2]
        if roi.size > 0:
            cv2.rectangle(frame, (bx1, label_y), (lbl_x2, lbl_y2), (0, 0, 0), -1)
            # Partial transparency via weighted blend on small region
            dark_roi = frame[label_y:lbl_y2, bx1:lbl_x2]
            blended = cv2.addWeighted(roi, 0.3, dark_roi, 0.7, 0)
            frame[label_y:lbl_y2, bx1:lbl_x2] = blended

        cv2.putText(frame, label, (bx1 + 4, label_y + th + 3),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 100), thickness, cv2.LINE_AA)

    return frame


def draw_plate_template(image_np, plates, dtrb_results):
    """Full-quality overlay using PIL for Persian text rendering.

    Used for sampled frames (ML detection frames) and video output where
    visual quality matters. Slower due to PIL/RGBA compositing.
    """
    img_rgb = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).convert("RGBA")
    draw = ImageDraw.Draw(pil_img)

    h, w = image_np.shape[:2]

    for idx, plate in enumerate(plates):
        x1, y1, x2, y2 = plate["bbox"]
        dtrb_text = dtrb_results[idx] if idx < len(dtrb_results) else "?"
        persian_plate = format_plate_persian(dtrb_text)
        confidence = plate["confidence"]

        pad = 8
        bx1 = max(0, x1 - pad)
        by1 = max(0, y1 - pad)
        bx2 = min(w, x2 + pad)
        by2 = min(h, y2 + pad)

        odraw = ImageDraw.Draw(pil_img)
        odraw.rectangle([bx1, by1, bx2, by2], outline=(0, 200, 50), width=3)

        for ch in plate.get("chars", []):
            cx1, cy1, cx2, cy2 = ch["bbox"]
            odraw.rectangle([cx1, cy1, cx2, cy2], outline=(50, 255, 100), width=2)

        # Draw car bounding box (blue)
        car_bbox = plate.get("car_bbox")
        if car_bbox is not None:
            cx1, cy1, cx2, cy2 = car_bbox
            odraw.rectangle([cx1, cy1, cx2, cy2], outline=(50, 100, 255), width=3)

        label_font = get_persian_font(28)
        conf_font = get_persian_font(16)

        label_bbox = draw.textbbox((0, 0), persian_plate, font=label_font)
        label_w = label_bbox[2] - label_bbox[0]
        label_h = label_bbox[3] - label_bbox[1]

        conf_text = f"{confidence:.2%}"
        conf_bbox = draw.textbbox((0, 0), conf_text, font=conf_font)
        conf_w = conf_bbox[2] - conf_bbox[0]
        conf_h = conf_bbox[3] - conf_bbox[1]

        # Car info line
        car_parts = []
        if plate.get("car_color"):
            car_parts.append(plate["car_color"])
        if plate.get("car_type"):
            car_parts.append(plate["car_type"])
        if plate.get("city"):
            car_parts.append(plate["city"])
        car_info = " | ".join(car_parts) if car_parts else ""
        car_h = 0
        if car_info:
            car_bbox_t = draw.textbbox((0, 0), car_info, font=conf_font)
            car_h = car_bbox_t[3] - car_bbox_t[1]

        panel_w = label_w + 30
        panel_h = label_h + conf_h + car_h + 30
        panel_x = min(bx1, w - panel_w - 10)
        panel_y = max(0, by1 - panel_h - 10)

        panel = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
        pdraw = ImageDraw.Draw(panel)
        pdraw.rectangle(
            [panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
            fill=(0, 0, 0, 180),
        )
        pil_img = Image.alpha_composite(pil_img, panel)
        draw = ImageDraw.Draw(pil_img)

        draw.text(
            (panel_x + 15, panel_y + 8),
            persian_plate,
            font=label_font, fill=(0, 255, 100),
        )
        draw.text(
            (panel_x + 15, panel_y + label_h + 12),
            conf_text,
            font=conf_font, fill=(200, 200, 200),
        )
        if car_info:
            draw.text(
                (panel_x + 15, panel_y + label_h + conf_h + 18),
                car_info,
                font=conf_font, fill=(100, 180, 255),
            )

    result = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    return result


def detect_plates(image, engine, fast_mode=False):
    """Run ALPR pipeline WITHOUT drawing overlays.

    Returns (image_copy, plates, alpr_results) so callers can validate/filter
    plates before deciding which boxes to draw.

    Each plate dict contains: bbox, confidence, plate_text, chars,
    car_bbox, car_color, car_type, city.
    """
    image = image.copy()
    if engine is None:
        return image, [], []

    try:
        results = engine.run(image)
    except Exception as exc:
        logger.error("ALPR pipeline failed: %s", exc)
        return image, [], []

    plates = []
    alpr_results = []
    for r in results:
        plates.append({
            "bbox": r.plate_bbox,
            "plate_text": r.plate_text,
            "confidence": r.confidence,
            "chars": [{"bbox": b, "char": ""} for b in r.char_bboxes],
            "car_bbox": r.car_bbox,
            "car_color": r.car_color,
            "car_type": r.car_type,
            "city": r.city,
        })
        alpr_results.append(r)

    return image, plates, alpr_results


def best_plate_text(dtrb_text: str, dtrb_conf: float, yolo_text: str, yolo_conf: float) -> tuple[str, float]:
    """Choose the best plate text between DTRB and YOLO readings.

    Strategy: Try DTRB first (usually more accurate for standard plates).
    If DTRB text fails validation, fall back to YOLO char-by-char text.
    This is critical for Free Zone plates where DTRB may produce wrong-length
    output but YOLO character detection is correct.

    Returns (best_text, best_confidence).
    """
    from plate_validator import validate_iranian_plate

    # Try DTRB text first
    dtrb_validation = validate_iranian_plate(dtrb_text, dtrb_conf)
    if dtrb_validation.is_valid:
        return dtrb_text, max(dtrb_conf, yolo_conf)

    # DTRB failed — try YOLO text as fallback
    if yolo_text and yolo_text != dtrb_text:
        yolo_validation = validate_iranian_plate(yolo_text, yolo_conf)
        if yolo_validation.is_valid:
            return yolo_text, yolo_conf

    # Neither passed — return DTRB text (caller will reject it via validation)
    return dtrb_text, max(dtrb_conf, yolo_conf)


def process_frame(image, engine, fast_mode=False):
    """Detect plates and draw overlays for ALL detections.

    Kept for the image endpoint. Real-time video/RTSP paths use detect_plates +
    explicit validation so only valid Iranian plates get drawn.
    """
    img, plates, alpr_results = detect_plates(image, engine, fast_mode)
    texts = [r.plate_text for r in alpr_results]
    annotated = draw_plate_template(img, plates, texts)
    return annotated, plates, alpr_results


class VideoProcessor:
    # Same-plate cooldown: a plate emitted within this many seconds is treated
    # as the same observation and is not re-emitted (no DB save, no alert, no
    # new live-feed line, no history-count bump). 60s gives a clean per-visit
    # record without spamming the same car/screen multiple times in 3 seconds.
    _DEDUP_WINDOW_SECONDS = 60.0

    def __init__(self, engine, on_detection=None):
        self.engine = engine
        self.on_detection = on_detection
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.running = False
            self.processing = False
            self.current_frame = None
            self.frame_idx = 0
            self.total_frames = 0
            self.output_path = None
            self.plate_log = []
            self.live_detections = []
            self.status = "idle"
            self.error = None
            self.last_overlay = None
            # plate_text -> last emission monotonic timestamp; consulted before
            # any DB save / live-feed line so the same plate doesn't get
            # recorded multiple times within _DEDUP_WINDOW_SECONDS.
            self._recent_emit_times = {}

    def process_video(self, input_path, skip_frames=30, fast_mode=False):
        self.stop()
        self.reset()
        self.thread = threading.Thread(
            target=self._run,
            args=(input_path, skip_frames, fast_mode),
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False
        if hasattr(self, 'thread') and self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)

    def _run(self, input_path, skip_frames, fast_mode):
        with self.lock:
            self.status = "opening"
            self.running = True
            self.processing = True

        try:
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                raise ValueError(f"Cannot open video: {input_path}")

            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if fps <= 0:
                fps = 30

            output_fps = fps  # Full frame rate for smooth playback
            output_name = f"processed_{os.path.basename(input_path)}"
            output_path = os.path.join(OUTPUT_DIR, output_name)

            fourcc = cv2.VideoWriter_fourcc(*"avc1")
            writer = cv2.VideoWriter(
                output_path, fourcc, max(output_fps, 1), (width, height)
            )
            if not writer.isOpened():
                print("[Warning] avc1 not available, falling back to mp4v (may not play in browser)")
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(
                    output_path, fourcc, max(output_fps, 1), (width, height)
                )

            with self.lock:
                self.total_frames = total
                self.status = "processing"

            plate_log = []
            frame_idx = 0

            while self.running:
                ret, frame = cap.read()
                if not ret:
                    break

                # Detect on every frame so the overlay box stays *on* the plate
                # in the output video. The dedup gate below throttles DB writes
                # and the live-feed strip so the same plate isn't recorded
                # multiple times per second.
                img_copy, plates, alpr_results = detect_plates(
                    frame, self.engine, fast_mode,
                )

                live_lines = []
                valid_plates = []
                valid_dtrb = []
                for idx, plate in enumerate(plates):
                    dtrb_text = plate["plate_text"]
                    dtrb_conf = plate["confidence"]
                    px1, py1, px2, py2 = plate["bbox"]

                    best_conf = dtrb_conf

                    # Try DTRB text first, fall back to YOLO text for Free Zone plates
                    dtrb_text, best_conf = best_plate_text(
                        dtrb_text, dtrb_conf,
                        plate["plate_text"], plate["confidence"]
                    )

                    # Validate against Iranian plate format
                    validation = validate_iranian_plate(dtrb_text, best_conf)

                    # Skip everything that is not a valid Iranian plate:
                    # no log entry, no box drawn, no DB save.
                    if not validation.is_valid:
                        continue

                    # Always draw the box on the current detection (keeps the
                    # overlay locked to the plate even when it is moving).
                    valid_plates.append(plate)
                    valid_dtrb.append(dtrb_text)

                    # Same-plate cooldown: if this exact plate was emitted
                    # within the dedup window, skip the DB save / live-feed
                    # line / plate_log entry. The box still gets drawn above.
                    now_ts = time.time()
                    last_ts = self._recent_emit_times.get(dtrb_text, 0.0)
                    if now_ts - last_ts < self._DEDUP_WINDOW_SECONDS:
                        continue
                    self._recent_emit_times[dtrb_text] = now_ts

                    persian_display = validator_format_persian(dtrb_text)

                    md = validation.metadata
                    metadata_dict = {
                        "classified": md.classified,
                        "category": md.category,
                        "category_display": md.category_display,
                        "color_scheme": md.color_scheme,
                        "region_code": md.region_code,
                        "region_name": md.region_name,
                        "special_note": md.special_note,
                    } if md is not None else None

                    # Normalized car bbox (0-1)
                    car_bbox_norm = None
                    raw_car = plate.get("car_bbox")
                    if raw_car is not None:
                        car_bbox_norm = [
                            round(float(raw_car[0]) / width, 4),
                            round(float(raw_car[1]) / height, 4),
                            round(float(raw_car[2]) / width, 4),
                            round(float(raw_car[3]) / height, 4),
                        ]

                    plate_log.append({
                        "frame": frame_idx,
                        "time": f"{frame_idx / fps:.2f}s",
                        "time_sec": round(frame_idx / fps, 3),
                        "plate_text": plate["plate_text"],
                        "dtrb_text": dtrb_text,
                        "confidence": best_conf,
                        # Normalized bbox (0-1) so the client can scale to any size
                        "bbox": [
                            round(float(px1) / width, 4),
                            round(float(py1) / height, 4),
                            round(float(px2) / width, 4),
                            round(float(py2) / height, 4),
                        ],
                        "persian_display": persian_display,
                        "is_valid_iranian": True,
                        "metadata": metadata_dict,
                        "car_color": plate.get("car_color"),
                        "car_type": plate.get("car_type"),
                        "city": plate.get("city"),
                        "car_bbox": car_bbox_norm,
                    })

                    live_lines.append(
                        f"Frame {frame_idx:>6d}  |  {persian_display:16s}  |  "
                        f"conf: {plate['confidence']:.4f}  |  "
                        f"@ {frame_idx / fps:.2f}s"
                    )

                    # IMMEDIATE save for valid plates only
                    if self.on_detection:
                        try:
                            self.on_detection("video", dtrb_text, best_conf, input_path, frame_idx, f"{frame_idx / fps:.2f}s")
                        except Exception as e:
                            logger.error(f"DB write failed for plate '{dtrb_text}' at frame {frame_idx}: {e}")

                # Draw overlay boxes only for valid Iranian plates (always
                # current-frame positions, never stale).
                annotated = draw_plate_template(img_copy, valid_plates, valid_dtrb)
                writer.write(annotated)

                with self.lock:
                    self.current_frame = annotated
                    self.frame_idx = frame_idx
                    self.plate_log = plate_log
                    self.live_detections.extend(live_lines)
                    if len(self.live_detections) > 500:
                        self.live_detections = self.live_detections[-500:]

                frame_idx += 1

            cap.release()
            writer.release()

            with self.lock:
                self.output_path = output_path
                self.plate_log = plate_log
                self.status = "done"
                self.processing = False
                self.running = False

        except Exception as e:
            import traceback
            traceback.print_exc()
            report_exception(e, ErrorCategory.STREAM, source="VideoProcessor._run",
                             user_key="video_open_failed")
            with self.lock:
                self.error = str(e)
                self.status = "error"
                self.processing = False
                self.running = False

    def stop(self):
        with self.lock:
            self.running = False

    def get_state(self):
        with self.lock:
            result = {
                "running": self.running,
                "processing": self.processing,
                "frame_idx": self.frame_idx,
                "total_frames": self.total_frames,
                "output_path": self.output_path,
                "plate_log": list(self.plate_log),
                "live_detections": list(self.live_detections),
                "status": self.status,
                "error": self.error,
            }
            if self.current_frame is not None:
                result["current_frame"] = self.current_frame.copy()
            else:
                result["current_frame"] = None
            return result


class RTSPStreamProcessor:
    # Same-plate cooldown: a plate emitted within this many seconds is treated
    # as the same observation and is not re-emitted (no DB save, no alert,
    # no new live-feed line, no history-count bump). Box overlay still draws
    # on every detection so the visual stays locked to the plate.
    _DEDUP_WINDOW_SECONDS = 60.0

    def __init__(self, engine, source,
                 fast_mode=False, skip_frames=15, on_detection=None,
                 max_reconnect_attempts=3, reconnect_delay=2.0):
        self.engine = engine
        self.source = source
        self.fast_mode = fast_mode
        self.skip_frames = skip_frames
        self.on_detection = on_detection
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay

        self.cap = None
        self.running = False
        self.frame_count = 0
        self.latest_frame = None
        self.latest_annotated = None
        self.latest_jpeg = None  # Pre-encoded JPEG bytes for fast serving
        self.plate_history = []
        self.live_detections = []
        # plate_text -> last emission monotonic timestamp (see _DEDUP_WINDOW_SECONDS)
        self._recent_emit_times = {}
        self.status = "initialized"
        self.lock = threading.Lock()
        self.thread = None
        self._error_message = None  # Latest error for UI display

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        # Signal both the main processing loop and the reader thread to exit.
        # IMPORTANT: do NOT call cap.release() here. The reader thread owns the
        # capture and releases it when it exits; releasing it from another
        # thread while a cap.read() is in flight throws a native OpenCV C++
        # exception that aborts the whole process on Windows.
        self.running = False
        if hasattr(self, 'thread') and self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)

    def _run(self):
        from plate_validator import validate_iranian_plate, format_plate_persian as _format_persian
        import time as _time

        with self.lock:
            self.status = "connecting"

        try:
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # Reduce internal decode buffer to 1 frame for lowest latency
            self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
            self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        except Exception as e:
            report_exception(e, ErrorCategory.STREAM, source="RTSPStreamProcessor", user_key="stream_connect_failed")
            with self.lock:
                self.status = f"error: connection failed - {e}"
            self.running = False
            return

        if not self.cap.isOpened():
            report_stream_error(
                f"Cannot connect to RTSP stream: {self.source}",
                source="RTSPStreamProcessor",
                user_key="stream_connect_failed",
            )
            with self.lock:
                self.status = "error: cannot connect to stream"
            self.running = False
            return

        with self.lock:
            self.status = "streaming"

        # ----- Reader thread (low-latency RTSP) ------------------------------
        # Decouples decode from ML so a slow ML pass does not let the FFmpeg
        # buffer fill with stale frames. The reader continuously reads as fast
        # as the network allows, keeping ONLY the latest frame; the main loop
        # then always processes "now", not what was queued seconds ago.
        raw_lock = threading.Lock()
        raw_holder = {"seq": 0, "frame": None}

        def _reader():
            seq = 0
            consecutive_failures = 0
            max_failures = 30  # ~1 second of failures before triggering reconnect
            try:
                while self.running:
                    try:
                        ret, frm = self.cap.read()
                    except Exception as read_exc:
                        report_exception(read_exc, ErrorCategory.STREAM,
                                         source="RTSPStreamProcessor._reader",
                                         user_key="stream_decode_error")
                        consecutive_failures += 1
                        if consecutive_failures > max_failures:
                            # Attempt reconnection within the reader thread
                            if not _reader_reconnect():
                                self.running = False
                                return
                            consecutive_failures = 0
                        _time.sleep(0.01)
                        continue
                    if not ret:
                        consecutive_failures += 1
                        if consecutive_failures > max_failures:
                            # Attempt reconnection within the reader thread
                            reconnected = _reader_reconnect()
                            if not reconnected:
                                report_stream_error(
                                    f"Stream ended and reconnection failed: {self.source}",
                                    source="RTSPStreamProcessor._reader",
                                    user_key="stream_ended",
                                )
                                with self.lock:
                                    self.status = "error: stream ended (reconnect failed)"
                                    self._error_message = "Stream disconnected and could not reconnect."
                                self.running = False
                                return
                            consecutive_failures = 0
                        else:
                            _time.sleep(0.01)
                        continue
                    consecutive_failures = 0  # Reset on successful read
                    seq += 1
                    with raw_lock:
                        raw_holder["seq"] = seq
                        raw_holder["frame"] = frm
            finally:
                # The reader is the SOLE owner of the capture handle, so it is
                # the only place cap.release() is called. This avoids the
                # concurrent read+release that crashes OpenCV natively.
                try:
                    if self.cap:
                        self.cap.release()
                except Exception:
                    pass

        def _reader_reconnect() -> bool:
            """Try to reconnect to the RTSP source (called from reader thread only).

            Since the reader thread owns self.cap, reconnection is done here
            to avoid cross-thread cap.release() crashes on Windows.
            """
            with self.lock:
                self.status = "reconnecting"

            for attempt in range(1, self.max_reconnect_attempts + 1):
                logger.warning(f"Reconnecting to {self.source} (attempt {attempt}/{self.max_reconnect_attempts})")
                report_error(
                    f"Stream reconnecting (attempt {attempt}/{self.max_reconnect_attempts}): {self.source}",
                    ErrorCategory.STREAM,
                    severity=ErrorSeverity.WARNING,
                    source="RTSPStreamProcessor._reader_reconnect",
                    user_key="stream_timeout",
                )

                _time.sleep(self.reconnect_delay * attempt)  # Exponential backoff

                try:
                    if self.cap:
                        self.cap.release()
                except Exception:
                    pass

                try:
                    self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
                    self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

                    if self.cap.isOpened():
                        ret, _ = self.cap.read()
                        if ret:
                            with self.lock:
                                self.status = "streaming"
                                self._error_message = None
                            logger.info(f"Reconnected to {self.source} on attempt {attempt}")
                            return True
                except Exception as e:
                    logger.warning(f"Reconnect attempt {attempt} failed: {e}")
                    continue

            return False

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        last_seq = 0
        _last_jpeg_time = 0.0          # Throttle JPEG encoding (~30 FPS visual)
        _plates_expire_time = 0.0      # Auto-clear stale overlays after N seconds
        _display_max_width = 960       # Resize for display if frame is wider

        # Overlay state as a single tuple for atomic read/write (GIL-safe).
        # Both threads access this reference atomically — no lock needed.
        # Format: (plates_list, dtrb_list) — always consistent pair.
        _overlay_state = ([], [])      # type: tuple[list, list]

        # ----- ML worker thread (decoupled from display) ---------------------
        # ML inference is moved to a separate thread so the display loop never
        # blocks. The display loop submits sampled frames here; the ML thread
        # processes them and updates shared overlay state when done.
        _ml_lock = threading.Lock()
        _ml_pending_frame = {"frame": None, "seq": 0}
        _ml_busy = {"value": False}

        def _ml_worker():
            """Dedicated thread for ML inference. Picks up pending frames,
            runs detect_plates(), and updates overlay state without blocking
            the display loop."""
            nonlocal _overlay_state, _plates_expire_time

            while self.running:
                # Check for pending work
                with _ml_lock:
                    frame_to_process = _ml_pending_frame["frame"]
                    _ml_pending_frame["frame"] = None
                if frame_to_process is None:
                    _time.sleep(0.005)
                    continue

                with _ml_lock:
                    _ml_busy["value"] = True

                try:
                    img_copy, plates, dtrb_results = detect_plates(
                        frame_to_process, self.engine, self.fast_mode,
                    )

                    # --- Plate validation ---
                    valid_plates = []
                    valid_dtrb = []
                    new_emissions = []

                    for idx, plate in enumerate(plates):
                        dtrb_text = plate["plate_text"]
                        dtrb_conf = plate["confidence"]
                        best_conf = dtrb_conf

                        # Try DTRB first, fall back to YOLO text for Free Zone plates
                        dtrb_text, best_conf = best_plate_text(
                            dtrb_text, dtrb_conf,
                            plate["plate_text"], plate["confidence"]
                        )

                        validation = validate_iranian_plate(dtrb_text, best_conf)

                        if not validation.is_valid:
                            continue

                        persian_display = _format_persian(dtrb_text)
                        valid_plates.append(plate)
                        valid_dtrb.append(dtrb_text)

                        # Same-plate cooldown check
                        now_ts = _time.time()
                        last_ts = self._recent_emit_times.get(dtrb_text, 0.0)
                        if now_ts - last_ts < self._DEDUP_WINDOW_SECONDS:
                            continue
                        self._recent_emit_times[dtrb_text] = now_ts
                        new_emissions.append((plate, dtrb_text, persian_display, best_conf, validation))

                    # --- Update overlay state atomically (single tuple assignment) ---
                    if valid_plates:
                        _overlay_state = (valid_plates, valid_dtrb)
                        _plates_expire_time = _time.time() + 3.0
                    else:
                        if _time.time() > _plates_expire_time:
                            _overlay_state = ([], [])

                    # --- Update shared state with lock ---
                    if new_emissions:
                        with self.lock:
                            self.status = "streaming"
                            for plate, dtrb_text, persian_display, best_conf, validation in new_emissions:
                                self._add_to_history(
                                    plate, dtrb_text, persian_display,
                                    True, validation.metadata, best_conf,
                                )
                                line = (
                                    f"[{datetime.now().strftime('%H:%M:%S')}]  "
                                    f"{persian_display:16s}  |  conf: "
                                    f"{best_conf:.4f}"
                                )
                                self.live_detections.append(line)
                                if len(self.live_detections) > 500:
                                    self.live_detections = self.live_detections[-500:]

                    # --- DB save OUTSIDE the lock ---
                    for plate, dtrb_text, persian_display, best_conf, validation in new_emissions:
                        if self.on_detection:
                            try:
                                self.on_detection(
                                    "rtsp", dtrb_text, best_conf,
                                    self.source, self.frame_count, "",
                                )
                            except Exception as db_exc:
                                report_db_error(db_exc, operation="save_detection")

                except Exception as e:
                    report_detection_error(e, source="RTSPStreamProcessor._ml_worker")

                finally:
                    with _ml_lock:
                        _ml_busy["value"] = False

        ml_thread = threading.Thread(target=_ml_worker, daemon=True)
        ml_thread.start()

        try:
            while self.running:
                # Grab the latest frame the reader has captured. If nothing new,
                # wait briefly so we don't busy-loop.
                with raw_lock:
                    cur_seq = raw_holder["seq"]
                    cur_frame = raw_holder["frame"]
                if cur_frame is None or cur_seq == last_seq:
                    _time.sleep(0.005)
                    continue
                last_seq = cur_seq
                self.frame_count = cur_seq
                frame = cur_frame

                # Submit sampled frames to ML thread (non-blocking).
                # Always overwrite pending frame so ML always gets the LATEST
                # available frame when it finishes its current work.
                if should_sample(self.frame_count, self.skip_frames):
                    with _ml_lock:
                        _ml_pending_frame["frame"] = frame.copy()
                        _ml_pending_frame["seq"] = cur_seq

                # ALL frames: produce display JPEG with last-known overlay at ~30 FPS
                now = _time.time()
                if now - _last_jpeg_time >= 0.033:  # ~30 FPS JPEG production
                    # Read overlay state atomically (single tuple read)
                    cur_plates, cur_dtrb = _overlay_state
                    if cur_plates and cur_dtrb and len(cur_plates) == len(cur_dtrb):
                        display_frame = draw_plate_overlay_fast(
                            frame, cur_plates, cur_dtrb
                        )
                    else:
                        display_frame = frame
                    # Downscale for display to reduce JPEG encoding time
                    dh, dw = display_frame.shape[:2]
                    if dw > _display_max_width:
                        scale = _display_max_width / dw
                        display_frame = cv2.resize(
                            display_frame,
                            (_display_max_width, int(dh * scale)),
                            interpolation=cv2.INTER_AREA,
                        )
                    _, buf = cv2.imencode(".jpg", display_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                    jpeg_data = buf.tobytes()
                    with self.lock:
                        self.latest_jpeg = jpeg_data
                    _last_jpeg_time = now
        except Exception as e:
            report_detection_error(e, source="RTSPStreamProcessor._run")
            with self.lock:
                self.status = f"error: {e}"

        # Signal the reader and ML worker to exit and wait.
        self.running = False
        reader.join(timeout=3.0)
        ml_thread.join(timeout=3.0)

    def _add_to_history(self, plate, dtrb_text, persian_display, is_valid_iranian, metadata, confidence=None):
        """Add or deduplicate a detection in the history list.

        Deduplication: if same dtrb_text already exists, increment count.
        Extends entries with persian_display, is_valid_iranian, and metadata dict.
        Requirements: 3.3, 7.2, 7.3
        """
        now = datetime.now().strftime("%H:%M:%S")
        conf = confidence if confidence is not None else plate["confidence"]

        # Build metadata dict from PlateMetadata dataclass (or None)
        metadata_dict = None
        if is_valid_iranian and metadata is not None:
            metadata_dict = {
                "classified": metadata.classified,
                "category": metadata.category,
                "category_display": metadata.category_display,
                "color_scheme": metadata.color_scheme,
                "region_code": metadata.region_code,
                "region_name": metadata.region_name,
                "special_note": metadata.special_note,
            }

        # Deduplication: increment count for repeated plate text
        for p in self.plate_history:
            if p["dtrb_text"] == dtrb_text:
                p["count"] += 1
                p["last_seen"] = now
                # Update confidence if new detection has higher confidence
                if conf > p["confidence"]:
                    p["confidence"] = conf
                # Refresh car info if newly available
                if plate.get("car_color") is not None:
                    p["car_color"] = plate.get("car_color")
                if plate.get("car_type") is not None:
                    p["car_type"] = plate.get("car_type")
                if plate.get("city") is not None:
                    p["city"] = plate.get("city")
                return

        self.plate_history.append({
            "dtrb_text": dtrb_text,
            "yolo_text": plate["plate_text"],
            "confidence": conf,
            "first_seen": now,
            "last_seen": now,
            "count": 1,
            "persian_display": persian_display,
            "is_valid_iranian": is_valid_iranian,
            "metadata": metadata_dict,
            "car_color": plate.get("car_color"),
            "car_type": plate.get("car_type"),
            "city": plate.get("city"),
        })

    def get_state(self):
        with self.lock:
            result = {
                "running": self.running,
                "status": self.status,
                "history": list(self.plate_history),
                "live_detections": list(self.live_detections),
                "error_message": self._error_message,
            }
            # Return pre-encoded JPEG bytes instead of copying full numpy array.
            # The UI can decode this directly — avoids 6MB memcopy per poll.
            result["annotated"] = None
            result["jpeg_bytes"] = self.latest_jpeg
            return result
