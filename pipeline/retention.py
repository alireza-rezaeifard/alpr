"""Unified bounded retention for generated emission requests and events.

One budget (``capacity`` slots) holds either an unfinalized request or a built
``VehicleEvent``. A reservation is taken before the lifecycle gate is consumed,
so no generated request can ever lack a place to live. Request-to-event
conversion reuses the same slot.

This store is deliberately synchronous and in-memory; it is not a crash-safe
spool. ``PENDING`` retries honor ``retry_interval_s``. Once
``retention_max_attempts`` is reached the slot becomes ``EXHAUSTED`` and is
retained read-only for diagnostics; it is not retried. ``CONFLICT`` is also
terminal. Both terminal states consume capacity until an operator/M1 workflow
releases or resolves them.

``EXHAUSTED`` covers two distinct exhaustion kinds: persistence exhaustion
(``recovery_attempts == 0``) and recovery exhaustion of a malformed REQUEST
(``recovery_attempts > 0``, capped by ``max_recovery_attempts``). The payload
and its Event identity are preserved in both cases; ``snapshot()`` reports
``recovery_exhausted`` separately so the two kinds remain distinguishable.
Repeated recovery failures never reset the slot's original ``state_since``
age, so a malformed request cannot postpone its own deadline forever.

Every reservation carries a generation. Slot mutations validate the generation,
so a stale token can never release or mutate a slot that has since been reused.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .types import EmissionRequest, VehicleEvent

FREE = "FREE"
RESERVED = "RESERVED"
REQUEST = "REQUEST"
PENDING = "PENDING"
EXHAUSTED = "EXHAUSTED"
CONFLICT = "CONFLICT"

# States whose payload must be preserved and never silently released.
TERMINAL_STATES = (EXHAUSTED, CONFLICT)


class StaleRetentionToken(RuntimeError):
    """Raised when a token no longer owns the slot it names."""


@dataclass(frozen=True)
class RetentionIntent:
    kind: str          # confirm | close
    track_key: str
    action: str
    status: str
    needs_review: bool
    reason: str
    event_uid: str | None = None

    def to_request(self) -> EmissionRequest:
        return EmissionRequest(
            track_key=self.track_key,
            action=self.action,
            status=self.status,
            needs_review=self.needs_review,
            reason=self.reason,
            event_uid=self.event_uid,
        )


@dataclass(frozen=True)
class RetentionToken:
    slot: int
    generation: int
    intent: RetentionIntent


@dataclass
class _Slot:
    state: str = FREE
    token: RetentionToken | None = None
    generation: int = 0
    request: EmissionRequest | None = None
    event: VehicleEvent | None = None
    attempts: int = 0
    last_attempt: float = 0.0
    state_since: float = 0.0
    last_error: str | None = None
    # Failed REQUEST-recovery attempts for the current reservation. Distinct
    # from ``attempts`` (persistence attempts) so diagnostics can tell the two
    # exhaustion kinds apart.
    recovery_attempts: int = 0


class UnifiedRetentionStore:
    """Bounded reservation/retention store shared by requests and events."""

    def __init__(self, capacity: int = 192, retry_interval_s: float = 5.0,
                 max_attempts: int = 3, recovery_timeout_s: float = 5.0,
                 max_recovery_attempts: int = 3) -> None:
        self.capacity = max(1, int(capacity))
        self.retry_interval_s = max(0.0, float(retry_interval_s))
        self.max_attempts = max(1, int(max_attempts))
        self.recovery_timeout_s = max(0.0, float(recovery_timeout_s))
        self.max_recovery_attempts = max(1, int(max_recovery_attempts))
        self._lock = threading.RLock()
        self._slots = [_Slot() for _ in range(self.capacity)]
        self._generation = 0
        self._stale_token_attempts = 0
        self._recovered_requests = 0
        self._released_reservations = 0
        self._recovery_errors = 0
        self._recovery_exhausted = 0

    # -- capacity / admission ------------------------------------------------
    def free(self) -> int:
        with self._lock:
            return sum(1 for s in self._slots if s.state == FREE)

    def count(self, *states: str) -> int:
        with self._lock:
            return sum(1 for s in self._slots if s.state in states)

    def reserve(self, kind: str, track_key: str, action: str, status: str,
                needs_review: bool, reason: str,
                event_uid: str | None = None) -> RetentionToken | None:
        intent = RetentionIntent(kind, track_key, action, status,
                                 needs_review, reason, event_uid)
        now = time.monotonic()
        with self._lock:
            for idx, slot in enumerate(self._slots):
                if slot.state == FREE:
                    self._generation += 1
                    token = RetentionToken(idx, self._generation, intent)
                    slot.state = RESERVED
                    slot.token = token
                    slot.generation = token.generation
                    slot.request = intent.to_request()
                    slot.event = None
                    slot.attempts = 0
                    slot.last_attempt = 0.0
                    slot.state_since = now
                    slot.last_error = None
                    return token
        return None

    def reserve_close(self, track_key: str, event_uid: str | None = None
                      ) -> RetentionToken | None:
        return self.reserve("close", track_key, "emit", "unconfirmed",
                            True, "force_at_close", event_uid=event_uid)

    # -- handoffs ------------------------------------------------------------
    def park_request(self, token: RetentionToken, request: EmissionRequest) -> None:
        with self._lock:
            slot = self._require_current(token)
            if slot.state not in (RESERVED, REQUEST):
                raise StaleRetentionToken(
                    f"cannot park request in state {slot.state}")
            slot.request = request
            self._set_state(slot, REQUEST)

    def convert(self, token: RetentionToken, event: VehicleEvent) -> None:
        with self._lock:
            slot = self._require_current(token)
            if slot.state not in (RESERVED, REQUEST):
                raise StaleRetentionToken(
                    f"cannot convert event in state {slot.state}")
            slot.event = event
            slot.request = None
            self._set_state(slot, PENDING)

    def request_for(self, token: RetentionToken) -> EmissionRequest:
        with self._lock:
            slot = self._require_current(token)
            return slot.request or token.intent.to_request()

    def payload(self, token: RetentionToken):
        with self._lock:
            slot = self._require_current(token)
            return slot.event or slot.request

    def has_payload(self, token: RetentionToken) -> bool:
        with self._lock:
            slot = self._require_current(token)
            return slot.event is not None or slot.request is not None

    def slot_state(self, token: RetentionToken) -> str:
        """Current state of the slot named by a current token.

        Raises ``StaleRetentionToken`` for a stale/released token, mirroring
        the other token-taking accessors. Callers use this to pick the correct
        transition (e.g. skip an already-done REQUEST→PENDING conversion)
        instead of suppressing conversion errors.
        """
        with self._lock:
            slot = self._require_current(token)
            return slot.state

    def release(self, token: RetentionToken) -> bool:
        """Release a current token.

        A stale or already-released token is a safe no-op. The attempt is
        counted so double release is observable without corrupting a reused
        slot.
        """
        with self._lock:
            if not self._is_current(token):
                self._stale_token_attempts += 1
                return False
            self._free_slot(self._slots[token.slot])
            return True

    # -- retry state ---------------------------------------------------------
    def mark_result(self, token: RetentionToken, outcome: str, detail=None) -> None:
        now = time.monotonic()
        with self._lock:
            slot = self._require_current(token)
            slot.last_attempt = now
            slot.last_error = None if outcome in ("created", "updated") else detail
            if outcome in ("created", "updated"):
                self._free_slot(slot)
            elif outcome == "identity_conflict":
                slot.attempts += 1
                self._set_state(slot, CONFLICT)
            else:
                slot.attempts += 1
                if slot.attempts >= self.max_attempts:
                    self._set_state(slot, EXHAUSTED)
                else:
                    self._set_state(slot, PENDING)

    def mark_unexpected_failure(self, token: RetentionToken, detail) -> None:
        """Keep recoverable work recoverable after an unexpected exception.

        A RESERVED slot has no lifecycle mutation under the admitted contract,
        so it is safe to release. A REQUEST or PENDING slot keeps its payload.

        The REQUEST recovery age (``state_since``) is deliberately preserved:
        a failed attempt must not postpone the recovery deadline, otherwise a
        persistently failing request would never age out (audit F-6).
        """
        with self._lock:
            if not self._is_current(token):
                self._stale_token_attempts += 1
                return
            slot = self._slots[token.slot]
            slot.last_error = str(detail)
            if slot.state == RESERVED:
                self._free_slot(slot)
            elif slot.state in (REQUEST, PENDING):
                slot.state = PENDING if slot.event is not None else REQUEST

    def note_recovery_failure(self, token: RetentionToken, detail) -> bool:
        """Record one failed REQUEST-recovery attempt (bounded, audit F-6).

        The attempt counter is per slot/generation and validated against the
        current token, so a stale token can never mutate a reused slot. The
        original recovery age (``state_since``) is preserved. After
        ``max_recovery_attempts`` failures the slot becomes ``EXHAUSTED``
        (recovery exhaustion) with its request payload and identity retained
        for diagnostics; it is never silently freed.

        Returns True when the slot transitioned to the terminal state.
        """
        with self._lock:
            if not self._is_current(token):
                self._stale_token_attempts += 1
                return False
            slot = self._slots[token.slot]
            slot.last_error = str(detail)
            if slot.state != REQUEST:
                return False
            slot.recovery_attempts += 1
            if slot.recovery_attempts >= self.max_recovery_attempts:
                self._set_state(slot, EXHAUSTED)
                self._recovery_exhausted += 1
                return True
            return False

    def due(self) -> list[RetentionToken]:
        """Return retryable PENDING tokens whose backoff has elapsed.

        ``EXHAUSTED`` and ``CONFLICT`` are terminal and deliberately excluded.
        ``REQUEST`` and ``RESERVED`` are not returned here; they use the
        dedicated recovery path so partially constructed work is not treated as
        a valid retry payload.
        """
        now = time.monotonic()
        with self._lock:
            out = []
            for slot in self._slots:
                if slot.token is None:
                    continue
                if (slot.state == PENDING
                        and now - slot.last_attempt >= self.retry_interval_s):
                    out.append(slot.token)
            return out

    def recoverable_requests(self, timeout_s: float | None = None
                             ) -> list[RetentionToken]:
        """Return parked REQUEST tokens older than the recovery timeout."""
        timeout = (self.recovery_timeout_s if timeout_s is None
                   else max(0.0, float(timeout_s)))
        now = time.monotonic()
        with self._lock:
            out = [slot.token for slot in self._slots
                   if slot.token is not None
                   and slot.state == REQUEST
                   and now - slot.state_since >= timeout]
            self._recovered_requests += len(out)
            return out

    def release_abandoned_reservations(self, timeout_s: float | None = None
                                       ) -> int:
        """Release RESERVED entries that never reached a lifecycle gate.

        Under the admitted contract, every terminal lifecycle transition parks
        its request first. A RESERVED slot older than the timeout therefore has
        no lifecycle mutation and no valid parked payload.
        """
        timeout = (self.recovery_timeout_s if timeout_s is None
                   else max(0.0, float(timeout_s)))
        now = time.monotonic()
        released = 0
        with self._lock:
            for slot in self._slots:
                if (slot.token is not None and slot.state == RESERVED
                        and now - slot.state_since >= timeout):
                    self._free_slot(slot)
                    released += 1
            self._released_reservations += released
        return released

    def note_recovery_error(self) -> None:
        with self._lock:
            self._recovery_errors += 1

    def conflicts(self) -> list[RetentionToken]:
        with self._lock:
            return [s.token for s in self._slots if s.state == CONFLICT and s.token]

    def has_due(self) -> bool:
        return bool(self.due())

    def recovery_exhausted(self) -> int:
        """Number of slots that reached EXHAUSTED through failed recoveries."""
        with self._lock:
            return self._recovery_exhausted

    def next_retry_delay(self) -> float:
        """Seconds until the next PENDING retry, or 0 when one is due now."""
        now = time.monotonic()
        with self._lock:
            delays = [max(0.0, self.retry_interval_s - (now - s.last_attempt))
                      for s in self._slots if s.state == PENDING]
            return min(delays) if delays else 0.0

    def progress_state(self) -> str:
        """Describe what can make progress without mutating payloads.

        free | due | backoff | recoverable | reserved | terminal
        """
        now = time.monotonic()
        with self._lock:
            if any(s.state == FREE for s in self._slots):
                return "free"
            if any(s.state == PENDING
                   and now - s.last_attempt >= self.retry_interval_s
                   for s in self._slots):
                return "due"
            if any(s.state == PENDING for s in self._slots):
                return "backoff"
            if any(s.state == REQUEST for s in self._slots):
                return "recoverable"
            if any(s.state == RESERVED for s in self._slots):
                return "reserved"
            return "terminal"

    def blocked(self) -> bool:
        """True only when no automatic progress path remains."""
        return self.progress_state() == "terminal"

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "capacity": self.capacity,
                "free": self.free(),
                "requests": self.count(RESERVED, REQUEST),
                "reserved": self.count(RESERVED),
                "stranded_requests": self.count(REQUEST),
                "pending": self.count(PENDING),
                "exhausted": self.count(EXHAUSTED),
                "conflicts": self.count(CONFLICT),
                "blocked": self.blocked(),
                "progress": self.progress_state(),
                "stale_token_attempts": self._stale_token_attempts,
                "recovered_requests": self._recovered_requests,
                "released_reservations": self._released_reservations,
                "recovery_errors": self._recovery_errors,
                "recovery_exhausted": self._recovery_exhausted,
            }

    # -- internals -----------------------------------------------------------
    def _is_current(self, token: RetentionToken) -> bool:
        if not isinstance(token, RetentionToken):
            return False
        if token.slot < 0 or token.slot >= self.capacity:
            return False
        slot = self._slots[token.slot]
        return (slot.token is not None
                and slot.token.generation == token.generation
                and slot.token.intent == token.intent
                and slot.generation == token.generation)

    def _require_current(self, token: RetentionToken) -> _Slot:
        if not self._is_current(token):
            self._stale_token_attempts += 1
            raise StaleRetentionToken("retention token is stale or released")
        return self._slots[token.slot]

    @staticmethod
    def _set_state(slot: _Slot, state: str) -> None:
        slot.state = state
        slot.state_since = time.monotonic()

    @staticmethod
    def _free_slot(slot: _Slot) -> None:
        slot.state = FREE
        slot.token = None
        slot.generation = 0
        slot.request = None
        slot.event = None
        slot.attempts = 0
        slot.last_attempt = 0.0
        slot.state_since = 0.0
        slot.last_error = None
        slot.recovery_attempts = 0
