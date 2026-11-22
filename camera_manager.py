"""
camera_manager.py
CameraManager: manages concurrent RTSPStreamProcessor instances with a FIFO queue and
configurable concurrency limit. Thread-safe via RLock.
Requirements: 11.1, 11.4, 11.8, 12.1, 12.3, 12.4, 12.5, 12.6, 12.7, 12.9, 13.9
"""
from __future__ import annotations
import logging
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
from error_handler import (
    report_error, report_exception,
    ErrorCategory, ErrorSeverity,
)

logger = logging.getLogger(__name__)


class CameraShutdownIncomplete(RuntimeError):
    """Raised when a camera still owns a processor whose shutdown is incomplete.

    Remediation 4 (audit F-14): no replacement processor may be constructed or
    assigned while the retained processor's shutdown/flush is unverified, so
    ``_start_processor_locked`` refuses before any session, model, or
    task-registry work happens. The caller preserves the runtime so a later
    safe retry (watcher stop retries or ``stop_camera``) can complete the
    shutdown.
    """

    def __init__(self, camera_id: int):
        super().__init__(
            f"camera {camera_id}: retained processor shutdown incomplete; "
            "refusing to construct a replacement processor")
        self.camera_id = camera_id


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
    # Bounded stop retries the watcher may attempt while a processor's
    # shutdown is incomplete (audit F-4). Never reset to unbounded looping.
    shutdown_stop_attempts: int = 0


