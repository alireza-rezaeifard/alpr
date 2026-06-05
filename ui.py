import os, argparse, json, cv2, numpy as np
import gradio as gr
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime
from ultralytics import YOLO
from deep_text_recognition_benchmark.dtrb import DTRB
from video_processor import VideoProcessor, RTSPStreamProcessor, format_plate_persian
from db import init_db, start_session, end_session, save_detection, get_stats, get_recent_detections, get_all_detections, get_detections_timeline, get_letter_frequency, get_source_distribution, get_confidence_distribution, get_sessions_history

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False

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
init_db()

image_session_id = None
video_session_id = None
rtsp_session_id = None

CSS = """
:root{--primary:#2563eb;--primary-light:#3b82f6;--bg:#0f172a;--surface:#1e293b;--surface-2:#334155;--text:#f1f5f9;--text-muted:#94a3b8;--success:#22c55e;--warning:#f59e0b;--danger:#ef4444;--border:#475569}
.sc{display:flex;gap:16px;flex-wrap:wrap}
.sc>div{flex:1;min-width:160px;padding:18px 22px;border-radius:12px;background:var(--surface);border:1px solid var(--border)}
.sc .l{font-size:13px;color:var(--text-muted)}
.sc .v{font-size:30px;font-weight:700}
.sc .s{font-size:12px;color:var(--text-muted);margin-top:4px}
.tbl{width:100%;border-collapse:collapse;font-family:inherit}
.tbl th{text-align:left;padding:8px 10px;color:var(--text-muted);font-size:12px;font-weight:500;border-bottom:2px solid var(--border)}
.tbl td{padding:6px 10px;border-bottom:1px solid var(--border);font-size:13px}
"""


def sc(label, value, color="var(--primary-light)", sub=""):
    return f'<div><div class="l">{label}</div><div class="v" style="color:{color}">{value}</div>{"<div class=\"s\">"+sub+"</div>" if sub else ""}</div>'


def build_dashboard():
    s = get_stats()
    return "".join([
        '<div class="sc">',
        sc("Total Detections", s["total_detections"], "#3b82f6", f"{s['detections_7d']} in 7d"),
        sc("Unique Plates", s["unique_plates"], "#22c55e"),
        sc("Sessions", s["total_sessions"], "#f59e0b", f"{s['sessions_7d']} in 7d"),
        sc("Avg Confidence", f"{s['avg_confidence']:.1%}" if s["avg_confidence"] else "N/A", "#22c55e"),
        "</div>",
    ])


def build_timeline():
    data = get_detections_timeline(14)
    fig, ax = plt.subplots(figsize=(8, 3))
    if data:
        d = [x["dt"] for x in data]
        c = [x["cnt"] for x in data]
        ax.plot(d, c, color="#3b82f6", lw=2, marker="o", ms=4)
        ax.fill_between(d, c, alpha=0.12, color="#3b82f6")
    ax.set_facecolor("#1e293b"); fig.patch.set_facecolor("#0f172a")
    ax.tick_params(colors="#94a3b8", labelsize=9)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color("#475569")
    ax.set_ylabel("Detections", color="#94a3b8", fontsize=10)
    ax.set_xlabel("Date", color="#94a3b8", fontsize=10)
    for l in ax.get_xticklabels(): l.set_rotation(30); l.set_ha("right")
    fig.tight_layout(); return fig


def build_source_pie():
    data = get_source_distribution()
    fig, ax = plt.subplots(figsize=(4, 2.8))
    if data:
        labels = [x["source_type"].capitalize() for x in data]
        sizes = [x["cnt"] for x in data]
        cols = ["#3b82f6", "#22c55e", "#f59e0b"]
        w, _, t = ax.pie(sizes, labels=None, autopct="%1.0f%%", startangle=90, colors=cols[:len(sizes)], textprops={"color": "#f1f5f9", "fontsize": 9})
        for x in t: x.set_color("#0f172a"); x.set_fontweight("bold")
        ax.legend(labels, loc="upper right", framealpha=0, fontsize=8, labelcolor="#94a3b8")
    ax.set_facecolor("#1e293b"); fig.patch.set_facecolor("#0f172a"); return fig


def build_conf_hist():
    data = get_confidence_distribution()
    fig, ax = plt.subplots(figsize=(4, 2.8))
    if data:
        ax.bar([x["bin"] for x in data], [x["cnt"] for x in data], width=0.05, color="#22c55e", alpha=0.8)
    ax.set_facecolor("#1e293b"); fig.patch.set_facecolor("#0f172a")
    ax.tick_params(colors="#94a3b8", labelsize=9)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color("#475569")
    ax.set_xlabel("Confidence", color="#94a3b8", fontsize=10)
    ax.set_ylabel("Count", color="#94a3b8", fontsize=10)
    fig.tight_layout(); return fig


