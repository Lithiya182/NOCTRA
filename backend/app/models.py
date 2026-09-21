"""Pydantic schemas mirroring the frozen shared JSON contract."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Classification = Literal["industrial_fire", "agricultural_burn", "wildfire", "other"]
Severity = Literal["minor", "moderate", "severe", "extreme"]
Status = Literal["routine", "alert_triggered", "confirmed", "dismissed"]


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


class AlertOut(BaseModel):
    id: int
    site_id: str
    severity: Severity
    is_anomalous: bool
    status: Status
    public_notified: Optional[bool] = None
    created_at: str
    updated_at: str
    cap: Optional[dict] = None
    site: Optional[SiteRow] = None


class TransitionIn(BaseModel):
    action: Literal["confirm", "dismiss"]


class PolygonOut(BaseModel):
    kind: str
    name: str
    ring: list[list[float]]


class NeedIn(BaseModel):
    kind: Literal["sos", "safe", "help"] = "help"
    lat: float
    lon: float
    message: str = ""


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
    lat: float
    lon: float
    frp: float = 120.0
    brightness: float = 360.0


class IngestOut(BaseModel):
    detections: int
    sites: int
    passes: list[str] = Field(default_factory=list)
    polygons: int = 0
    alerts_created: int = 0