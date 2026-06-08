"""Domain routers for the ANPR backend.

Each module defines a FastAPI ``APIRouter`` that is included by ``api.py``:
    auth, users, licenses, cameras, detection, scanner, watchlists, alerts,
    reports, export, audit, retention.
"""
