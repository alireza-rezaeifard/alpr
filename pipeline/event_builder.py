"""Event identity and application-level idempotency (design §2.5, §3.2).

The event key is the durable identity of a vehicle visit. Format matches the
design exactly:

    event_key = f"{camera_id}:{session_epoch}:{local_track_id}"

and equals ``track_key`` — one track lifetime = one event. Idempotency is
enforced at the application layer first (``EventIdempotencyRegistry``):
a second ``emit()`` for the same key is refused and counted, so protection
does not depend on a DB UNIQUE constraint (which lands in Phase 3). The DB
UNIQUE index on ``event_key`` is the *second* line of defence, per §3.2.
"""
from __future__ import annotations

import threading

from .types import ConsensusResult, VehicleEvent

STATUS_CONFIRMED = "confirmed"
STATUS_UNCONFIRMED = "unconfirmed"


def make_event_key(camera_id, session_epoch: int, local_track_id: int) -> str:
    """Deterministic event key (§3.2 event_key, §2.3 camera scoping)."""
    return f"{camera_id}:{session_epoch}:{int(local_track_id)}"


def local_track_id_from_key(event_key: str) -> int:
    """Inverse of make_event_key (raises ValueError on malformed keys)."""
    try:
        return int(event_key.rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"malformed event_key: {event_key!r}") from exc


class EventIdempotencyRegistry:
    """Application-level duplicate suppression (§2.5 rule 2).

    Thread-safe. Remembers every emitted key and refuses repeats with
    ``double_emit_blocked`` semantics; ``invalidate_key`` supports processor
    restart inside a session epoch (Phase 1 hooks, no-op now).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._emitted: dict[str, int] = {}   # event_key -> emission count
        self._upgraded: dict[str, int] = {}  # event_key -> upgrade count

    def register_emission(self, event_key: str) -> bool:
        """True when this is the first emission; False when suppressed."""
        with self._lock:
            count = self._emitted.get(event_key, 0)
            self._emitted[event_key] = count + 1
            return count == 0

    def register_upgrade(self, event_key: str, max_upgrades: int) -> bool:
        """True when the upgrade slot is still free (§4.6 max_upgrades)."""
        with self._lock:
            count = self._upgraded.get(event_key, 0)
            if count >= max_upgrades:
                return False
            self._upgraded[event_key] = count + 1
            return True

    def is_emitted(self, event_key: str) -> bool:
        with self._lock:
            return self._emitted.get(event_key, 0) > 0

    def emission_count(self, event_key: str) -> int:
        with self._lock:
            return self._emitted.get(event_key, 0)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "keys_emitted": len(self._emitted),
                "keys_upgraded": len(self._upgraded),
                "total_emissions": sum(self._emitted.values()),
                "total_upgrades": sum(self._upgraded.values()),
            }

    def reset(self) -> None:
        with self._lock:
            self._emitted.clear()
            self._upgraded.clear()


def build_event(event_key: str, result: ConsensusResult, *, track_kind: str,
                first_seen: str, last_seen: str, frame_count: int,
                observation_count: int, duration_ms: int,
                plate_valid: bool, status: str = STATUS_CONFIRMED,
                needs_review: bool = False) -> VehicleEvent:
    """Assemble a VehicleEvent from a ConsensusResult (§3.2 field subset)."""
    plate_text = result.plate
    return VehicleEvent(
        event_key=event_key,
        track_id=event_key,
        track_kind=track_kind,
        first_seen=first_seen,
        last_seen=last_seen,
        plate_number=plate_text,
        plate_norm=plate_text.strip().lower(),
        confidence=result.confidence,
        agreement_ratio=result.agreement_ratio,
        quality_score=(result.best.weight if result.best else 0.0),
        frame_count=frame_count,
        observation_count=observation_count,
        duration_ms=duration_ms,
        status=status,
        needs_review=needs_review,
        char_confidences=list(result.char_conf),
        alternates=list(result.alternates),
        plate_valid=plate_valid,
    )
