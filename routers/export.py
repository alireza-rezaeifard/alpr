"""
routers/export.py
Detection export API: produce downloadable CSV files of detection records.

Provides ``GET /api/export/detections`` which accepts the same source-type and
search filters as the detection list endpoint (``GET /api/detections``) and
returns a CSV file with:
- Fixed header: timestamp, source_type, plate_dtrb, plate_persian, confidence
- Dynamic camera_name column when any result row is camera-sourced (Req 14.3)
- Header-only file for empty result sets (Requirement 14.4)

The endpoint is guarded by ``require_permission("view")`` so any authenticated
role (Admin, Operator, or Viewer) can export (Requirement 2.7). The CSV builder
is pure and isolated in ``export.csv_export``.

Requirements: 14.1, 14.2, 14.3, 14.4
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from auth.dependencies import AuthenticatedUser, require_permission
from export.csv_export import build_detection_csv
import db
import io

router = APIRouter(prefix="/api/export", tags=["export"])


# ---------------------------------------------------------------------------
# GET /api/export/detections — CSV export with filters (Requirements 14.1-14.4)
# ---------------------------------------------------------------------------
@router.get("/detections")
def export_detections_csv(
    source_type: str | None = Query(None, description="Filter by source type: image, video, camera, rtsp, or all"),
    search: str | None = Query(None, description="Search term for plate_dtrb or plate_persian"),
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> StreamingResponse:
    """Export detection records as a downloadable CSV file.

    Accepts the same ``source_type`` and ``search`` filters as the detection
    list endpoint. The resulting CSV contains:
    - Fixed columns: timestamp, source_type, plate_dtrb, plate_persian, confidence
    - Camera_name column when any row is camera-sourced (Requirement 14.3)
    - Header-only output for empty result sets (Requirement 14.4)

    The response is a ``text/csv`` file with a ``Content-Disposition`` header
    prompting download.

    Requirements
    ------------
    - 14.1: Fixed header columns (timestamp, source_type, DTRB text, Persian
      plate, confidence).
    - 14.2: All matching detections are included (no pagination limit).
    - 14.3: Camera-name column is added when any row has a camera name.
    - 14.4: Empty result sets produce a header-only file.
    """
    # Step 1: Load detection records with the same filters as the detection list
    # We use a very high limit to get all matching records (Requirement 14.2)
    rows, _total = db.get_all_detections(
        limit=1_000_000,
        offset=0,
        source_type=source_type if source_type and source_type != "all" else None,
        search=search,
    )

    # Step 2: Build CSV content (pure function, Requirements 14.1-14.4)
    csv_content = build_detection_csv(rows)

    # Step 3: Return as a downloadable file
    output = io.BytesIO(csv_content.encode("utf-8"))
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=detections.csv"
        },
    )