class CameraManager:
    def __init__(self, ensure_models_fn: Callable, tasks_registry: dict | None = None, tasks_lock=None):
        """
        :param ensure_models_fn: callable returning (detector, recognizer, opt) —
                                 used to lazy-load ML models when starting a processor.
        :param tasks_registry: reference to the global _tasks dict in api.py for task registration.
        :param tasks_lock: reference to the global _tasks_lock in api.py.
        """
        self._lock = threading.RLock()
        self._cameras: dict[int, CameraRuntime] = {}
        self._queue: deque[int] = deque()
        self._concurrency_limit: int = get_concurrency_limit()
        self._ensure_models = ensure_models_fn
        self._tasks_registry = tasks_registry
        self._tasks_lock = tasks_lock

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

    def remove_camera(self, camera_id: int) -> dict:
        """Stop any running processor, end the session, remove from queue and map, then delete from DB.

        Removal is conditional on verified shutdown completion (audit F-15):
        ``_stop_camera_locked`` retains the processor, its open session and all
        pending work when shutdown is incomplete, in which case the runtime and
        the DB camera row are NOT removed and the failure is reported
        explicitly. A later removal attempt can succeed once
        ``shutdown_completed()`` verifies termination and the final flush.

        Returns ``{'removed': bool, 'reason': str | None, 'camera_id': int}``
        (``reason`` is ``None`` on success, ``'not_found'`` for an unknown id,
        or ``'shutdown_incomplete'``).

        Requirements: 11.4, 11.8
        """
        with self._lock:
            if camera_id not in self._cameras:
                return {"removed": False, "reason": "not_found",
                        "camera_id": camera_id}
            self._stop_camera_locked(camera_id, end_sess=True)
            rt = self._cameras[camera_id]
            if rt.processor is not None:
                # _stop_camera_locked retained ownership: the shutdown is
                # incomplete. Do not delete the runtime or the DB record; keep
                # the exact processor object, session reference, and pending
                # work for a later safe retry.
                logger.warning(
                    "camera %s removal deferred: processor shutdown "
                    "incomplete; runtime, session and pending work retained",
                    camera_id)
                return {"removed": False, "reason": "shutdown_incomplete",
                        "camera_id": camera_id}
            # Remove from queue if present
            try:
                self._queue.remove(camera_id)
            except ValueError:
                pass
            del self._cameras[camera_id]
        delete_camera(camera_id)
        return {"removed": True, "reason": None, "camera_id": camera_id}

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
                try:
                    self._start_processor_locked(rt)
                except CameraShutdownIncomplete as exc:
                    # F-14: the retained processor keeps ownership (its
                    # shutdown is incomplete). Nothing was replaced; the
                    # failure is observable and a later safe retry (watcher
                    # stop retries or stop_camera) can complete the shutdown.
                    logger.warning(
                        "camera %s start refused: %s; runtime preserved for a "
                        "later safe retry", camera_id, exc)
                    return {"camera_id": camera_id, "status": "error",
                            "task_id": None, "error": "shutdown_incomplete"}
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

    def _shutdown_incomplete(self, processor) -> bool:
        """True when *processor* is retained but its shutdown is not verified
        complete (audit F-14).

        Uses the established authoritative shutdown contract
        (``shutdown_completed()``), never status strings or worker flags. An
        inaccessible processor is treated as incomplete (conservative).
        """
        if processor is None:
            return False
        try:
            return not bool(processor.shutdown_completed())
        except Exception:
            return True

    def _start_processor_locked(self, rt: CameraRuntime) -> None:
        """Instantiate and start an RTSPStreamProcessor for *rt* (must hold _lock).

        Assigns a fresh task_id (uuid4 hex) and session_id, wires the on_detection callback
        that stores detections attributed to this camera, and launches a watcher daemon thread
        that updates the camera status as the processor transitions through its states.

        Raises :class:`CameraShutdownIncomplete` — before ANY session, model, or
        task-registry work — when *rt* still owns a processor whose shutdown is
        incomplete (audit F-14). The caller must preserve the runtime for a
        later safe retry.

        Requirements: 12.5, 13.9
        """
        if self._shutdown_incomplete(rt.processor):
            # F-14: never overwrite a retained processor that has not verified
            # worker termination + final flush; doing so would abandon its
            # EventPipeline, pending retention work, and open session.
            raise CameraShutdownIncomplete(rt.camera_id)
        if rt.processor is not None and rt.session_id:
            # F-14: a retained processor with a VERIFIED complete shutdown must
            # not leak its open session when replaced. All in-repo completion
            # paths already finalize the session; this covers direct callers.
            try:
                state = rt.processor.get_state()
                history = state.get("history", [])
                end_session(
                    rt.session_id, 0, len(history),
                    len({p["dtrb_text"] for p in history}),
                )
            except Exception:
                pass  # error isolation: finalization failure must not block start
        from video_processor import RTSPStreamProcessor
        from video_processor import format_plate_persian
        from db import save_detection

        engine = self._ensure_models()
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
            engine, rt.url,
            fast_mode=False, skip_frames=rt.skip_frames,
            on_detection=on_det,
            camera_id=camera_id, camera_name=camera_name,
            session_id=session_id, source_file=rt.url,
        )
        processor.start()

        rt.task_id = task_id
        rt.session_id = session_id
        rt.processor = processor
        rt.status = "connecting"

        # Register in the global _tasks dict so the existing
        # /api/detect/rtsp/{task_id} status endpoint continues to work.
        if self._tasks_registry is not None and self._tasks_lock is not None:
            with self._tasks_lock:
                self._tasks_registry[task_id] = {
                    "processor": processor,
                    "session_id": session_id,
                    "status": "running",
                    "url": rt.url,
                    "camera_id": camera_id,
                }

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

        while True:
            time.sleep(1)

            # Get the processor reference while holding the manager lock briefly
            with self._lock:
                if camera_id not in self._cameras:
                    return
                rt = self._cameras[camera_id]
                if rt.processor is None:
                    return
                processor = rt.processor

            # Read processor status WITHOUT holding manager lock (avoids deadlock)
            try:
                with processor.lock:
                    proc_status = processor.status
            except Exception:
                proc_status = "error: inaccessible"

            # Now update the camera runtime status
            with self._lock:
                if camera_id not in self._cameras:
                    return
                rt = self._cameras[camera_id]

                if proc_status.startswith("error"):
                    keep_watching = self._handle_processor_error_locked(
                        rt, processor)
                    if not keep_watching:
                        return
                    # Incomplete shutdown: keep polling so a later successful
                    # stop (watcher retry or API) finishes the flush and the
                    # session closure. Never abandon the processor while
                    # workers/flushes are unresolved (audit F-4).
                    continue

                if proc_status in ("done", "stopped"):
                    if rt.status != "stopped":
                        rt.status = "stopped"
                    return

                # Direct status mapping
                if proc_status == "streaming":
                    rt.status = "streaming"
                elif proc_status == "connected":
                    rt.status = "connected"
                elif proc_status == "connecting" or proc_status == "initialized":
                    rt.status = "connecting"
                else:
                    rt.status = "streaming"  # Default to streaming if frames are flowing

    # Bounded number of stop attempts the watcher makes for one incomplete
    # shutdown before falling back to passive polling (audit F-4: no
    # unbounded stop loops).
    _MAX_SHUTDOWN_STOP_RETRIES = 3

    def _handle_processor_error_locked(self, rt: CameraRuntime,
                                       processor) -> bool:
        """Resolve an errored processor under the manager lock (audit F-4).

        Distinguishes a verified terminal error (workers terminated, final
        flush completed) from an incomplete shutdown such as
        ``error: shutdown timeout``. Incomplete shutdown NEVER abandons the
        processor or closes the session: up to ``_MAX_SHUTDOWN_STOP_RETRIES``
        bounded stop attempts are made here, after which ownership and the
        open session are retained and the watcher keeps polling so a later
        successful stop can finish the flush and the closure.

        Returns True when the watcher must keep polling; False when the
        processor lifecycle is fully resolved (session closed, reference
        released, queue promoted).
        """
        try:
            completed = bool(processor.shutdown_completed())
        except Exception:
            completed = False
        if (not completed
                and rt.shutdown_stop_attempts < self._MAX_SHUTDOWN_STOP_RETRIES):
            rt.shutdown_stop_attempts += 1
            try:
                processor.stop()
            except Exception:
                pass
            try:
                completed = bool(processor.shutdown_completed())
            except Exception:
                completed = False
        if not completed:
            # Keep the processor reference and the open session; free the
            # concurrency slot by marking the camera errored. Diagnostics
            # stay observable via the processor's own status/error fields.
            if rt.status != "error":
                rt.status = "error"
            return True
        # Verified shutdown: close the session, release the processor.
        if rt.status not in ("stopped", "error"):
            rt.status = "error"
        if rt.session_id:
            try:
                history = []
                with processor.lock:
                    history = list(processor.plate_history)
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
        rt.shutdown_stop_attempts = 0
        self._promote_from_queue()
        return False

    def _stop_camera_locked(self, camera_id: int, end_sess: bool) -> None:
        """Stop the processor for *camera_id* and optionally close its session.

        Must be called while holding _lock.
        """
        rt = self._cameras.get(camera_id)
        if rt is None:
            return
        if rt.processor is not None:
            try:
                rt.processor.stop()
                completed = bool(rt.processor.shutdown_completed())
            except Exception:
                completed = False
            if completed:
                if end_sess and rt.session_id:
                    try:
                        state = rt.processor.get_state()
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
                rt.shutdown_stop_attempts = 0
            else:
                # Incomplete shutdown (audit F-4): retain the processor
                # reference and the open session so the watcher (or a later
                # stop) can finish the flush and closure. Frees the
                # concurrency slot without discarding unflushed work.
                rt.status = "error"
                return
        rt.status = "stopped"
        rt.task_id = None
        rt.session_id = None
        rt.shutdown_stop_attempts = 0

    def _promote_from_queue(self) -> None:
        """Start the earliest-queued camera whenever a concurrency slot is free.

        This is the single choke-point for FIFO promotion (Req 12.9). Must be called
        while holding _lock.

        F-14: a queued camera that still owns an incompletely stopped processor
        is re-queued (queue membership preserved, no replacement constructed)
        and will be retried on the next promotion event after the watcher's
        bounded stop retries or a later stop complete the shutdown. No busy
        retry loop is introduced: promotion stays event-driven.
        """
        running = self._running_count()
        pending = list(self._queue)
        self._queue.clear()
        for next_id in pending:
            if running >= self._concurrency_limit:
                self._queue.append(next_id)
                continue
            if next_id not in self._cameras:
                continue  # Camera was removed while queued
            rt = self._cameras[next_id]
            if rt.status == "queued":
                try:
                    self._start_processor_locked(rt)
                    running += 1
                except CameraShutdownIncomplete:
                    # Ownership of the retained processor is preserved and the
                    # camera keeps its queue membership.
                    self._queue.append(next_id)
                except Exception as e:
                    # Error isolation: a start failure must not block later queue entries
                    report_exception(e, ErrorCategory.CAMERA,
                                     source=f"CameraManager.promote(cam={next_id})")
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
