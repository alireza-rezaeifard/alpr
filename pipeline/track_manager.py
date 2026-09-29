"""Track lifecycle state machine (design §2.4/§2.5).

States: NEW → TRACKING → PLATE_CAPTURED → CONFIRMED → COMPLETED / EXPIRED,
with LOST→resume handled by the tracker (§2.4 table). All transitions are
explicit methods; invalid transitions raise ``InvalidTransition``. Expiry is
monotonic-clock based so reconnects/restarts flush open tracks (§2.4 any→EXPIRED).

Owns ``Track`` records and the emission gate (EVENT_EMITTED flag + re-entry
cooldown lookup hook + fragmentation window, §2.5 rules 2-4). Emission
requests are handed to EventBuilder (Phase 1); persistence is NOT done here.
"""
from __future__ import annotations

import time

from .config import PipelineConfig
from .types import EmissionRequest, PlateRead, Track, TrackUpdate

NEW = "NEW"
TRACKING = "TRACKING"
PLATE_CAPTURED = "PLATE_CAPTURED"
CONFIRMED = "CONFIRMED"
COMPLETED = "COMPLETED"
EXPIRED = "EXPIRED"

_VALID_TRANSITIONS = {
    NEW: {TRACKING, EXPIRED},
    TRACKING: {TRACKING, PLATE_CAPTURED, COMPLETED, EXPIRED},
    PLATE_CAPTURED: {PLATE_CAPTURED, CONFIRMED, COMPLETED, EXPIRED},
    CONFIRMED: {CONFIRMED, COMPLETED, EXPIRED},
    COMPLETED: set(),
    EXPIRED: set(),
}


class InvalidTransition(Exception):
    """Raised when code requests a state transition outside §2.4."""


