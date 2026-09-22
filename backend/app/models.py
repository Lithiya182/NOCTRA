"""Pydantic schemas mirroring the frozen shared JSON contract."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Classification = Literal["industrial_fire", "agricultural_burn", "wildfire", "other"]
Severity = Literal["minor", "moderate", "severe", "extreme"]
Status = Literal["routine", "alert_triggered", "confirmed", "dismissed"]
FRPTrend = Literal["increasing", "decreasing", "stable", "insufficient_data"]
FRPIntensity = Literal["weak", "moderate", "high-moderate", "high", "very-high"]


class SiteOfInterest(BaseModel):
    site_id: str
    lat: float
    lon: float
    classification: Classification
    confidence: float
    explanation: str
    severity: Severity
    is_anomalous: bool
    status: Status
    first_seen: str
    last_seen: str


class SiteRow(BaseModel):
    site_id: str
    lat: float
    lon: float
    classification: Classification
    confidence: float
    explanation: str
    severity: Severity
    is_anomalous: bool
    status: Status
    first_seen: str
    last_seen: str
    max_frp: float = 0
    brightness: float = 0
    persistence: int = 0
    duty_cycle_pct: float = 0
    ml_prediction: Optional[str] = None
    is_synthetic: bool = True
    source: str = "synthetic"
    coverage_status: Optional[str] = None
    last_pass_date: Optional[str] = None
    days_since_last_pass: Optional[int] = None
    next_expected_pass_date: Optional[str] = None
    frp_mean: Optional[float] = None
    frp_std: Optional[float] = None
    frp_last: Optional[float] = None
    frp_trend: Optional[FRPTrend] = None
    detection_count: Optional[int] = None
    active_pass_count: Optional[int] = None
    days_span: Optional[int] = None
    expansion_magnitude: Optional[float] = None
    frp_intensity: Optional[FRPIntensity] = None


class AlertOut(BaseModel):
    id: int
    site_id: str
    severity: Severity
    is_anomalous: bool
    status: Status
    public_notified: Optional[bool] = None
    analyst_note: Optional[str] = None
    reviewed_by: Optional[str] = None
    created_at: str
    updated_at: str
    cap: Optional[dict] = None
    site: Optional[SiteRow] = None


class TransitionIn(BaseModel):
    action: Literal["confirm", "dismiss"]
    analyst_note: Optional[str] = Field(None, max_length=1000)
    reviewed_by: Optional[str] = Field("analyst", max_length=100)


class AlertReviewOut(BaseModel):
    id: int
    alert_id: int
    site_id: str
    action: str
    previous_status: Optional[str] = None
    new_status: str
    analyst_note: Optional[str] = None
    reviewed_by: str = "analyst"
    created_at: str


class PolygonOut(BaseModel):
    kind: str
    name: str
    ring: list[list[float]]


class NeedIn(BaseModel):
    kind: Literal["sos", "safe", "help"] = "help"
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude (-90 to 90)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude (-180 to 180)")
    message: str = Field("", max_length=1000, description="Message (max 1000 chars)")


class NeedOut(BaseModel):
    id: int
    kind: str
    lat: float
    lon: float
    message: str
    created_at: str


class PushSubscribeIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class RuntimeDetectionIn(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude (-90 to 90)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude (-180 to 180)")
    frp: float = Field(120.0, ge=0.0, description="FRP in MW (non-negative)")
    brightness: float = Field(360.0, ge=0.0, description="Brightness in Kelvin (non-negative)")


class IngestOut(BaseModel):
    detections: int
    sites: int
    passes: list[str] = Field(default_factory=list)
    polygons: int = 0
    alerts_created: int = 0