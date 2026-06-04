import os
import argparse
import cv2
import numpy as np
import gradio as gr
from ultralytics import YOLO
from deep_text_recognition_benchmark.dtrb import DTRB
from video_processor import VideoProcessor, RTSPStreamProcessor

DETECTOR_PATH = "plate_detector.pt"
RECOGNIZER_PATH = "weigths/dtrb-recoginzer/dtrb-None-VGG-BiLSTM-CTC-license-plate-recognizer.pth"
OUTPUT_DIR = "io/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

opt = argparse.Namespace(
    workers=0, batch_size=192, batch_max_length=25,
    imgH=32, imgW=100, rgb=False,
    character='0123456789abcdefghijklmnopqrstuvwxyz',
    sensitive=False, PAD=False,
    Transformation="TPS", FeatureExtraction="ResNet",
    SequenceModeling="BiLSTM", Prediction="Attn",
    num_fiducial=20, input_channel=1, output_channel=512,
    hidden_size=256, threshold=0.6,
)

print("Loading detector...")
plate_detector = YOLO(DETECTOR_PATH)
print("Loading recognizer...")
plate_recognizer = DTRB(RECOGNIZER_PATH, opt)

video_proc = VideoProcessor(plate_detector, plate_recognizer, opt)
rtsp_processor = None


def process_image_ui(input_image):
    if input_image is None:
        return None, "No image provided."
    image = input_image.astype(np.uint8)
    if len(image.shape) == 3 and image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    from video_processor import process_frame
    annotated, plates, dtrb_results = process_frame(
        image, plate_detector, plate_recognizer, opt
    )
    annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)

    if not plates:
        return annotated_rgb, "No license plate detected."

    lines = []
    for idx, plate in enumerate(plates):
        dtrb_text = dtrb_results[idx] if idx < len(dtrb_results) else "-"
        lines.append(
            f"Plate #{idx+1}: YOLO={plate['plate_text']}  "
            f"DTRB={dtrb_text}  conf={plate['confidence']:.2f}"
        )
    return annotated_rgb, "\n".join(lines)


def start_video_processing(video_path, skip_frames, fast_mode):
    if not video_path:
        return (None, None, None, "", "", "No video file provided.")
    if not os.path.exists(video_path):
        return (None, None, None, "", "", f"File not found: {video_path}")

    video_proc.process_video(
        video_path,
        skip_frames=int(skip_frames),
        fast_mode=fast_mode,
    )
    return (None, None, None, "", "", f"Processing started... (0/?)")


def stop_video():
    video_proc.stop()
    video_proc.reset()
    return None, None, None, "", "", "Cancelled"


def update_video_preview():
    state = video_proc.get_state()

    preview_rgb = None
    if state["current_frame"] is not None:
        preview_rgb = cv2.cvtColor(state["current_frame"], cv2.COLOR_BGR2RGB)

    total = state["total_frames"]
    current = state["frame_idx"]
    pct = int(current / total * 100) if total > 0 else 0

    if state["status"] == "processing":
        status = f"Processing... ({current}/{total} frames, {pct}%)"
    elif state["status"] == "done":
        unique = len(set(e["dtrb_text"] for e in state["plate_log"]))
        status = (
            f"Done! {len(state['plate_log'])} detections, "
            f"{unique} unique plates."
        )
    elif state["status"] == "error":
        status = f"Error: {state['error']}"
    else:
        status = state["status"]

    log_text = ""
    if state["plate_log"]:
        lines = [
            f"{'Frame':>7}  {'Time':>8}  {'Plate':>14}  "
            f"{'DTRB':>12}  {'Conf':>5}"
        ]
        lines.append("─" * 55)
        for entry in state["plate_log"]:
            lines.append(
                f"{entry['frame']:>7}  {entry['time']:>8}  "
                f"{entry['plate_text']:>14}  {entry['dtrb_text']:>12}  "
                f"{entry['confidence']:.2f}"
            )
        log_text = "\n".join(lines)

    live_text = ""
    if state["live_detections"]:
        live_lines = state["live_detections"]
        show = live_lines[-50:]
        live_text = "\n".join(show)

    video_file = state["output_path"]
    if video_file is not None:
        if not os.path.exists(video_file):
            print(f"[Warning] output path does not exist: {video_file}")
            video_file = None
    else:
        video_file = gr.update()
    return (
        preview_rgb,
        video_file,
        video_file,
        log_text,
        live_text,
        status,
    )


