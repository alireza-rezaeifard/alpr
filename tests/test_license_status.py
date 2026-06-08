"""Unit tests for license status shape and no-license reachability (task 7.7).

Covers:
* Req 3.5 — ``get_license_status()`` returns the documented shape
  (``active``, ``expiry``, ``camera_limit``, ``configured_cameras``) both with no
  license and after activating a valid license.
* Req 3.7 — status logic works with no license present, and the auth/login,
  license-activate, and license-status routes are NOT license-gated (they omit
  the ``require_license`` dependency) so they stay reachable from a clean state.
"""
import importlib
import os
from datetime import date, timedelta

import pytest


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp file and reload the licensing service onto it."""
    os.environ["ANPR_SECRET_KEY"] = "test-secret-for-license-status"
    os.environ["ANPR_LICENSE_SECRET"] = "test-license-secret"
    import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    # Reload service + key modules so their module-level ``import db`` binds to
    # the patched DB_PATH for this test's connections.
    import licensing.license_key as license_key
    import licensing.service as service
    importlib.reload(license_key)
    importlib.reload(service)
    yield db, service, license_key
    os.environ.pop("ANPR_SECRET_KEY", None)
    os.environ.pop("ANPR_LICENSE_SECRET", None)


# ---------------------------------------------------------------------------
# Status shape with no license (Req 3.5, 3.7)
# ---------------------------------------------------------------------------

def test_status_shape_with_no_license(fresh_db):
    db, service, _ = fresh_db

    status = service.get_license_status()

    # Documented shape (Req 3.5): all four fields present.
    assert hasattr(status, "active")
    assert hasattr(status, "expiry")
    assert hasattr(status, "camera_limit")
    assert hasattr(status, "configured_cameras")

    # With no license the status logic still works (Req 3.7).
    assert status.active is False
    assert status.expiry is None
    assert status.camera_limit is None
    assert status.configured_cameras == 0


def test_status_configured_cameras_counts_cameras_with_no_license(fresh_db):
    db, service, _ = fresh_db

    db.create_camera("cam-1", "rtsp://example/1")
    db.create_camera("cam-2", "rtsp://example/2")

    status = service.get_license_status()

    # Status remains reachable and accurate without any license (Req 3.7).
    assert status.active is False
    assert status.camera_limit is None
    assert status.configured_cameras == 2


# ---------------------------------------------------------------------------
# Status shape after activating a valid license (Req 3.5)
# ---------------------------------------------------------------------------

def test_status_shape_after_activating_valid_license(fresh_db):
    db, service, license_key = fresh_db

    future_expiry = (date.today() + timedelta(days=365)).isoformat()
    key = license_key.encode_license_key(
        license_key.LicenseClaims(expiry=future_expiry, camera_limit=4)
    )

    service.activate_license(key)
    # Add one camera to verify the configured-camera count is reported.
    db.create_camera("cam-1", "rtsp://example/1")

    status = service.get_license_status()

    assert status.active is True
    assert status.expiry == future_expiry
    assert status.camera_limit == 4
    assert status.configured_cameras == 1


def test_status_inactive_when_license_expired(fresh_db):
    db, service, license_key = fresh_db

    past_expiry = (date.today() - timedelta(days=1)).isoformat()
    key = license_key.encode_license_key(
        license_key.LicenseClaims(expiry=past_expiry, camera_limit=2)
    )

    service.activate_license(key)
    status = service.get_license_status()

    # Expired: not active, but expiry/limit are still surfaced (Req 3.5).
    assert status.active is False
    assert status.expiry == past_expiry
    assert status.camera_limit == 2


# ---------------------------------------------------------------------------
# Reachability: auth/activate/status are not license-gated (Req 3.7)
# ---------------------------------------------------------------------------

def _dependency_calls(route):
    """Recursively collect every dependency ``.call`` for a FastAPI route."""
    calls = []
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return calls

    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            calls.append(dep.call)
        stack.extend(dep.dependencies)
    return calls


def _route_is_license_gated(route) -> bool:
    """True if any dependency of ``route`` is a ``require_license`` guard."""
    for call in _dependency_calls(route):
        qualname = getattr(call, "__qualname__", "")
        if "require_license" in qualname:
            return True
    return False


def _find_route(router, path_suffix: str, method: str):
    for route in router.routes:
        if route.path.endswith(path_suffix) and method in getattr(route, "methods", set()):
            return route
    raise AssertionError(f"route {method} ...{path_suffix} not found")


def test_license_routes_are_not_license_gated():
    from routers import licenses

    activate_route = _find_route(licenses.router, "/activate", "POST")
    status_route = _find_route(licenses.router, "/status", "GET")

    assert not _route_is_license_gated(activate_route)
    assert not _route_is_license_gated(status_route)


def test_login_route_is_not_license_gated():
    from routers import auth

    login_route = _find_route(auth.router, "/login", "POST")
    assert not _route_is_license_gated(login_route)