def build_plate_chart():
    data = get_letter_frequency()
    fig, ax = plt.subplots(figsize=(4, 2.8))
    if data:
        plates = [x["plate_persian"][:18] for x in data[:10]]
        counts = [x["cnt"] for x in data[:10]]
        ax.barh(range(len(plates)), counts, color=plt.cm.Blues(np.linspace(0.45, 0.9, len(plates))))
        ax.set_yticks(range(len(plates))); ax.set_yticklabels(plates, fontsize=8, color="#f1f5f9")
        ax.invert_yaxis()
    ax.set_facecolor("#1e293b"); fig.patch.set_facecolor("#0f172a")
    ax.tick_params(colors="#94a3b8", labelsize=9)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color("#475569")
    ax.set_xlabel("Count", color="#94a3b8", fontsize=10)
    fig.tight_layout(); return fig


def build_recent():
    dets = get_recent_detections(10)
    if not dets:
        return "<div style='padding:16px;color:var(--text-muted)'>No detections yet.</div>"
    rows = "".join(
        f"<tr><td>{d['timestamp'][:19].replace('T',' ')}</td><td>{d['plate_persian'] or d['plate_dtrb']}</td><td>{d['source_type'].capitalize()}</td><td style='color:var(--success)'>{d['confidence']:.1%}</td></tr>"
        for d in dets
    )
    return f'<table class="tbl"><thead><tr><th>Time</th><th>Plate</th><th>Source</th><th>Conf</th></tr></thead><tbody>{rows}</tbody></table>'


def refresh_dashboard_all():
    return build_dashboard(), build_timeline(), build_source_pie(), build_conf_hist(), build_plate_chart(), build_recent()


def refresh_dashboard_partial():
    return build_dashboard(), build_recent()


def process_image_ui(input_image):
    global image_session_id
    if input_image is None:
        return None, "", gr.update(), gr.update()
    image = input_image.astype(np.uint8)
    if len(image.shape) == 3 and image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    from video_processor import process_frame
    annotated, plates, dtrb_results = process_frame(image, plate_detector, plate_recognizer, opt)
    annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)

    if not plates:
        return annotated_rgb, "No license plate detected.", build_dashboard(), build_recent()

    lines = []
    for idx, plate in enumerate(plates):
        dtrb_text = dtrb_results[idx] if idx < len(dtrb_results) else "-"
        persian = format_plate_persian(dtrb_text)
        lines.append(f"Plate #{idx+1}: {persian}  (conf: {plate['confidence']:.2%})")
        sid = image_session_id or start_session("image", "direct_upload")
        if image_session_id is None: image_session_id = sid
        save_detection(sid, "image", dtrb_text, persian, plate["confidence"], "direct_upload")

    return annotated_rgb, "\n".join(lines), build_dashboard(), build_recent()


def start_video_processing(video_path, skip_frames, fast_mode):
    global video_session_id
    if not video_path:
        return None, None, None, "", "", "No video file.", gr.update(), gr.update()
    if not os.path.exists(video_path):
        return None, None, None, "", "", f"Not found: {video_path}", gr.update(), gr.update()
    video_session_id = start_session("video", video_path)

    def on_det(src, text, conf, file, frame, ftime):
        save_detection(video_session_id, src, text, format_plate_persian(text), conf, file, frame, ftime)
    video_proc.on_detection = on_det

    video_proc.process_video(video_path, skip_frames=int(skip_frames), fast_mode=fast_mode)
    return None, None, None, "", "", f"Processing started... (0/?)", gr.update(), gr.update()


def stop_video():
    global video_session_id
    video_proc.stop(); video_proc.reset()
    video_session_id = None
    return None, None, None, "", "", "Cancelled", gr.update(), gr.update()


