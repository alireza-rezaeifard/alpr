"""
tests/test_audit_immutability.py
Unit tests for the append-only (immutable) audit log.

Requirement 15.5: The audit log is append-only — existing audit rows cannot be
modified or deleted through the service layer or the HTTP API. The only public
surface is:

    * an internal append path (``audit.service.write_audit``), and
    * a read path (``audit.service.list_audit`` / ``GET /api/audit``).

These tests assert that no modify/delete capability exists for existing audit
rows anywhere on the public surface:

    * The audit service module exposes no update/delete function.
    * The persistence layer (``db``) exposes no update/delete function for audit
      rows.
    * The audit router exposes no mutating (PUT/PATCH/DELETE/POST) routes — only
      read (GET).

Requirements: 15.5
"""
import audit.service as audit_service
import db
from routers.audit import router as audit_router


# ---------------------------------------------------------------------------
# Service layer: no update/delete function for audit rows
# ---------------------------------------------------------------------------
def test_audit_service_exposes_only_append_and_read():
    """The audit service exposes write_audit and list_audit and nothing that
    could modify or remove existing rows (Requirement 15.5)."""
    assert hasattr(audit_service, "write_audit")
    assert hasattr(audit_service, "list_audit")

    forbidden = (
        "update_audit",
        "edit_audit",
        "modify_audit",
        "delete_audit",
        "remove_audit",
        "clear_audit",
        "purge_audit",
    )
    for name in forbidden:
        assert not hasattr(audit_service, name), (
            f"audit.service must not expose '{name}' — audit log is append-only"
        )


def test_audit_service_callables_do_not_mutate_existing_rows():
    """No public callable on the audit service references SQL that would UPDATE
    or DELETE existing audit rows (Requirement 15.5)."""
    import inspect

    public_callables = [
        obj
        for name, obj in vars(audit_service).items()
        if not name.startswith("_") and inspect.isfunction(obj)
        and obj.__module__ == audit_service.__name__
    ]
    # write_audit and list_audit are the only public functions.
    names = sorted(fn.__name__ for fn in public_callables)
    assert names == ["list_audit", "write_audit"]

    for fn in public_callables:
        src = inspect.getsource(fn).upper()
        assert "UPDATE AUDIT_LOG" not in src, (
            f"{fn.__name__} must not UPDATE audit_log rows"
        )
        assert "DELETE FROM AUDIT_LOG" not in src, (
            f"{fn.__name__} must not DELETE audit_log rows"
        )


# ---------------------------------------------------------------------------
# Persistence layer: no update/delete helper for audit rows
# ---------------------------------------------------------------------------
def test_db_exposes_no_audit_update_or_delete_helper():
    """The db module exposes no helper to update or delete audit rows
    (Requirement 15.5)."""
    forbidden = (
        "update_audit",
        "delete_audit",
        "remove_audit",
        "clear_audit",
        "purge_audit",
    )
    for name in forbidden:
        assert not hasattr(db, name), (
            f"db must not expose '{name}' — audit log is append-only"
        )


# ---------------------------------------------------------------------------
# Router layer: no mutating endpoints, only read
# ---------------------------------------------------------------------------
def test_audit_router_exposes_no_mutating_endpoints():
    """The audit router offers no PUT/PATCH/DELETE/POST endpoint, so existing
    audit rows can never be modified or deleted via the API (Requirement
    15.5)."""
    mutating_methods = {"PUT", "PATCH", "DELETE", "POST"}
    for route in audit_router.routes:
        methods = set(getattr(route, "methods", set()) or set())
        offending = methods & mutating_methods
        assert not offending, (
            f"audit route {getattr(route, 'path', '?')} must not allow "
            f"{offending} — audit log is append-only"
        )


def test_audit_router_only_allows_read():
    """Every audit route is read-only (GET / HEAD) — confirming the API exposes
    only an append-internal/read surface (Requirement 15.5)."""
    allowed = {"GET", "HEAD", "OPTIONS"}
    assert audit_router.routes, "audit router should expose at least one route"
    for route in audit_router.routes:
        methods = set(getattr(route, "methods", set()) or set())
        assert methods, f"route {getattr(route, 'path', '?')} has no methods"
        assert methods <= allowed, (
            f"audit route {getattr(route, 'path', '?')} exposes non-read "
            f"methods {methods - allowed}"
        )
