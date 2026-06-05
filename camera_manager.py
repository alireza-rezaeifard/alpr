"""
camera_manager.py
CameraManager: manages concurrent RTSPStreamProcessor instances with a FIFO queue and
configurable concurrency limit. Thread-safe via RLock.
Requirements: 11.1, 11.4, 11.8, 12.1, 12.3, 12.4, 12.5, 12.6, 12.7, 12.9, 13.9
"""
from __future__ import annotations
import uuid
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from db import (
    create_camera, list_cameras, get_camera, update_camera, delete_camera,
    start_session, end_session, get_concurrency_limit, set_concurrency_limit as _db_set_limit,
)


@dataclass
class CameraRuntime:
    """Runtime state for a single camera slot."""
    camera_id: int
    name: str
    url: str
    skip_frames: int
    status: str = "stopped"     # stopped|queued|connecting|connected|streaming|error
    task_id: Optional[str] = None
    session_id: Optional[int] = None
    processor: object = None    # RTSPStreamProcessor instance


class CameraManager:
    def __init__(self, ensure_models_fn: Callable):
        """
        :param ensure_models_fn: callable returning (detector, recognizer, opt) —
                                 used to lazy-load ML models when starting a processor.
        """
        self._lock = threading.RLock()
        self._cameras: dict[int, CameraRuntime] = {}
        self._queue: deque[int] = deque()
        self._concurrency_limit: int = get_concurrency_limit()
        self._ensure_models = ensure_models_fn

    # ------------------------------------------------------------------
    # CRUD (write-through to DB)
    # ------------------------------------------------------------------

    def add_camera(self, name: str, url: str, skip_frames: int | None = None) -> dict:
        """Create a new camera record and register it in the in-memory map.

        Requirements: 11.1, 11.8
        """
        sf = skip_frames if skip_frames is not None else 15
        record = create_camera(name, url, sf)
        with self._lock:
            self._cameras[record["id"]] = CameraRuntime(
                camera_id=record["id"],
                name=record["name"],
                url=record["url"],
                skip_frames=record["skip_frames"],
                status="stopped",
            )
        return self._to_view(record["id"])

    def list_cameras_view(self) -> list[dict]:
        """Return a view snapshot of all cameras sorted by id."""
        with self._lock:
            return [self._to_view(cid) for cid in sorted(self._cameras)]

    def get_camera_view(self, camera_id: int) -> dict | None:
        """Return a view snapshot for a single camera, or None if not found."""
        with self._lock:
            if camera_id not in self._cameras:
                return None
            return self._to_view(camera_id)

    def update_camera_info(
        self,
        camera_id: int,
        name: str | None = None,
        url: str | None = None,
        skip_frames: int | None = None,
    ) -> dict | None:
        """Update persisted camera fields and mirror changes in the runtime map.

        Requirements: 11.4
        """
        updated = update_camera(camera_id, name=name, url=url, skip_frames=skip_frames)
        if updated is None:
            return None
        with self._lock:
            if camera_id in self._cameras:
                rt = self._cameras[camera_id]
                if name is not None:
                    rt.name = name
                if url is not None:
                    rt.url = url
                if skip_frames is not None:
                    rt.skip_frames = skip_frames
        return self._to_view(camera_id)

    def remove_camera(self, camera_id: int) -> bool:
        """Stop any running processor, end the session, remove from queue and map, then delete from DB.

        Requirements: 11.4, 11.8
        """
        with self._lock:
            if camera_id not in self._cameras:
                return False
            self._stop_camera_locked(camera_id, end_sess=True)
            # Remove from queue if present
            try:
                self._queue.remove(camera_id)
            except ValueError:
                pass
            del self._cameras[camera_id]
        delete_camera(camera_id)
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_camera(self, camera_id: int) -> dict:
        """Start a camera. Returns status 'running' or 'queued'.

        If the number of running processors is below the concurrency limit the camera is
        started immediately; otherwise it is enqueued FIFO.
        Requirements: 12.1, 12.3, 12.5
        """
        with self._lock:
            if camera_id not in self._cameras:
                return {"camera_id": camera_id, "status": "error", "task_id": None}
            rt = self._cameras[camera_id]
            # Already active — return current state
            if rt.status in ("connecting", "connected", "streaming"):
                return {"camera_id": camera_id, "status": "running", "task_id": rt.task_id}
            # Already queued — idempotent
            if rt.status == "queued":
                return {"camera_id": camera_id, "status": "queued", "task_id": None}
            running_count = self._running_count()
            if running_count < self._concurrency_limit:
                self._start_processor_locked(rt)
                return {"camera_id": camera_id, "status": "running", "task_id": rt.task_id}
            else:
                if camera_id not in self._queue:
                    self._queue.append(camera_id)
                rt.status = "queued"
                return {"camera_id": camera_id, "status": "queued", "task_id": None}

    def stop_camera(self, camera_id: int) -> dict:
        """Stop a running or queued camera and promote the earliest queued camera if a slot opens.

        Requirements: 12.9
        """
        with self._lock:
            if camera_id not in self._cameras:
                return {"status": "not_found"}
            was_running = self._cameras[camera_id].status in ("connecting", "connected", "streaming")
            self._stop_camera_locked(camera_id, end_sess=True)
            # Remove from queue if it was queued
            try:
                self._queue.remove(camera_id)
            except ValueError:
                pass
            # Only promote if a running slot was freed
            if was_running:
                self._promote_from_queue()
        return {"status": "stopped"}

    def start_all(self) -> list[dict]:
        """Attempt to start every stopped or error camera.

        Requirements: 12.1
        """
        results = []
        with self._lock:
            for cid in sorted(self._cameras):
                rt = self._cameras[cid]
                if rt.status in ("stopped", "error"):
                    results.append(self.start_camera(cid))
        return results

    def stop_all(self) -> None:
        """Stop all running processors, end their sessions, and clear the queue.

        Requirements: 12.6
        """
        with self._lock:
            self._queue.clear()
            for cid in list(self._cameras):
                self._stop_camera_locked(cid, end_sess=True)

    # ------------------------------------------------------------------
    # Concurrency config
    # ------------------------------------------------------------------

    def set_concurrency_limit(self, value: int) -> None:
        """Validate and persist a new concurrency limit.

        Requirements: 12.7
        """
        if not (1 <= value <= 64):
            raise ValueError(f"Concurrency limit must be between 1 and 64, got {value}")
        with self._lock:
            self._concurrency_limit = value
        _db_set_limit(value)

    def get_limit(self) -> int:
        """Return the current concurrency limit."""
        with self._lock:
            return self._concurrency_limit

    # ------------------------------------------------------------------
    # Startup restoration
    # ------------------------------------------------------------------

    def restore_on_startup(self) -> None:
        """Load all persisted cameras with status=stopped (no auto-start).

        Requirements: 11.8
        """
        rows = list_cameras()
        with self._lock:
            for row in rows:
                self._cameras[row["id"]] = CameraRuntime(
                    camera_id=row["id"],
                    name=row["name"],
                    url=row["url"],
                    skip_frames=row["skip_frames"],
                    status="stopped",
                )

    # ------------------------------------------------------------------
    # Status query
    # ------------------------------------------------------------------

    def get_status(self, camera_id: int) -> dict | None:
        """Return the current view for a camera, or None if not found."""
        with self._lock:
            return self._to_view(camera_id) if camera_id in self._cameras else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _running_count(self) -> int:
        """Count cameras currently occupying a concurrency slot (must hold _lock)."""
        return sum(
            1 for r in self._cameras.values()
            if r.status in ("connecting", "connected", "streaming")
        )

    def _start_processor_locked(self, rt: CameraRuntime) -> None:
        """Instantiate and start an RTSPStreamProcessor for *rt* (must hold _lock).

        Assigns a fresh task_id (uuid4 hex) and session_id, wires the on_detection callback
        that stores detections attributed to this camera, and launches a watcher daemon thread
        that updates the camera status as the processor transitions through its states.

        Requirements: 12.5, 13.9
        """
        from video_processor import RTSPStreamProcessor
        from video_processor import format_plate_persian
        from db import save_detection

        detector, recognizer, opt = self._ensure_models()
        task_id = uuid.uuid4().hex
        session_id = start_session("rtsp", rt.url)

        camera_id = rt.camera_id
        camera_name = rt.name

        def on_det(src, text, conf, source_file, frame, ftime):
            """Persist a detection attributed to this camera. Requirements: 13.9"""
            save_detection(
                session_id, src, text, format_plate_persian(text), conf,
                source_file, frame, ftime,
                camera_id=camera_id, camera_name=camera_name,
            )

        processor = RTSPStreamProcessor(
            detector, recognizer, opt, rt.url,
            fast_mode=False, skip_frames=rt.skip_frames,
            on_detection=on_det,
        )
        processor.start()

        rt.task_id = task_id
        rt.session_id = session_id
        rt.processor = processor
        rt.status = "connecting"

        # Register in the global _tasks dict so the existing
        # /api/detect/rtsp/{task_id} status endpoint continues to work.
        try:
            import api as _api
            with _api._tasks_lock:
                _api._tasks[task_id] = {
                    "processor": processor,
                    "session_id": session_id,
                    "status": "running",
                    "url": rt.url,
                    "camera_id": camera_id,
                }
        except Exception:
            pass  # best-effort; the watcher + get_status still work without this

        # Daemon watcher thread: mirrors processor state → camera status,
        # promotes the queue when the processor stops or errors.
        watcher = threading.Thread(
            target=self._watch_processor, args=(camera_id,), daemon=True
        )
        watcher.start()

    def _watch_processor(self, camera_id: int) -> None:
        """Poll the processor every second and reflect its state on the CameraRuntime.

        When the processor stops or errors this method frees the slot and calls
        _promote_from_queue so the next queued camera can start.
        Requirements: 12.4, 12.9
        """
        import time

        _STATUS_MAP = {
            "connecting": "connecting",
            "connected": "connected",
            "streaming": "streaming",
        }

        while True:
            time.sleep(1)
            with self._lock:
                if camera_id not in self._cameras:
                    return
                rt = self._cameras[camera_id]
                if rt.processor is None:
                    return

                try:
                    state = rt.processor.get_state()
                except Exception:
                    # Processor became inaccessible — treat as error
                    state = {"status": "error: inaccessible"}

                proc_status: str = state.get("status", "unknown")

                if proc_status.startswith("error"):
                    # Error isolation: only this camera is affected (Req 12.4)
                    if rt.status not in ("stopped", "error"):
                        rt.status = "error"
                        if rt.session_id:
                            try:
                                history = state.get("history", [])
                                end_session(
                                    rt.session_id,
                                    0,
                                    len(history),
                                    len({p["dtrb_text"] for p in history}),
                                    status="error",
                                )
                            except Exception:
                                pass
                        rt.processor = None
                        self._promote_from_queue()
                    return

                if proc_status in ("done", "stopped"):
                    if rt.status not in ("stopped",):
                        rt.status = "stopped"
                    return

                # Map live processor status to camera status
                rt.status = _STATUS_MAP.get(proc_status, rt.status)

    def _stop_camera_locked(self, camera_id: int, end_sess: bool) -> None:
        """Stop the processor for *camera_id* and optionally close its session.

        Must be called while holding _lock.
        """
        rt = self._cameras.get(camera_id)
        if rt is None:
            return
        if rt.processor is not None:
            try:
                state = rt.processor.get_state()
                rt.processor.stop()
                if end_sess and rt.session_id:
                    history = state.get("history", [])
                    end_session(
                        rt.session_id,
                        0,
                        len(history),
                        len({p["dtrb_text"] for p in history}),
                    )
            except Exception:
                pass  # Error isolation: failure here must not cascade (Req 12.4)
            rt.processor = None
        rt.status = "stopped"
        rt.task_id = None
        rt.session_id = None

    def _promote_from_queue(self) -> None:
        """Start the earliest-queued camera whenever a concurrency slot is free.

        This is the single choke-point for FIFO promotion (Req 12.9). Must be called
        while holding _lock.
        """
        running = self._running_count()
        while running < self._concurrency_limit and self._queue:
            next_id = self._queue.popleft()
            if next_id not in self._cameras:
                continue  # Camera was removed while queued
            rt = self._cameras[next_id]
            if rt.status == "queued":
                try:
                    self._start_processor_locked(rt)
                    running += 1
                except Exception:
                    # Error isolation: a start failure must not block later queue entries
                    rt.status = "error"

    def _to_view(self, camera_id: int) -> dict:
        """Produce a serialisable view dict for a CameraRuntime (must hold _lock or be safe to read)."""
        rt = self._cameras.get(camera_id)
        if rt is None:
            return {}
        return {
            "id": rt.camera_id,
            "name": rt.name,
            "url": rt.url,
            "skip_frames": rt.skip_frames,
            "status": rt.status,
            "task_id": rt.task_id,
            "session_id": rt.session_id,
        }