def update_video_preview():
    state = video_proc.get_state()
    preview_rgb = None
    if state["current_frame"] is not None:
        preview_rgb = cv2.cvtColor(state["current_frame"], cv2.COLOR_BGR2RGB)
    total, current = state["total_frames"], state["frame_idx"]
    pct = int(current / total * 100) if total > 0 else 0

    if state["status"] == "processing":
        status = f"Processing... ({current}/{total} frames, {pct}%)"
    elif state["status"] == "done":
        unique = len(set(e["dtrb_text"] for e in state["plate_log"]))
        status = f"Done! {len(state['plate_log'])} detections, {unique} unique plates."
        end_session(video_session_id, total, len(state["plate_log"]), unique) if video_session_id else None
    elif state["status"] == "error":
        status = f"Error: {state['error']}"
    else:
        status = state["status"]

    log_text = ""
    if state["plate_log"]:
        h = f"{'Frame':>7}  {'Time':>8}  {'Plate':>14}  {'DTRB':>12}  {'Conf':>5}"
        log_text = h + "\n" + "\u2500" * 55 + "\n"
        log_text += "\n".join(f"{e['frame']:>7}  {e['time']:>8}  {e['plate_text']:>14}  {e['dtrb_text']:>12}  {e['confidence']:.2f}" for e in state["plate_log"])

    live_text = "\n".join(state["live_detections"][-50:]) if state["live_detections"] else ""
    video_file = state["output_path"]
    if video_file is not None:
        if not os.path.exists(video_file): video_file = None
    else:
        video_file = gr.update()
    return preview_rgb, video_file, video_file, log_text, live_text, status, build_dashboard(), build_recent()


def start_rtsp(rtsp_url, fast_mode, skip_frames):
    global rtsp_processor, rtsp_session_id
    if not rtsp_url or not rtsp_url.strip():
        return None, None, None, "Enter a valid RTSP URL.", gr.update(), gr.update()
    if rtsp_processor is not None:
        rtsp_processor.stop(); rtsp_processor = None
    rtsp_session_id = start_session("rtsp", rtsp_url.strip())

    def on_det(src, text, conf, file, frame, ftime):
        save_detection(rtsp_session_id, src, text, format_plate_persian(text), conf, file, frame, ftime)
    rtsp_processor = RTSPStreamProcessor(plate_detector, plate_recognizer, opt, rtsp_url.strip(),
        fast_mode=fast_mode, skip_frames=int(skip_frames), on_detection=on_det)
    rtsp_processor.start()
    return None, None, None, "Connecting to stream...", gr.update(), gr.update()


def stop_rtsp():
    global rtsp_processor, rtsp_session_id
    if rtsp_processor is not None:
        state = rtsp_processor.get_state()
        if rtsp_session_id:
            end_session(rtsp_session_id, 0, len(state["history"]), len(set(p["dtrb_text"] for p in state["history"])))
        rtsp_processor.stop(); rtsp_processor = None
    rtsp_session_id = None
    return None, None, None, "Stream stopped.", gr.update(), gr.update()


def update_rtsp_feed():
    global rtsp_processor
    if rtsp_processor is None:
        return None, None, None, "No stream active.", gr.update(), gr.update()
    state = rtsp_processor.get_state()
    if state["status"].startswith("error"):
        return None, None, None, f"Error: {state['status']}", gr.update(), gr.update()
    annotated_rgb = None
    if state["annotated"] is not None:
        annotated_rgb = cv2.cvtColor(state["annotated"], cv2.COLOR_BGR2RGB)
    history = state["history"]
    status = f"Status: {state['status']} — waiting for plates..." if not history else f"Status: {state['status']} — {len(history)} unique plates, last: {format_plate_persian(history[-1].get('dtrb_text','?'))} ({history[-1]['count']}x)"
    hist_lines = []
    for i, p in enumerate(history):
        hist_lines.insert(0, f"#{i+1:3d} | {format_plate_persian(p.get('dtrb_text','?')):16s} | conf: {p['confidence']:.2f} | count: {p['count']:3d} | first: {p['first_seen']} | last: {p['last_seen']}")
    history_text = "\n".join(hist_lines) if hist_lines else "(no plates detected yet)"
    live_text = "\n".join(state["live_detections"][-50:]) if state["live_detections"] else ""
    return annotated_rgb, history_text, live_text, status, build_dashboard(), build_recent()


def build_history_table(source_type, search_text):
    dets, total = get_all_detections(limit=200, source_type=source_type, search=search_text)
    if not dets:
        return "<div style='padding:16px;color:var(--text-muted)'>No records found.</div>"
    rows = "".join(
        f"<tr><td>{d['timestamp'][:19].replace('T',' ')}</td><td>{d['plate_persian'] or d['plate_dtrb']}</td><td>{d['source_type'].capitalize()}</td><td style='color:var(--success)'>{d['confidence']:.1%}</td><td>{os.path.basename(d['source_file'] or '-')}</td></tr>"
        for d in dets
    )
    return f'<table class="tbl"><thead><tr><th>Time</th><th>Plate</th><th>Source</th><th>Conf</th><th>File</th></tr></thead><tbody>{rows}</tbody></table><div style="padding:8px 0;color:var(--text-muted);font-size:12px">{total} total records</div>'


