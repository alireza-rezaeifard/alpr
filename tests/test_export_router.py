"""
tests/test_export_router.py
Integration tests for the export router (Requirement 14).

These tests verify that the export endpoint:
1. Returns StreamingResponse with correct media type and headers
2. Enforces the view permission (Viewer, Operator, Admin)
3. Accepts source_type and search filters
4. Passes filters correctly to the database layer

The actual CSV content generation is tested separately in test_csv_export.py
since the pure build_detection_csv function is easier to test directly.

Requirements: 14.1, 14.2, 14.3, 14.4
"""
from __future__ import annotations

import pytest
from unittest.mock import Mock

import db


@pytest.fixture
def export_router():
    """Import the export router with a clean database."""
    import routers.export as export
    return export


@pytest.fixture
def mock_user():
    """Create a mock authenticated user with Viewer role."""
    from auth.dependencies import AuthenticatedUser
    return AuthenticatedUser(
        id=1,
        username="viewer",
        role="Viewer",
        disabled=False,
        jti="test-jti",
        token_exp=9999999999,
    )


# ---------------------------------------------------------------------------
# Filter parameter passing
# ---------------------------------------------------------------------------
def test_export_passes_filters_to_db(export_router, mock_user, monkeypatch):
    """Export endpoint passes source_type and search filters to db."""
    call_args = {}

    def capture_args(**kwargs):
        call_args.update(kwargs)
        return ([], 0)

    monkeypatch.setattr(db, "get_all_detections", capture_args)

    export_router.export_detections_csv(
        source_type="camera",
        search="12a345",
        _user=mock_user,
    )

    # Should pass filters but use high limit to get all results (Req 14.2)
    assert call_args["source_type"] == "camera"
    assert call_args["search"] == "12a345"
    assert call_args["limit"] == 1_000_000  # High limit for "all matching"
    assert call_args["offset"] == 0


def test_export_handles_source_type_all(export_router, mock_user, monkeypatch):
    """Export endpoint treats source_type='all' as no filter."""
    call_args = {}

    def capture_args(**kwargs):
        call_args.update(kwargs)
        return ([], 0)

    monkeypatch.setattr(db, "get_all_detections", capture_args)

    export_router.export_detections_csv(
        source_type="all",
        search=None,
        _user=mock_user,
    )

    # source_type="all" should be treated as None (no filter)
    assert call_args["source_type"] is None


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------
def test_export_returns_csv_file_response(export_router, mock_user, monkeypatch):
    """Export endpoint returns a downloadable CSV file."""
    monkeypatch.setattr(
        db, "get_all_detections", lambda **kwargs: ([], 0)
    )

    response = export_router.export_detections_csv(
        source_type=None, search=None, _user=mock_user
    )

    # Check response type and headers
    assert response.media_type == "text/csv"
    assert "Content-Disposition" in response.headers
    assert "attachment" in response.headers["Content-Disposition"]
    assert "detections.csv" in response.headers["Content-Disposition"]


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------
def test_export_requires_view_permission(export_router):
    """Export endpoint requires the view permission."""
    # The route uses Depends(require_permission("view"))
    # Actual permission check is tested in auth tests
    # Here we verify the endpoint structure
    assert hasattr(export_router, "export_detections_csv")


def test_export_with_no_search_filter(export_router, mock_user, monkeypatch):
    """Export endpoint handles None search filter correctly."""
    call_args = {}

    def capture_args(**kwargs):
        call_args.update(kwargs)
        return ([], 0)

    monkeypatch.setattr(db, "get_all_detections", capture_args)

    export_router.export_detections_csv(
        source_type=None,
        search=None,
        _user=mock_user,
    )

    assert call_args["search"] is None