def start_rtsp(rtsp_url, fast_mode, skip_frames):
    global rtsp_processor

    if not rtsp_url or not rtsp_url.strip():
        return None, None, None, "Please enter a valid RTSP URL."

    if rtsp_processor is not None:
        rtsp_processor.stop()
        rtsp_processor = None

    rtsp_processor = RTSPStreamProcessor(
        plate_detector, plate_recognizer, opt, rtsp_url.strip(),
        fast_mode=fast_mode, skip_frames=int(skip_frames),
    )
    rtsp_processor.start()

    return None, None, None, "Connecting to stream..."


def stop_rtsp():
    global rtsp_processor
    if rtsp_processor is not None:
        rtsp_processor.stop()
        rtsp_processor = None
    return None, None, None, "Stream stopped."


def update_rtsp_feed():
    global rtsp_processor

    if rtsp_processor is None:
        return None, None, None, "No stream active."

    state = rtsp_processor.get_state()

    if state["status"].startswith("error"):
        return None, None, None, f"Error: {state['status']}"

    annotated_rgb = None
    if state["annotated"] is not None:
        annotated_rgb = cv2.cvtColor(state["annotated"], cv2.COLOR_BGR2RGB)

    history = state["history"]
    if not history:
        status = f"Status: {state['status']} — waiting for plates..."
    else:
        last = history[-1]
        status = (
            f"Status: {state['status']} — "
            f"{len(history)} unique plates, "
            f"last: {last['dtrb_text']} ({last['count']}x)"
        )

    history_lines = []
    for i, p in enumerate(history):
        history_lines.insert(0,
            f"#{i+1:3d} | {p['dtrb_text']:12s} | "
            f"conf: {p['confidence']:.2f} | "
            f"count: {p['count']:3d} | "
            f"first: {p['first_seen']} | last: {p['last_seen']}"
        )
    history_text = "\n".join(history_lines) if history_lines else "(no plates detected yet)"

    live_text = ""
    if state["live_detections"]:
        show = state["live_detections"][-50:]
        live_text = "\n".join(show)

    return annotated_rgb, history_text, live_text, status