class TrackManager:
    """Owns lifecycle Tracks for one camera (§2.4, §2.5)."""

    def __init__(self, cfg: PipelineConfig | None = None,
                 clock=time.monotonic) -> None:
        self.cfg = cfg or PipelineConfig()
        self._clock = clock
        self._tracks: dict[str, Track] = {}
        # (plate_norm) -> last emission monotonic time, §2.5 rule 3.
        self._last_emit_by_plate: dict[str, float] = {}
        # Recently closed (plate_norm, track_key, close_ts, min_ts, max_ts).
        self._recently_closed: list[tuple[str, str, float, float, float]] = []
        self.tracks_rejected_new = 0
        self.tracks_dropped_no_evidence = 0
        self.fragments_absorbed = 0
        self.double_emit_blocked = 0

    # -- tracker input -------------------------------------------------
    def apply_updates(self, updates: list[TrackUpdate], now: float | None = None
                      ) -> list[EmissionRequest]:
        """Fold tracker output into lifecycle tracks; expire stale ones.

        Returns emission requests for tracks that completed/expired with
        evidence (§2.4 COMPLETED row). LOST updates keep the lifecycle state
        (tracker resumes it on re-association, §2.4 LOST→resumed).
        """
        now = self._clock() if now is None else now
        requests: list[EmissionRequest] = []
        seen: set[str] = set()
        for update in updates:
            seen.add(update.track_key)
            track = self._tracks.get(update.track_key)
            if track is None:
                track = Track(track_key=update.track_key, kind=update.kind,
                              state=NEW, first_ts=now, last_ts=now,
                              box=update.box)
                self._tracks[update.track_key] = track
            track.box = update.box
            track.last_ts = now
            if update.state == "TRACKED":
                track.hits = update.hits
                track.age = update.age
                track.time_since_update = 0
                if track.state == NEW and track.hits >= self.cfg.new_track_min_hits:
                    self._transition(track, TRACKING)
            else:  # LOST: hold lifecycle state, count the gap (§2.4)
                track.time_since_update = update.time_since_update
        # Tracks the tracker dropped entirely are treated as LOST here.
        for key, track in list(self._tracks.items()):
            if key not in seen and track.state not in (COMPLETED, EXPIRED):
                last = track.last_ts if track.last_ts is not None else now
                track.time_since_update = int((now - last) * self.cfg.effective_fps)
            if track.state in (COMPLETED, EXPIRED):
                continue
            if self._expired(track, now):
                requests.extend(self._close_track(track, now))
        return requests

    def attach_read(self, track_key: str, read: PlateRead,
                    now: float | None = None) -> EmissionRequest | None:
        """Store one PlateRead; returns an emission request when the read
        itself completes the evidence picture (caller still runs consensus)."""
        now = self._clock() if now is None else now
        track = self._tracks.get(track_key)
        if track is None or track.state in (COMPLETED, EXPIRED):
            return None
        track.observations.append(read)
        if len(track.observations) > self.cfg.max_track_obs:
            # Keep the best reads; drop the weakest (§5.8 ring policy).
            track.observations.sort(key=lambda r: r.weight)
            track.observations = track.observations[-self.cfg.max_track_obs:]
        track.last_ts = now
        if read.usable and track.state == TRACKING:
            self._transition(track, PLATE_CAPTURED)
        return None

    def mark_confirmed(self, track_key: str) -> EmissionRequest | None:
        """Consensus CONFIRM rule fired (§4.6): emit once, then CONFIRMED."""
        track = self._tracks.get(track_key)
        if track is None or track.state in (COMPLETED, EXPIRED):
            return None
        if track.event_emitted:
            self.double_emit_blocked += 1
            return None
        if track.state != CONFIRMED:
            self._transition(track, CONFIRMED)
        track.event_emitted = True
        return EmissionRequest(track_key=track_key, action="emit",
                               status="confirmed", reason="consensus_confirm")


    # -- expiry / close --------------------------------------------------
    def _expired(self, track: Track, now: float) -> bool:
        """True when a non-terminal track has been unseen too long (§2.4)."""
        import math
        expiry_frames = max(1, math.ceil(self.cfg.track_expiry_s
                                         * self.cfg.effective_fps))
        lifetime_ref = track.first_ts if track.first_ts is not None else now
        lifetime_ok = (now - lifetime_ref) >= self.cfg.track_min_lifetime_s
        return track.time_since_update > expiry_frames and (
            lifetime_ok or track.state == NEW
        )

    def _close_track(self, track: Track, now: float) -> list[EmissionRequest]:
        """COMPLETED path (§2.4): emit unconfirmed when evidence suffices."""
        usable = [r for r in track.observations if getattr(r, "usable", False)]
        if track.state == NEW:
            self.tracks_rejected_new += 1
            self._transition(track, EXPIRED)
            return []
        if track.event_emitted:
            self._transition(track, COMPLETED)
            return []
        if not usable:
            self.tracks_dropped_no_evidence += 1
            self._transition(track, COMPLETED)
            return []
        self._transition(track, COMPLETED)
        return [EmissionRequest(track_key=track.track_key, action="emit",
                                status="unconfirmed", needs_review=True,
                                reason="force_at_close")]

    def expire_all(self, reason: str = "shutdown") -> list[EmissionRequest]:
        """any → EXPIRED flush on stop/reconnect/exception (§2.4)."""
        requests: list[EmissionRequest] = []
        for track in self._tracks.values():
            if track.state in (COMPLETED, EXPIRED):
                continue
            usable = [r for r in track.observations if getattr(r, "usable", False)]
            self._transition(track, EXPIRED)
            if track.event_emitted or usable:
                status = "confirmed" if track.event_emitted else "unconfirmed"
                requests.append(EmissionRequest(
                    track_key=track.track_key, action="emit", status=status,
                    needs_review=not track.event_emitted, reason=reason))
            else:
                self.tracks_dropped_no_evidence += 1
        return requests

    # -- duplicate-prevention helpers (§2.5) -------------------------------
    def note_emission(self, plate_norm: str, track_key: str,
                      first_ts: float, last_ts: float,
                      now: float | None = None) -> str:
        """Record an emission; returns 'emit' or 'absorbed'.

        Fragmentation absorption (§2.5 rule 4): a second emission of the same
        plate within fragment_window_s whose track overlapped the previous
        window folds into the first event instead of creating a row.
        """
        now = self._clock() if now is None else now
        self._prune_closed(now)
        prior = self._last_emit_by_plate.get(plate_norm)
        if prior is not None and (now - prior) <= self.cfg.fragment_window_s:
            for norm, key, close_ts, lo, hi in self._recently_closed:
                if norm == plate_norm and not (last_ts < lo or first_ts > hi):
                    self.fragments_absorbed += 1
                    return "absorbed"
        self._last_emit_by_plate[plate_norm] = now
        self._recently_closed.append((plate_norm, track_key, now,
                                      first_ts, last_ts))
        return "emit"

    def in_reentry_cooldown(self, plate_norm: str,
                            now: float | None = None) -> bool:
        """Safety-net cooldown (§2.5 rule 3): absorb fragments, not visits."""
        now = self._clock() if now is None else now
        prior = self._last_emit_by_plate.get(plate_norm)
        return prior is not None and (now - prior) <= self.cfg.reentry_cooldown_s

    def _prune_closed(self, now: float) -> None:
        horizon = max(self.cfg.fragment_window_s, self.cfg.reentry_cooldown_s)
        self._recently_closed = [e for e in self._recently_closed
                                 if (now - e[2]) <= horizon + 1.0]

    def close_completed(self, track_key: str, plate_norm: str,
                        first_ts: float, last_ts: float,
                        now: float | None = None) -> None:
        """Register a COMPLETED track's window for absorption checks."""
        now = self._clock() if now is None else now
        self._recently_closed.append((plate_norm, track_key, now,
                                      first_ts, last_ts))
        self._prune_closed(now)

    # -- core transition ---------------------------------------------------
    def _transition(self, track: Track, new_state: str) -> None:
        allowed = _VALID_TRANSITIONS.get(track.state, set())
        if new_state != track.state and new_state not in allowed:
            raise InvalidTransition(f"{track.state} -> {new_state}")
        track.state = new_state

    # -- inspection ----------------------------------------------------------
    def get(self, track_key: str) -> Track | None:
        return self._tracks.get(track_key)

    def live_tracks(self) -> list[Track]:
        return [t for t in self._tracks.values()
                if t.state not in (COMPLETED, EXPIRED)]