def build_sessions_table():
    sessions = get_sessions_history(20)
    if not sessions:
        return "<div style='padding:16px;color:var(--text-muted)'>No sessions yet.</div>"
    rows = ""
    for s in sessions:
        dur = ""
        if s["started_at"] and s["ended_at"]:
            try:
                secs = (datetime.fromisoformat(s["ended_at"]) - datetime.fromisoformat(s["started_at"])).total_seconds()
                dur = f"{secs:.0f}s"
            except: pass
        color = {"done":"var(--success)","running":"var(--warning)","error":"var(--danger)"}.get(s["status"],"var(--text)")
        rows += f"<tr><td>{s['started_at'][:19].replace('T',' ')}</td><td>{s['source_type'].capitalize()}</td><td style='color:{color}'>{s['status']}</td><td>{s['total_plates']}</td><td>{dur}</td></tr>"
    return f'<table class="tbl"><thead><tr><th>Started</th><th>Source</th><th>Status</th><th>Plates</th><th>Duration</th></tr></thead><tbody>{rows}</tbody></table>'


def save_video_detection(src, text, conf, file, frame, ftime):
    global video_session_id
    if video_session_id:
        save_detection(video_session_id, src, text, format_plate_persian(text), conf, file, frame, ftime)


# --- Create processors with callbacks ---
video_proc = VideoProcessor(plate_detector, plate_recognizer, opt)
rtsp_processor = None