with gr.Blocks(title="Persian License Plate Recognition") as demo:
    gr.Markdown(
        "# Persian License Plate Recognition\n"
        "Detect and recognize Persian license plates from images, videos, or live RTSP streams"
    )

    with gr.Tabs():
        with gr.TabItem("Image"):
            with gr.Row():
                with gr.Column(scale=1):
                    img_input = gr.Image(label="Input Image", type="numpy", height=350)
                    with gr.Row():
                        img_submit = gr.Button("Process", variant="primary", size="lg")
                        img_clear = gr.Button("Clear", size="lg")
                    gr.Examples(
                        examples=[["car_a.jpg"], ["car_b.jpg"], ["car_c.jpg"], ["car_d.jpg"]],
                        inputs=img_input, label="Sample Images",
                    )
                with gr.Column(scale=1):
                    img_output = gr.Image(label="Result", type="numpy", height=350)
                    img_text = gr.Textbox(label="Recognition Results", lines=6)

            img_submit.click(
                fn=process_image_ui, inputs=img_input,
                outputs=[img_output, img_text]
            )
            img_clear.click(
                fn=lambda: (None, ""), outputs=[img_output, img_text]
            )

        with gr.TabItem("Video"):
            gr.Markdown("### Process a video file — watch the live preview as plates are detected")
            with gr.Row():
                with gr.Column(scale=1):
                    vid_input = gr.Video(label="Upload Video", height=200)
                    with gr.Row():
                        vid_skip = gr.Slider(
                            minimum=1, maximum=120, value=30, step=1,
                            label="Process every Nth frame"
                        )
                        vid_fast = gr.Checkbox(
                            label="Fast mode (YOLO only, skip DTRB)", value=False
                        )
                    with gr.Row():
                        vid_start = gr.Button(
                            "Start Processing", variant="primary", size="lg"
                        )
                        vid_stop = gr.Button("Cancel", size="lg")
                    vid_status = gr.Textbox(
                        label="Status", value="Not started", lines=2
                    )
                    vid_live_detections = gr.Textbox(
                        label="Live Detections (console output)",
                        lines=10, max_lines=25,
                        value="",
                    )
                with gr.Column(scale=1):
                    vid_preview = gr.Image(
                        label="Live Preview (updates during processing)",
                        height=200, type="numpy",
                    )
                    vid_output = gr.Video(label="Final Processed Video", height=240)
                    vid_download = gr.File(
                        label="Download Processed Video",
                        file_count="single",
                    )
                    vid_log = gr.Textbox(
                        label="Complete Plate Detection Log", lines=6, max_lines=20
                    )

            vid_start.click(
                fn=start_video_processing,
                inputs=[vid_input, vid_skip, vid_fast],
                outputs=[vid_preview, vid_output, vid_download, vid_log, vid_live_detections, vid_status],
            )
            vid_stop.click(
                fn=stop_video,
                outputs=[vid_preview, vid_output, vid_download, vid_log, vid_live_detections, vid_status],
            )

            vid_timer = gr.Timer(value=0.5, active=True)
            vid_timer.tick(
                fn=update_video_preview,
                outputs=[vid_preview, vid_output, vid_download, vid_log, vid_live_detections, vid_status],
            )

        with gr.TabItem("Live RTSP"):
            with gr.Row():
                with gr.Column(scale=1):
                    rtsp_url = gr.Textbox(
                        label="RTSP / Stream URL",
                        placeholder="rtsp://username:password@192.168.1.100:554/stream",
                        value="",
                    )
                    with gr.Row():
                        rtsp_fast = gr.Checkbox(
                            label="Fast mode (YOLO only)", value=False
                        )
                        rtsp_skip = gr.Slider(
                            minimum=1, maximum=60, value=15, step=1,
                            label="Process every Nth frame"
                        )
                    with gr.Row():
                        rtsp_start = gr.Button("Start Stream", variant="primary", size="lg")
                        rtsp_stop = gr.Button("Stop Stream", variant="stop", size="lg")
                    rtsp_status = gr.Textbox(
                        label="Status", lines=2, value="Not started"
                    )
                    rtsp_live_detections = gr.Textbox(
                        label="Live Detections (console output)",
                        lines=10, max_lines=25,
                        value="(no detections yet)",
                    )
                with gr.Column(scale=1):
                    rtsp_feed = gr.Image(label="Live Feed", height=350)
                    rtsp_history = gr.Textbox(
                        label="Detected Plates (newest first)",
                        lines=8, max_lines=25,
                        value="(no plates detected yet)",
                    )

            rtsp_start.click(
                fn=start_rtsp,
                inputs=[rtsp_url, rtsp_fast, rtsp_skip],
                outputs=[rtsp_feed, rtsp_history, rtsp_live_detections, rtsp_status],
            )
            rtsp_stop.click(
                fn=stop_rtsp,
                outputs=[rtsp_feed, rtsp_history, rtsp_live_detections, rtsp_status],
            )

            rtsp_timer = gr.Timer(value=0.5, active=True)
            rtsp_timer.tick(
                fn=update_rtsp_feed,
                outputs=[rtsp_feed, rtsp_history, rtsp_live_detections, rtsp_status],
            )


if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
    )
