"""
export/csv_export.py
Pure CSV export builder for detection records.

Transforms detection rows into CSV format with:
- Fixed header: timestamp, source type, DTRB text, Persian plate, confidence
- Dynamic camera-name column when any row is camera-sourced (Requirement 14.3)
- Header-only output for empty result sets (Requirement 14.4)

The ``build_detection_csv`` function is pure: it reads detection dicts and
produces a CSV string. No database access, no side effects.

Requirements: 14.1, 14.2, 14.3, 14.4
"""
from __future__ import annotations
import csv
import io


def build_detection_csv(rows: list[dict]) -> str:
    """Build a CSV string from detection records (pure function).

    Parameters
    ----------
    rows : list[dict]
        Detection records, each with ``timestamp``, ``source_type``,
        ``plate_dtrb``, ``plate_persian``, ``confidence``, and optionally
        ``camera_name`` (when source_type is "camera" or "rtsp").

    Returns
    -------
    str
        CSV content with fixed columns (timestamp, source_type, plate_dtrb,
        plate_persian, confidence) plus a camera_name column when any row
        has ``camera_name`` populated. Empty result sets yield a header-only
        CSV (Requirement 14.4).

    Requirements
    ------------
    - 14.1: Fixed header columns for timestamp, source_type, DTRB text,
      Persian plate, and confidence.
    - 14.2: All matching detection records are included.
    - 14.3: Camera-name column is added when any row is camera-sourced.
    - 14.4: Empty result sets produce a file containing only the header.
    """
    # Step 1: Determine whether any row has a camera name (Requirement 14.3)
    has_camera_name = any(
        row.get("camera_name") is not None and row.get("camera_name") != ""
        for row in rows
    )

    # Step 2: Build the fixed header (Requirement 14.1)
    header = ["timestamp", "source_type", "plate_dtrb", "plate_persian", "confidence"]
    if has_camera_name:
        header.append("camera_name")

    # Step 3: Write rows to CSV in-memory (Requirement 14.2, 14.4)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=header, extrasaction="ignore")
    writer.writeheader()

    for row in rows:
        # Build the row dict with only the fields in the header
        csv_row = {
            "timestamp": row.get("timestamp", ""),
            "source_type": row.get("source_type", ""),
            "plate_dtrb": row.get("plate_dtrb", ""),
            "plate_persian": row.get("plate_persian", ""),
            "confidence": row.get("confidence", ""),
        }
        if has_camera_name:
            csv_row["camera_name"] = row.get("camera_name", "")
        writer.writerow(csv_row)

    return output.getvalue()
