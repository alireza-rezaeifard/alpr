"""Phase 1 integration: tracker + lifecycle + consensus + event persistence.

Wiring for one source (one camera / one uploaded video) as the design's §1.1
describes. The existing per-frame inference loop stays exactly where it is;
after each frame's ``AlprResult`` list is produced, this object

  1. converts pixel boxes to normalized ``Box`` objects,
  2. feeds vehicle boxes to the camera-scoped ``ByteTracker``,
  3. folds the ``TrackUpdate``s into the ``TrackManager`` lifecycle,
  4. attaches each plate reading to the vehicle track whose box contains it
     (containment-first, §5.4), with a separate plate-kind tracker for plates
     that have no vehicle box (§2.3 fallback), and
  5. runs the pure consensus engine per track and finalizes at most ONE event
     per track lifetime (§4.6 stopping rules), persisted through
     ``db.persist_event`` whose UNIQUE(event_key) is the durable
     idempotency boundary (§3.2).

No second inference loop, no new model calls: when the feature flag is off,
nothing here is constructed.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime

from .config import PipelineConfig
from .consensus import FORCE, UPGRADE, decide, is_usable, observation_weight, update
from .event_builder import EventIdempotencyRegistry, build_event
from .metrics import PipelineMetrics
from .retention import PENDING, REQUEST, UnifiedRetentionStore
from .tracker import ByteTracker
from .track_manager import TrackManager
from .types import (Box, EmissionRequest, PlateRead, TrackUpdate, VehicleEvent,
                    containment_iou)

from plate_validator import validate_iranian_plate

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat()


class EventPipeline:
    """Per-source event pipeline state — one instance per processor, never
    shared, so tracker / lifecycle / idempotency / cooldown state is fully
    isolated across cameras and threads (task §4). The internal lock is an
    ``RLock`` because ``process_results`` (ML worker thread) and ``expire``
    (stop path) may both touch the stats counters.
    """

    def __init__(self, source_type: str, camera_id=None, camera_name: str | None = None,
                 session_id: int | None = None, source_file: str | None = None,
                 source_instance_id: str | int | None = None,
                 cfg: PipelineConfig | None = None,
                 metrics: PipelineMetrics | None = None) -> None:
        self.cfg = cfg or PipelineConfig()
        self.source_type = source_type
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.session_id = session_id
        self.source_file = source_file
        # Approved identity contract: managed sources use sessions.id; direct
        # processors get a unique run instance so keys never collapse to :0:.
        if session_id is not None:
            self.source_instance_id = session_id
        elif source_instance_id is not None:
            self.source_instance_id = source_instance_id
        else:
            self.source_instance_id = uuid.uuid4().hex
        self.scope = f"camera:{camera_id}" if camera_id is not None else f"{source_type}:file"
        self.metrics = metrics
        tracker_ns = camera_id if camera_id is not None else source_type
        self._tracker = ByteTracker(tracker_ns, session_epoch=self.source_instance_id,
                                    cfg=self.cfg, kind="vehicle")
        # Plate-kind tracker (§2.3 fallback) gets its own namespace so its
        # local ids can never collide with vehicle-track ids.
        self._plate_tracker = ByteTracker(f"{tracker_ns}:plate",
                                          session_epoch=self.source_instance_id,
                                          cfg=self.cfg, kind="plate")
        self._lifecycle = TrackManager(self.cfg)
        self._registry = EventIdempotencyRegistry()
        self._retention = UnifiedRetentionStore(
            capacity=self.cfg.retention_capacity,
            retry_interval_s=self.cfg.retention_retry_interval_s,
            max_attempts=self.cfg.retention_max_attempts,
            recovery_timeout_s=self.cfg.retention_recovery_timeout_s,
            max_recovery_attempts=self.cfg.retention_max_recovery_attempts,
        )
        self._lock = threading.RLock()
        # wall-clock first_seen per track key (deterministic output field).
        self._first_seen_iso: dict[str, str] = {}
        self._stats = {
            "frames_processed": 0,
            "ocr_observations": 0,
            "observations_accepted": 0,
            "observations_rejected": 0,
            "events_finalized": 0,
            "duplicate_finalizations_suppressed": 0,
            "invalid_or_unknown_outcomes": 0,
            "persist_failures": 0,
            "identity_conflicts": 0,
            "pending_retried": 0,
            "retention_paused_frames": 0,
            "finalization_reasons": {},
        }

    # ------------------------------------------------------------------
    # main entry, called from the existing inference loop
    # ------------------------------------------------------------------
    def process_results(self, frame_idx: int, frame_width: int, frame_height: int,
                        results: list, now: float | None = None) -> list[VehicleEvent]:
        """Fold one frame's ``AlprResult`` list into the pipeline.

        Returns the VehicleEvents finalized by this call (usually empty; at
        most one per track, only when a §4.6 stopping rule fired).
        """
        now = _now_mono() if now is None else now
        self.drain_retention()
        vehicle_boxes: list[Box] = []
        plate_reads: list[tuple[PlateRead, str]] = []

        for r in results or []:
            raw_vehicle = getattr(r, "vehicle_boxes", None) or []
            vehicle_bbox = None
            if raw_vehicle:
                vx1, vy1, vx2, vy2 = raw_vehicle[0]
                vehicle_bbox = Box(vx1 / frame_width, vy1 / frame_height,
                                   vx2 / frame_width, vy2 / frame_height,
                                   conf=1.0, cls=2)
                vehicle_boxes.append(vehicle_bbox)
            if not r.plate_text:
                continue
            px1, py1, px2, py2 = r.plate_bbox
            plate_box = Box(px1 / frame_width, py1 / frame_height,
                            px2 / frame_width, py2 / frame_height,
                            conf=float(getattr(r, "plate_det_conf", 0.0)), cls=0)
            read = PlateRead(
                frame_idx=frame_idx,
                ts=_now_iso(),
                text=r.plate_text,
                # One ranked candidate per position (the argmax text). The char
                # detector interface is unchanged; runner-up candidates need a
                # small _assemble_chars extension, deferred to Phase 2.
                char_candidates=[[(ch, 1.0)] for ch in r.plate_text],
                char_count=len(r.plate_text),
                plate_det_conf=float(getattr(r, "plate_det_conf", 0.0)),
                plate_area_px=max(1, (px2 - px1) * (py2 - py1)),
                aspect_ratio=(px2 - px1) / max(1e-6, float(py2 - py1)),
                sharpness=0.0,
                brightness_ok=True,   # §4.3 gate needs crop stats — Phase 2
                usable=False,         # set by the quality gate below
                weight=0.0,
                bbox=plate_box,
                vehicle_bbox=vehicle_bbox,
            )
            usable, reason = is_usable(read, self.cfg)
            read.usable = usable
            if usable:
                read.weight = observation_weight(read, self.cfg)
                self._bump("observations_accepted")
            else:
                self._bump("observations_rejected")
            self._bump("ocr_observations")
            plate_reads.append((read, reason))

        with self._lock:
            self._stats["frames_processed"] += 1
            if self._retention.free() <= 0:
                self._stats["retention_paused_frames"] += 1
                return []
            return self._process_locked(frame_idx, vehicle_boxes, plate_reads, now)

    # ------------------------------------------------------------------
    def _process_locked(self, frame_idx: int, vehicle_boxes: list[Box],
                        plate_reads: list, now: float) -> list[VehicleEvent]:
        updates = self._tracker.update(vehicle_boxes, now)

        # Containment-first assignment (§5.4): a plate belongs to the vehicle
        # track whose box contains its vehicle-matched box.
        assigned: dict[str, list[PlateRead]] = {}
        unassigned: list[PlateRead] = []
        for read, _reason in plate_reads:
            best_key, best_score = None, 0.0
            if read.vehicle_bbox is not None:
                for u in updates:
                    if u.kind != "vehicle":
                        continue
                    score = _containment(read.vehicle_bbox, u.box)
                    if score > best_score:
                        best_score, best_key = score, u.track_key
            if best_key is not None:
                assigned.setdefault(best_key, []).append(read)
            else:
                unassigned.append(read)

        # Plate-only fallback tracker (§2.3): keeps identity for plates whose
        # vehicle box is missing, using the plate box itself. Runs every frame
        # (with an empty list when nothing is unassigned) so its tracks age
        # and expire like vehicle tracks — no state leak.
        plate_boxes = [r.bbox for r in unassigned if r.bbox is not None]
        plate_updates = self._plate_tracker.update(plate_boxes, now)
        for u in plate_updates:
            updates.append(u)
        plate_by_box = {id(u.box): u.track_key for u in plate_updates}
        still_unassigned: list[PlateRead] = []
        for read in unassigned:
            key = plate_by_box.get(id(read.bbox)) if read.bbox is not None else None
            if key is not None:
                assigned.setdefault(key, []).append(read)
            else:
                still_unassigned.append(read)
        unassigned = still_unassigned

        requests, request_tokens = self._lifecycle.apply_updates_admitted(
            updates, now, self._retention)

        # Record wall-clock first_seen for newly seen tracks (deterministic
        # event field; monotonic time drives all lifecycle decisions).
        for u in updates:
            if u.track_key not in self._first_seen_iso:
                self._first_seen_iso[u.track_key] = _now_iso()

        finalized: list[VehicleEvent] = []
        for key in list(assigned.keys()):
            for read in assigned[key]:
                self._lifecycle.attach_read(key, read, now)
            finalized.extend(self._evaluate_track(key, now))

        for request, token in zip(requests, request_tokens):
            # Associate the token with the exact lifecycle request before any
            # finalization work; the store, not a caller-local list, owns it.
            self._retention.park_request(token, request)
            event = self._finalize(request, now, closing=True, token=token)
            if event is not None:
                finalized.append(event)
        return finalized

    # ------------------------------------------------------------------
    # consensus evaluation per track (§4.6, closing=False branch)
    # ------------------------------------------------------------------
    def _evaluate_track(self, track_key: str, now: float) -> list[VehicleEvent]:
        track = self._lifecycle.get(track_key)
        if track is None or track.state in ("COMPLETED", "EXPIRED"):
            return []
        reads = track.observations
        if not reads:
            return []
        result, _action = update(reads, self.cfg, closing=False,
                                 already_emitted=track.event_emitted,
                                 upgrades=0, plate_valid=False)
        if result is None:
            return []
        validation = self._validate_result(result)
        usable_count = sum(1 for r in reads if r.usable
                           and r.weight >= self.cfg.min_obs_weight)
        char_mean = (sum(result.char_conf) / len(result.char_conf)
                     if result.char_conf else 0.0)
        best_quality = result.best.weight if result.best else 0.0
        action = decide(
            usable_obs=usable_count,
            length_mode_weight=result.length_mode_weight,
            agreement_ratio_value=result.agreement_ratio,
            char_mean=char_mean,
            plate_valid=validation.is_valid,
            quality=best_quality,
            already_emitted=track.event_emitted,
            upgrades=0,
            best_quality=best_quality,
            closing=False,
            cfg=self.cfg,
        )
        if action == "CONFIRM":
            token = self._retention.reserve(
                "confirm", track_key, "emit", "confirmed", False,
                "consensus_confirm", event_uid=track.event_uid)
            if token is None:
                return []
            try:
                request = self._lifecycle.mark_confirmed(
                    track_key, self._retention, token)
            except BaseException:
                current = self._lifecycle.get(track_key)
                if current is None or not current.event_emitted:
                    self._retention.release(token)
                raise
            if request is None:
                self._retention.release(token)
                return []
            event = self._finalize(request, now, closing=False, token=token)
            if event is not None:
                return [event]
        # UPGRADE/HOLD: the single persisted row is refreshed at close time by
        # the idempotent upsert; no second event is ever created (§6).
        return []

    # ------------------------------------------------------------------
    def _validate_result(self, result) -> object:
        """Pass the consensus text through the unchanged plate validator —
        consensus never validates (§4.5 step 4). Never raises."""
        text = result.plate if result is not None else ""
        conf = float(getattr(result, "confidence", 0.0) or 0.0)
        return validate_iranian_plate(text, conf)

    # ------------------------------------------------------------------
    # finalization — at most one event per track lifetime (§6)
    # ------------------------------------------------------------------
    def _finalize(self, request, now: float, closing: bool,
                  token=None) -> VehicleEvent | None:
        if token is None:
            raise ValueError("_finalize requires a retained request token")
        try:
            return self._finalize_impl(request, now, closing, token)
        except Exception as exc:
            logger.exception(
                "finalization exception event_key=%s event_uid=%s",
                request.track_key, getattr(request, "event_uid", None))
            self._retention.mark_unexpected_failure(token, exc)
            raise

    def _finalize_impl(self, request, now: float, closing: bool,
                       token) -> VehicleEvent | None:
        track = self._lifecycle.get(request.track_key)
        if track is None:
            self._retention.release(token)
            return None
        reads = track.observations
        if not reads:
            self._bump("invalid_or_unknown_outcomes")
            self._retention.release(token)
            return None
        result, action = update(reads, self.cfg, closing=True,
                                already_emitted=track.event_emitted,
                                upgrades=0, plate_valid=False)
        if result is None or not result.plate:
            # Track expired without a usable consensus: no plate is fabricated,
            # no successful event is created (task §5 rejection policy).
            self._bump("invalid_or_unknown_outcomes")
            self._retention.release(token)
            return None
        if action == "SUPPRESS":
            # Consensus says the evidence is too weak even at close time
            # (below force_emit_posterior) — rejection, not a weak event.
            self._bump("invalid_or_unknown_outcomes")
            self._retention.release(token)
            return None

        if self._registry.is_emitted(request.track_key):
            # App-level duplicate suppression (§2.5 rule 2) — counted, silent.
            self._bump("duplicate_finalizations_suppressed")
            self._retention.release(token)
            return None

        validation = self._validate_result(result)
        first_seen = self._first_seen_iso.get(request.track_key) or _now_iso()
        event_uid = track.event_uid or request.event_uid
        if not event_uid:
            event_uid = str(uuid.uuid4())
            track.event_uid = event_uid

        event = build_event(
            event_key=request.track_key,
            result=result,
            track_kind=track.kind,
            first_seen=first_seen,
            last_seen=_now_iso(),
            frame_count=track.hits,
            observation_count=len(track.observations),
            duration_ms=int(max(0.0, now - (track.first_ts or now)) * 1000),
            plate_valid=validation.is_valid,
            status=request.status or "confirmed",
            needs_review=request.needs_review or not validation.is_valid,
            event_uid=event_uid,
        )
        event.source_type = self.source_type
        event.camera_id = self.camera_id
        event.camera_name = self.camera_name
        event.session_id = self.session_id
        event.source_file = self.source_file
        event.finalize_reason = request.reason or action.lower()

        # Fragmentation absorption (§2.5 rule 4) — safety net, not identity.
        decision = self._lifecycle.note_emission(
            event.plate_norm, track_key=track.track_key,
            first_ts=track.first_ts or now, last_ts=now, now=now,
        )
        if decision == "absorbed":
            self._bump("duplicate_finalizations_suppressed")
            self._retention.release(token)
            return None

        outcome = self._persist(event, token)
        if outcome in ("created", "updated"):
            self._commit_success(event, token, outcome)
            return event
        return None

    def _commit_success(self, event: VehicleEvent, token, outcome: str) -> None:
        """Apply exactly-once post-persistence bookkeeping.

        The row is already durable here. A bookkeeping failure must not make the
        caller treat the event as unpersisted; release the slot first, then make
        registry/metrics updates best-effort with a critical log.
        """
        if token is not None:
            self._retention.release(token)
        try:
            self._registry.register_emission(event.event_key)
            self._bump("events_finalized")
            reason = getattr(event, "finalize_reason", None) or "unknown"
            with self._lock:
                reasons = self._stats["finalization_reasons"]
                reasons[reason] = reasons.get(reason, 0) + 1
            if self.metrics is not None:
                self.metrics.inc(
                    self.scope,
                    "events_persisted" if outcome == "created" else "events_upserted",
                )
        except Exception:
            logger.exception(
                "post-persistence bookkeeping failed event_uid=%s event_key=%s",
                event.event_uid, event.event_key,
            )

    def _persist(self, event: VehicleEvent, token=None) -> str:
        """Persist and route the outcome through the retention slot.

        Success deliberately does not release the token here: the caller runs
        _commit_success so normal and retry paths share one exactly-once
        bookkeeping route. Failure keeps the exact Event object in the slot.
        """
        outcome = "persist_failure"
        detail = None
        try:
            from db import persist_event
            result = persist_event(event)
            outcome = getattr(result, "outcome", "persist_failure")
            detail = getattr(result, "detail", None)
        except Exception as exc:  # import failure or an unhandled DB boundary
            detail = str(exc)
            logger.critical(
                "persistence exception event_uid=%s event_key=%s: %s",
                event.event_uid, event.event_key, exc,
            )

        if outcome in ("created", "updated"):
            return outcome

        if token is not None:
            # Route the failure through the correct transition. A first
            # failure on a freshly parked REQUEST converts the slot to
            # PENDING exactly once; a retry of an already-converted PENDING
            # slot must NOT convert again — convert() rejects PENDING by
            # design, and only the attempt bookkeeping (attempts,
            # last_attempt/backoff, exhaustion) has to advance (audit F-1).
            if self._retention.slot_state(token) == PENDING:
                self._retention.mark_result(token, outcome, detail)
            else:
                self._retention.convert(token, event)
                self._retention.mark_result(token, outcome, detail)
        if outcome == "identity_conflict":
            self._bump("identity_conflicts")
            logger.critical(
                "identity conflict event_uid=%s event_key=%s detail=%s",
                event.event_uid, event.event_key, detail)
        else:
            self._bump("persist_failures")
            logger.warning(
                "persist failure event_uid=%s event_key=%s detail=%s",
                event.event_uid, event.event_key, detail)
        return outcome

    def drain_retention(self) -> None:
        """Recover stranded work, then retry all currently due slots."""
        with self._lock:
            self._recover_retention_locked()
            for token in self._retention.due():
                try:
                    payload = self._retention.payload(token)
                    if payload is None:
                        self._retention.release(token)
                        continue
                    self._bump("pending_retried")
                    if isinstance(payload, VehicleEvent):
                        outcome = self._persist(payload, token)
                        if outcome in ("created", "updated"):
                            self._commit_success(payload, token, outcome)
                    else:
                        self._finalize(payload, _now_mono(), closing=True,
                                       token=token)
                except Exception:
                    logger.exception(
                        "retention retry failed slot=%s", token.slot)

    def _recover_retention_locked(self) -> list[VehicleEvent]:
        """Recover parked requests; abandon only dead pre-mutation reservations.

        Ordinary recovery keeps the configured age threshold. The verified
        end-of-source boundary uses ``_final_recovery_locked`` (zero-age
        recovery; audit F-5). Recovery failures are bounded by the store's
        recovery-attempt policy (audit F-6): repeated failures of one slot
        eventually terminate it instead of retrying forever.
        """
        self._retention.release_abandoned_reservations()
        return self._recover_pass(
            self._retention.recoverable_requests())

    def _recover_pass(self, tokens) -> list[VehicleEvent]:
        """Finalize one batch of recovered REQUEST tokens."""
        finalized: list[VehicleEvent] = []
        for token in tokens:
            try:
                payload = self._retention.payload(token)
                if not isinstance(payload, EmissionRequest):
                    continue
                event = self._finalize(payload, _now_mono(), closing=True,
                                       token=token)
                if event is not None:
                    finalized.append(event)
            except Exception as exc:
                # Bounded per audit F-6: repeated failures of the same slot
                # eventually reach the terminal state instead of looping.
                self._retention.note_recovery_failure(token, exc)
                self._retention.note_recovery_error()
                logger.exception(
                    "retention request recovery failed slot=%s", token.slot)
        return finalized

    def _final_recovery_locked(self) -> list[VehicleEvent]:
        """Zero-age recovery pass at a verified end-of-source boundary.

        Releases provably abandoned pre-mutation RESERVED slots (see
        ``_recover_retention_locked`` for the safety argument), then runs
        bounded recovery passes until no recoverable REQUEST remains (or the
        recovery-attempt policy terminates the malformed ones), and reports
        any still-stranded REQUEST slots. PENDING retries are NOT forced
        early: their configured backoff is preserved.
        """
        self._retention.release_abandoned_reservations(timeout_s=0.0)
        finalized: list[VehicleEvent] = []
        for _ in range(self._retention.max_recovery_attempts):
            tokens = self._retention.recoverable_requests(timeout_s=0.0)
            if not tokens:
                break
            finalized.extend(self._recover_pass(tokens))
        stranded = self._retention.count(REQUEST)
        if stranded:
            logger.critical(
                "final recovery left %d stranded REQUEST slot(s); payload "
                "retained for diagnostics", stranded)
        return finalized

    def retention_progress_state(self) -> str:
        """Store progress category for file-source backpressure."""
        return self._retention.progress_state()

    def retention_next_retry_delay(self) -> float:
        """Seconds until the next automatic retry/recovery can progress."""
        return self._retention.next_retry_delay()

    def retention_free(self) -> int:
        """Available retention slots (used by file-source backpressure)."""
        return self._retention.free()

    def retention_has_due(self) -> bool:
        """True when a retry is currently eligible (used by pause loops)."""
        return self._retention.has_due()

    def retention_blocked(self) -> bool:
        """True when capacity is full and no pending retry can make progress."""
        return self._retention.blocked()

    def retention_snapshot(self) -> dict:
        """Bounded operator-facing retention diagnostics."""
        return self._retention.snapshot()

    # ------------------------------------------------------------------
    # lifecycle flush on stop / reconnect (§2.4 any→EXPIRED)
    # ------------------------------------------------------------------
    def expire(self, reason: str = "shutdown") -> list[VehicleEvent]:
        self.drain_retention()
        with self._lock:
            finalized: list[VehicleEvent] = []
            requests, tokens = self._lifecycle.expire_all_admitted(
                reason, self._retention)
            for request, token in zip(requests, tokens):
                try:
                    self._retention.park_request(token, request)
                    event = self._finalize(
                        request, _now_mono(), closing=True, token=token)
                except Exception:
                    logger.exception(
                        "shutdown finalization failed track=%s reason=%s",
                        request.track_key, reason)
                    continue
                if event is not None:
                    finalized.append(event)
                else:
                    logger.critical(
                        "shutdown flush retained/undelivered request or event "
                        "track=%s reason=%s", request.track_key, reason)
            if self._lifecycle.live_tracks():
                # Tracks that could not reserve a slot remain non-terminal and
                # are recoverable for a later expire()/drain cycle.
                self._bump("retention_blocked")
                logger.critical(
                    "shutdown flush blocked: %d track(s) still require "
                    "retention capacity (free=%d, conflicts=%d, exhausted=%d)",
                    len(self._lifecycle.live_tracks()),
                    self._retention.free(),
                    self._retention.snapshot().get("conflicts", 0),
                    self._retention.snapshot().get("exhausted", 0),
                )
            else:
                self._tracker.reset()
                self._plate_tracker.reset()
                self._first_seen_iso.clear()
            # Verified end-of-source boundary (audit F-5): recover REQUEST
            # slots with a zero-age threshold so work stranded inside the
            # recovery window is finalized with its original identity instead
            # of being silently discarded with the pipeline object.
            finalized.extend(self._final_recovery_locked())
            return finalized

    def note_track_seen(self, track_key: str) -> None:
        """Record the wall-clock first_seen of a track (deterministic field)."""
        with self._lock:
            self._first_seen_iso.setdefault(track_key, _now_iso())

    # ------------------------------------------------------------------
    # observability — bounded-cardinality labels only (task §8)
    # ------------------------------------------------------------------
    def _bump(self, name: str) -> None:
        with self._lock:
            self._stats[name] = self._stats.get(name, 0) + 1
        if self.metrics is not None:
            self.metrics.inc(self.scope, name)

    def get_metrics(self) -> dict:
        """Snapshot without plate text or track ids as labels (task §8)."""
        with self._lock:
            stats = dict(self._stats)
            stats["finalization_reasons"] = dict(self._stats["finalization_reasons"])
        stats["active_tracks"] = len(self._lifecycle.live_tracks())
        stats["tracks_created"] = self._tracker.tracks_created
        stats["tracks_expired"] = self._tracker.tracks_expired
        stats["occlusion_recoveries"] = self._tracker.occlusion_recoveries
        stats["tracks_rejected_new"] = self._lifecycle.tracks_rejected_new
        stats["tracks_dropped_no_evidence"] = self._lifecycle.tracks_dropped_no_evidence
        stats["fragments_absorbed"] = self._lifecycle.fragments_absorbed
        stats["registry"] = self._registry.snapshot()
        stats["retention"] = self._retention.snapshot()
        accepted = stats.get("observations_accepted", 0)
        stats["track_to_event_ratio"] = round(
            stats["events_finalized"] / accepted, 4) if accepted else 0.0
        return stats


def _containment(inner: Box, outer: Box) -> float:
    return containment_iou(inner, outer)


def _now_mono() -> float:
    import time
    return time.monotonic()


__all__ = ["EventPipeline"]
