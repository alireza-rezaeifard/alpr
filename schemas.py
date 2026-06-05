"""
schemas.py
Pydantic request/response models for new and validated API endpoints.
Requirements: 11.1, 12.2, 14.7
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class CameraCreate(BaseModel):
    name: str = Field("", max_length=100)          # empty name allowed (Req 11.2)
    url: str
    skip_frames: int | None = Field(None, ge=1, le=1000)


class CameraUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    url: str | None = None
    skip_frames: int | None = Field(None, ge=1, le=1000)


class CameraView(BaseModel):
    id: int
    name: str
    url: str
    skip_frames: int
    status: str            # stopped|queued|connecting|connected|streaming|error
    task_id: str | None = None
    session_id: int | None = None


class StartResult(BaseModel):
    camera_id: int
    status: str            # running|queued|error
    task_id: str | None = None


class StopResult(BaseModel):
    status: str


class ConcurrencyConfig(BaseModel):
    value: int = Field(..., ge=1, le=64)           # Req 12.2/12.8


class ConcurrencyView(BaseModel):
    concurrency_limit: int


class PlateMetadataResponse(BaseModel):
    classified: bool
    category: str | None = None
    category_display: str | None = None
    color_scheme: str | None = None               # white|yellow|green|red|blue|black
    region_code: str | None = None
    region_name: str | None = None
    special_note: str | None = None
    reason: str | None = None
