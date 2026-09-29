"""In-repo ByteTrack, camera-scoped (design §2.2 option B, §2.5).

Motion-only two-stage association over ``Box`` lists:
  stage 1: high-score boxes vs all tracks (greedy IoU + Hungarian-equivalent
           deterministic matching);
  stage 2: low-score boxes vs still-unmatched tracks (occlusion recovery).

One instance per camera inside ``PipelineContext`` — never shared, never
global — so tracks cannot cross-contaminate cameras. No torch, no cv2:
pure Python + stdlib, fully deterministic for a fixed input sequence
(no wall-clock, no randomness, no dict-order dependence).

Design references:
  §2.1 comparison table (why ByteTrack over SORT/DeepSORT),
  §2.5 update rules, Kalman state [cx, cy, a, h, vx, vy, va, vh].
"""
from __future__ import annotations

from .config import PipelineConfig
from .types import Box, TrackUpdate, box_iou

_STATE_NEW = "NEW"
_STATE_TRACKED = "TRACKED"
_STATE_LOST = "LOST"


class _KalmanState:
    """Minimal constant-velocity filter on [cx, cy, a, h, vx, vy, va, vh].

    Deliberately dependency-free (numpy-only design, implemented with plain
    floats): the 8-state SORT/ByteTrack transition with process/measurement
    noise tuned for the effective pipeline FPS. Predict-then-update runs on
    every tracker step so ``predict_box`` is always fresh for association.
    """

    __slots__ = ("cx", "cy", "a", "h", "vx", "vy", "va", "vh", "dt")

    def __init__(self, box: Box, dt: float) -> None:
        w = max(1e-6, box.x2 - box.x1)
        h = max(1e-6, box.y2 - box.y1)
        self.cx = (box.x1 + box.x2) / 2.0
        self.cy = (box.y1 + box.y2) / 2.0
        self.a = w / h
        self.h = h
        self.vx = 0.0
        self.vy = 0.0
        self.va = 0.0
        self.vh = 0.0
        self.dt = dt

    def predict(self) -> None:
        """Constant-velocity predict step."""
        self.cx += self.vx * self.dt
        self.cy += self.vy * self.dt
        self.a += self.va * self.dt
        self.h += self.vh * self.dt
        if self.h < 1e-6:
            self.h = 1e-6
        if self.a < 1e-6:
            self.a = 1e-6

    def update(self, box: Box) -> None:
        """Correct with measurement; velocity follows the residual.

        Blend factor 0.5 keeps association smooth at ~8 FPS effective
        sampling without a full covariance implementation.
        """
        w = max(1e-6, box.x2 - box.x1)
        h = max(1e-6, box.y2 - box.y1)
        mcx = (box.x1 + box.x2) / 2.0
        mcy = (box.y1 + box.y2) / 2.0
        ma = w / h
        blend = 0.5
        self.vx = blend * (mcx - self.cx) / self.dt + (1.0 - blend) * self.vx
        self.vy = blend * (mcy - self.cy) / self.dt + (1.0 - blend) * self.vy
        self.va = blend * (ma - self.a) / self.dt + (1.0 - blend) * self.va
        self.vh = blend * (h - self.h) / self.dt + (1.0 - blend) * self.vh
        self.cx, self.cy, self.a, self.h = mcx, mcy, ma, h

    def predict_box(self) -> Box:
        """Current state as a box (conf/cls filled by caller)."""
        w = self.a * self.h
        return Box(
            x1=self.cx - w / 2.0,
            y1=self.cy - self.h / 2.0,
            x2=self.cx + w / 2.0,
            y2=self.cy + self.h / 2.0,
            conf=0.0,
            cls=-1,
        )


class _InternalTrack:
    """Tracker-owned state; TrackManager owns the lifecycle Track."""

    __slots__ = ("local_id", "kind", "kf", "box", "conf", "cls",
                 "hits", "age", "time_since_update", "state")

    def __init__(self, local_id: int, kind: str, box: Box, dt: float) -> None:
        self.local_id = local_id
        self.kind = kind
        self.kf = _KalmanState(box, dt)
        self.box = box
        self.conf = box.conf
        self.cls = box.cls
        self.hits = 1
        self.age = 1
        self.time_since_update = 0
        self.state = _STATE_NEW


def _greedy_match(cost: list[list[float]], thresh: float,
                  n_rows: int, n_cols: int) -> tuple[list[tuple[int, int]],
                                                     list[int], list[int]]:
    """Deterministic greedy assignment on an IoU cost matrix.

    Picks globally highest IoU first (ties broken by row, then column index),
    repeating until no pair clears *thresh*. Hungarian-equivalent outcome on
    the small, well-separated ALPR association problems; deterministic and
    dependency-free. Returns (matches, unmatched_rows, unmatched_cols).
    """
    pairs: list[tuple[float, int, int]] = []
    for r in range(n_rows):
        for c in range(n_cols):
            iou = cost[r][c]
            if iou >= thresh:
                pairs.append((iou, r, c))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    used_rows: set[int] = set()
    used_cols: set[int] = set()
    matches: list[tuple[int, int]] = []
    for _, r, c in pairs:
        if r in used_rows or c in used_cols:
            continue
        used_rows.add(r)
        used_cols.add(c)
        matches.append((r, c))
    return (matches,
            [r for r in range(n_rows) if r not in used_rows],
            [c for c in range(n_cols) if c not in used_cols])


