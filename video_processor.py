import os
import cv2
import numpy as np
import threading
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

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


def draw_plate_template(image_np, plates, dtrb_results):
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

        for ch in plate["chars"]:
            cx1, cy1, cx2, cy2 = ch["bbox"]
            odraw.rectangle([cx1, cy1, cx2, cy2], outline=(50, 255, 100), width=2)

        label_font = get_persian_font(28)
        conf_font = get_persian_font(16)

        label_bbox = draw.textbbox((0, 0), persian_plate, font=label_font)
        label_w = label_bbox[2] - label_bbox[0]
        label_h = label_bbox[3] - label_bbox[1]

        conf_text = f"{confidence:.2%}"
        conf_bbox = draw.textbbox((0, 0), conf_text, font=conf_font)
        conf_w = conf_bbox[2] - conf_bbox[0]
        conf_h = conf_bbox[3] - conf_bbox[1]

        panel_w = label_w + 30
        panel_h = label_h + conf_h + 24
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

    result = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return result


def process_frame(image, detector, recognizer, opt, fast_mode=False):
    image = image.copy()
    results = detector.predict(image, verbose=False)

    char_detections = []
    for result in results:
        if result.boxes is None:
            continue
        for i in range(len(result.boxes.xyxy)):
            conf = result.boxes.conf[i].item()
            if conf > opt.threshold:
                cls_id = int(result.boxes.cls[i].item())
                label = detector.names[cls_id]
                bbox = result.boxes.xyxy[i].cpu().detach().numpy().astype(int)
                x1, y1, x2, y2 = bbox
                char_detections.append({
                    "bbox": (x1, y1, x2, y2),
                    "confidence": conf,
                    "class_id": cls_id,
                    "char": label,
                })

    plates = group_detections(char_detections)

    dtrb_results = []
    for plate in plates:
        x1, y1, x2, y2 = plate["bbox"]
        plate_crop = image[y1:y2, x1:x2].copy()
        if plate_crop.size == 0:
            dtrb_results.append("-")
            continue
        if fast_mode:
            dtrb_results.append(plate["plate_text"])
            continue
        plate_resized = cv2.resize(plate_crop, (opt.imgW, opt.imgH))
        plate_gray = cv2.cvtColor(plate_resized, cv2.COLOR_BGR2GRAY)
        dtrb_label = recognizer.predict(plate_gray, opt)
        dtrb_results.append(dtrb_label)

    annotated = draw_plate_template(image, plates, dtrb_results)
    return annotated, plates, dtrb_results


class VideoProcessor:
    def __init__(self, detector, recognizer, opt):
        self.detector = detector
        self.recognizer = recognizer
        self.opt = opt
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

            output_fps = fps / max(skip_frames, 1)
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
            cached_plates = []
            cached_dtrb = []

            while self.running:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % skip_frames == 0:
                    annotated, plates, dtrb_results = process_frame(
                        frame, self.detector, self.recognizer,
                        self.opt, fast_mode,
                    )
                    if plates:
                        cached_plates = list(plates)
                        cached_dtrb = list(dtrb_results)
                        self.last_overlay = {
                            "plates": list(plates),
                            "dtrb": list(dtrb_results),
                        }

                    writer.write(annotated)

                    live_lines = []
                    for idx, plate in enumerate(plates):
                        dtrb_text = dtrb_results[idx] if idx < len(dtrb_results) else "-"
                        plate_log.append({
                            "frame": frame_idx,
                            "time": f"{frame_idx / fps:.2f}s",
                            "plate_text": plate["plate_text"],
                            "dtrb_text": dtrb_text,
                            "confidence": plate["confidence"],
                        })
                        persian_display = format_plate_persian(dtrb_text)
                        live_lines.append(
                            f"Frame {frame_idx:>6d}  |  {persian_display:16s}  |  "
                            f"conf: {plate['confidence']:.4f}  |  "
                            f"@ {frame_idx / fps:.2f}s"
                        )

                    with self.lock:
                        self.current_frame = annotated
                        self.frame_idx = frame_idx
                        self.live_detections.extend(live_lines)
                        if len(self.live_detections) > 500:
                            self.live_detections = self.live_detections[-500:]
                else:
                    if cached_plates and self.last_overlay:
                        frame_with_overlay = draw_plate_template(
                            frame, cached_plates, cached_dtrb
                        )
                        writer.write(frame_with_overlay)
                    else:
                        writer.write(frame)

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
    def __init__(self, detector, recognizer, opt, source,
                 fast_mode=False, skip_frames=15):
        self.detector = detector
        self.recognizer = recognizer
        self.opt = opt
        self.source = source
        self.fast_mode = fast_mode
        self.skip_frames = skip_frames

        self.cap = None
        self.running = False
        self.frame_count = 0
        self.latest_frame = None
        self.latest_annotated = None
        self.plate_history = []
        self.live_detections = []
        self.status = "initialized"
        self.lock = threading.Lock()
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.running = False
        time.sleep(0.3)
        if self.cap:
            try:
                self.cap.release()
            except:
                pass

    def _run(self):
        self.status = "connecting"
        self.cap = cv2.VideoCapture(self.source)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not self.cap.isOpened():
            with self.lock:
                self.status = "error: cannot connect to stream"
            self.running = False
            return

        self.status = "connected"

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                with self.lock:
                    self.status = "error: stream ended"
                self.running = False
                break

            self.frame_count += 1
            if self.frame_count % self.skip_frames != 0:
                continue

            try:
                annotated, plates, dtrb_results = process_frame(
                    frame, self.detector, self.recognizer,
                    self.opt, self.fast_mode,
                )
                with self.lock:
                    self.latest_annotated = annotated
                    self.status = "streaming"
                    for idx, plate in enumerate(plates):
                        dtrb_text = dtrb_results[idx] if idx < len(dtrb_results) else "-"
                        self._add_to_history(plate, dtrb_text)
                        persian_display = format_plate_persian(dtrb_text)
                        line = (
                            f"[{datetime.now().strftime('%H:%M:%S')}]  "
                            f"{persian_display:16s}  |  conf: "
                            f"{plate['confidence']:.4f}"
                        )
                        self.live_detections.append(line)
                        if len(self.live_detections) > 500:
                            self.live_detections = self.live_detections[-500:]
            except Exception as e:
                with self.lock:
                    self.status = f"error: {e}"

        if self.cap:
            self.cap.release()

    def _add_to_history(self, plate, dtrb_text):
        now = datetime.now().strftime("%H:%M:%S")
        for p in self.plate_history:
            if p["dtrb_text"] == dtrb_text:
                p["count"] += 1
                p["last_seen"] = now
                return
        self.plate_history.append({
            "dtrb_text": dtrb_text,
            "yolo_text": plate["plate_text"],
            "confidence": plate["confidence"],
            "first_seen": now,
            "last_seen": now,
            "count": 1,
        })

    def get_state(self):
        with self.lock:
            result = {
                "running": self.running,
                "status": self.status,
                "history": list(self.plate_history),
                "live_detections": list(self.live_detections),
            }
            if self.latest_annotated is not None:
                result["annotated"] = self.latest_annotated.copy()
            else:
                result["annotated"] = None
            return result