with gr.Blocks(title="Persian License Plate Recognition") as demo:
    gr.Markdown("# \U0001f697 Persian License Plate Recognition  \u2014 Dashboard")
    gr.Markdown("Detect and recognize Persian license plates from images, videos, or live RTSP streams")

    dashboard_html = gr.HTML(value=build_dashboard())
    with gr.Row(equal_height=False):
        with gr.Column(scale=2):
            timeline_plot = gr.Plot(label="Detection Timeline (14 days)", value=build_timeline())
        with gr.Column(scale=1):
            source_plot = gr.Plot(label="By Source", value=build_source_pie())
    with gr.Row(equal_height=False):
        with gr.Column(scale=1):
            conf_plot = gr.Plot(label="Confidence Distribution", value=build_conf_hist())
        with gr.Column(scale=1):
            letter_plot = gr.Plot(label="Most Detected Plates", value=build_plate_chart())
    gr.Markdown("### \U0001f4cb Recent Detections")
    recent_table = gr.HTML(value=build_recent())
    gr.Markdown("---")

    with gr.Tabs():
        with gr.TabItem("\U0001f5bc  Image"):
            with gr.Row():
                with gr.Column(scale=1):
                    img_input = gr.Image(label="Input Image", type="numpy", height=300)
                    with gr.Row():
                        img_submit = gr.Button("Process", variant="primary")
                        img_clear = gr.Button("Clear")
                    gr.Examples(examples=[["car_a.jpg"],["car_b.jpg"],["car_c.jpg"],["car_d.jpg"]], inputs=img_input, label="Sample Images")
                with gr.Column(scale=1):
                    img_output = gr.Image(label="Result", type="numpy", height=300)
                    img_text = gr.Textbox(label="Recognition Results", lines=5)
            img_submit.click(fn=process_image_ui, inputs=img_input, outputs=[img_output, img_text, dashboard_html, recent_table])
            img_clear.click(fn=lambda: (None, ""), outputs=[img_output, img_text])

        with gr.TabItem("\U0001f3ac  Video"):
            with gr.Row():
                with gr.Column(scale=1):
                    vid_input = gr.Video(label="Upload Video", height=180)
                    with gr.Row():
                        vid_skip = gr.Slider(minimum=1, maximum=120, value=30, step=1, label="Process every Nth frame")
                        vid_fast = gr.Checkbox(label="Fast mode (YOLO only)", value=False)
                    with gr.Row():
                        vid_start = gr.Button("Start Processing", variant="primary")
                        vid_stop = gr.Button("Cancel")
                    vid_status = gr.Textbox(label="Status", value="Not started", lines=2)
                    vid_live = gr.Textbox(label="Live Detections", lines=8, max_lines=20, value="")
                with gr.Column(scale=1):
                    vid_preview = gr.Image(label="Live Preview", height=180, type="numpy")
                    vid_output = gr.Video(label="Final Processed Video", height=200)
                    vid_download = gr.File(label="Download Processed Video")
                    vid_log = gr.Textbox(label="Complete Detection Log", lines=4, max_lines=15)

            vid_start.click(fn=start_video_processing, inputs=[vid_input, vid_skip, vid_fast],
                outputs=[vid_preview, vid_output, vid_download, vid_log, vid_live, vid_status, dashboard_html, recent_table])
            vid_stop.click(fn=stop_video,
                outputs=[vid_preview, vid_output, vid_download, vid_log, vid_live, vid_status, dashboard_html, recent_table])

            gr.Timer(value=0.5, active=True).tick(fn=update_video_preview,
                outputs=[vid_preview, vid_output, vid_download, vid_log, vid_live, vid_status, dashboard_html, recent_table])

        with gr.TabItem("\U0001f4e1  Live RTSP"):
            with gr.Row():
                with gr.Column(scale=1):
                    rtsp_url = gr.Textbox(label="RTSP / Stream URL", placeholder="rtsp://username:password@192.168.1.100:554/stream", value="")
                    with gr.Row():
                        rtsp_fast = gr.Checkbox(label="Fast mode (YOLO only)", value=False)
                        rtsp_skip = gr.Slider(minimum=1, maximum=60, value=15, step=1, label="Process every Nth frame")
                    with gr.Row():
                        rtsp_start = gr.Button("Start Stream", variant="primary")
                        rtsp_stop = gr.Button("Stop Stream", variant="stop")
                    rtsp_status = gr.Textbox(label="Status", lines=2, value="Not started")
                    rtsp_live = gr.Textbox(label="Live Detections", lines=8, max_lines=20, value="(no detections yet)")
                with gr.Column(scale=1):
                    rtsp_feed = gr.Image(label="Live Feed", height=300)
                    rtsp_history = gr.Textbox(label="Detected Plates (newest first)", lines=6, max_lines=20, value="(no plates detected yet)")

            rtsp_start.click(fn=start_rtsp, inputs=[rtsp_url, rtsp_fast, rtsp_skip],
                outputs=[rtsp_feed, rtsp_history, rtsp_live, rtsp_status, dashboard_html, recent_table])
            rtsp_stop.click(fn=stop_rtsp,
                outputs=[rtsp_feed, rtsp_history, rtsp_live, rtsp_status, dashboard_html, recent_table])

            gr.Timer(value=0.5, active=True).tick(fn=update_rtsp_feed,
                outputs=[rtsp_feed, rtsp_history, rtsp_live, rtsp_status, dashboard_html, recent_table])

        with gr.TabItem("\U0001f4ca  Analytics"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=2): a_timeline = gr.Plot(label="Detection Timeline (14 days)", value=build_timeline())
                with gr.Column(scale=1): a_source = gr.Plot(label="By Source", value=build_source_pie())
            with gr.Row(equal_height=False):
                with gr.Column(scale=1): a_conf = gr.Plot(label="Confidence Distribution", value=build_conf_hist())
                with gr.Column(scale=1): a_letter = gr.Plot(label="Most Detected Plates", value=build_plate_chart())
            gr.Button("Refresh Charts", variant="secondary").click(
                fn=lambda: (build_timeline(), build_source_pie(), build_conf_hist(), build_plate_chart()),
                outputs=[a_timeline, a_source, a_conf, a_letter])

        with gr.TabItem("\U0001f4d1  History"):
            h_table = gr.HTML(value=build_history_table("all",""))
            with gr.Row():
                h_source = gr.Dropdown(choices=["all","image","video","rtsp"], value="all", label="Filter by Source")
                h_search = gr.Textbox(label="Search", placeholder="Search plate text...")
                gr.Button("Refresh", variant="primary").click(fn=build_history_table, inputs=[h_source, h_search], outputs=h_table)
            h_source.change(fn=build_history_table, inputs=[h_source, h_search], outputs=h_table)
            h_search.submit(fn=build_history_table, inputs=[h_source, h_search], outputs=h_table)

        with gr.TabItem("\U0001f4cb  Sessions"):
            s_tbl = gr.HTML(value=build_sessions_table())
            gr.Button("Refresh", variant="primary").click(fn=build_sessions_table, outputs=s_tbl)

        with gr.TabItem("\U0001f4a1  Batch"):
            gr.Markdown("### Batch Process Folder\nProcess multiple images from a folder.")
            with gr.Row():
                batch_folder = gr.Textbox(label="Image Folder Path", placeholder="io/input/")
                batch_fast = gr.Checkbox(label="Fast mode", value=False)
            batch_run = gr.Button("Run Batch", variant="primary")
            batch_output = gr.Textbox(label="Results", lines=15, max_lines=50)
            batch_run.click(fn=lambda folder, fast: "Batch processing not yet implemented.\nPoint to a folder containing .jpg files.", inputs=[batch_folder, batch_fast], outputs=batch_output)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False,
        theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate"), css=CSS)
