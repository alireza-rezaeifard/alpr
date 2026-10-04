import cv2
from pathlib import Path

cands = [
    Path(r"D:\alpr\io\output\input_8d7a87720b0842b782eb24cbd469952c.mp4"),
    Path(r"D:\alpr\io\output\processed_cam1.mp4"),
    Path(r"D:\alpr\io\output\processed_cam2.mp4"),
]
for p in cands:
    if not p.exists():
        print(p.name, "MISSING")
        continue
    cap = cv2.VideoCapture(str(p))
    ok = cap.isOpened()
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if ok else 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if ok else 0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if ok else 0
    fps = cap.get(cv2.CAP_PROP_FPS) if ok else 0.0
    r, _ = cap.read()
    cap.release()
    print(f"{p.name:50s} open={ok} frames={n:5d} {w}x{h} fps={fps:.2f} first_read={r} bytes={p.stat().st_size}")

print()
print("KNOWN ORIGINALS (from earlier in this session):")
print("  cam1.mp4  frames=360  1920x1032 fps=30.99 bytes=16109000")
print("  cam2.mp4  frames=599  1920x1080 fps=25.00 bytes=129390859")