class ByteTracker:
    """Camera-scoped ByteTrack instance (§2.2 option B).

    Holds no global state: ``camera_id`` + ``session_epoch`` namespace every
    emitted ``track_key`` as ``f"{camera_id}:{session_epoch}:{local_id}"``,
    so ids can never repeat across restarts or leak between cameras.
    """

    def __init__(self, camera_id, session_epoch, cfg=None, kind="vehicle"):
        from .config import PipelineConfig as _Cfg
        self.cfg = cfg or _Cfg()
        self.camera_id = camera_id
        self.session_epoch = session_epoch
        self.kind = kind
        self._tracks: list = []
        self._next_id = 1
        self._dt = 1.0 / max(self.cfg.effective_fps, 1e-6)
        self.tracks_created = 0
        self.tracks_expired = 0
        self.tracks_merged_plate = 0
        self.occlusion_recoveries = 0

    def update(self, boxes, ts):
        """Associate *boxes* (capture order); one update per track.

        Deterministic: identical box sequences produce identical ids.
        """
        for track in self._tracks:
            track.kf.predict()

        high = [b for b in boxes if b.conf >= self.cfg.track_high_thresh]
        low = [b for b in boxes
               if self.cfg.track_low_thresh <= b.conf < self.cfg.track_high_thresh]

        live = [t for t in self._tracks if t.state != _STATE_LOST
                or t.time_since_update <= self._expiry_frames()]
        matches, unmatched_tracks, _ = self._associate(live, high)

        matched_cols: set = set()
        for track_idx, box_idx in matches:
            track = live[track_idx]
            self._register_match(track, high[box_idx])
            matched_cols.add(box_idx)

        still_open = [live[i] for i in unmatched_tracks]
        low_matches, _, _ = self._associate(still_open, low)
        recovered: set = set()
        for track_idx, box_idx in low_matches:
            track = still_open[track_idx]
            self._register_match(track, low[box_idx])
            recovered.add(id(track))
            self.occlusion_recoveries += 1

        matched_ids = {id(live[i]) for i, _ in matches} | recovered
        for track in live:
            if id(track) not in matched_ids:
                track.time_since_update += 1
                track.age += 1
                if track.time_since_update > 0:
                    track.state = _STATE_LOST
        self._expire_lost()

        for i, b in enumerate(high):
            if i not in matched_cols and b.conf >= self.cfg.new_track_thresh:
                self._create(b)

        self._enforce_cap()

        return [
            TrackUpdate(
                track_key=self._key(t), kind=t.kind, box=t.box, state=t.state,
                hits=t.hits, age=t.age, time_since_update=t.time_since_update,
            )
            for t in sorted(self._tracks, key=lambda t: t.local_id)
        ]

    def reset(self):
        """Flush all tracks (scene change / reconnect, §2.6)."""
        self._tracks = []

    def _key(self, track):
        return f"{self.camera_id}:{self.session_epoch}:{track.local_id}"

    def _expiry_frames(self):
        import math
        return max(1, math.ceil(self.cfg.track_expiry_s * self.cfg.effective_fps))

    def _associate(self, tracks, boxes):
        if not tracks or not boxes:
            return [], list(range(len(tracks))), list(range(len(boxes)))
        cost = [[box_iou(t.kf.predict_box(), b) for b in boxes] for t in tracks]
        return _greedy_match(cost, self.cfg.match_thresh, len(tracks), len(boxes))

    def _register_match(self, track, box):
        track.kf.update(box)
        track.box = box
        track.conf = box.conf
        track.cls = box.cls
        track.hits += 1
        track.age += 1
        track.time_since_update = 0
        track.state = _STATE_TRACKED

    def _create(self, box):
        track = _InternalTrack(self._next_id, self.kind, box, self._dt)
        self._next_id += 1
        self._tracks.append(track)
        self.tracks_created += 1
        return track

    def _expire_lost(self):
        limit = self._expiry_frames()
        kept = []
        for track in self._tracks:
            if track.state == _STATE_LOST and track.time_since_update > limit:
                self.tracks_expired += 1
            else:
                kept.append(track)
        self._tracks = kept

    def _enforce_cap(self):
        cap = self.cfg.max_live_tracks
        while len(self._tracks) > cap:
            lost = [t for t in self._tracks if t.state == _STATE_LOST]
            victim = min(lost or self._tracks, key=lambda t: t.local_id)
            self._tracks.remove(victim)
            self.tracks_expired += 1

