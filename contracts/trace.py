"""NOCTRA Decision Trace Contract.

Ordered TraceStep(step_no, stage, summary, evidence_ref, timestamp) covering
all 12 stages of the frozen architecture, plus notification delivery audit.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    """Single stage execution step in the immutable 12-stage Decision Trace DAG."""

    step_no: int = Field(
        ...,
        ge=1,
        le=12,
        description="Step sequence number in the 12-stage pipeline (1 to 12)",
    )
    stage: str = Field(
        ...,
        description=(
            "Stage identifier: FIRMS_INGEST | SITE_FORMATION | THERMAL_DNA_OSM | "
            "CLASSIFICATION_RULE_AND_EBM | SEVERITY_AND_HYSTERESIS | "
            "CHANGE_DETECTION_EWMA_CUSUM | SENTINEL2_CORROBORATION | "
            "BAYESIAN_FUSION | ROUTING_AND_PRIORITY | HUMAN_REVIEW | "
            "TWILIO_DISPATCH | DECISION_TRACE"
        ),
    )
    summary: str = Field(
        ...,
        description="Concise description of the decision, state, or inference made at this stage",
    )
    evidence_ref: Optional[str] = Field(
        None,
        description="Reference identifier, column, or URI to supporting evidence artifact",
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 execution timestamp",
    )
    stage_status: Optional[str] = Field(
        None,
        description="Stage implementation status: live | unbuilt | shadow | experimental",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if step data is hand-authored mock data",
    )


class NotificationTrace(BaseModel):
    """Audit record for external notification dispatch (Twilio SMS / Push)."""

    message_sid: Optional[str] = Field(
        None,
        description="Twilio message SID (e.g. SM...) if dispatched, or null if held/not dispatched",
    )
    status: str = Field(
        ...,
        description="Dispatch state: not_dispatched | gated_awaiting_review | queued | sent | delivered | failed",
    )
    channel: str = Field(
        "sms",
        description="Notification delivery channel: sms | web_push | cap",
    )
    recipient: Optional[str] = Field(
        None,
        description="Masked recipient phone number or webhook target",
    )
    dispatched_at: Optional[str] = Field(
        None,
        description="ISO 8601 timestamp when dispatch was executed",
    )
    authorized_by: Optional[str] = Field(
        None,
        description="Name of the authenticated human reviewer who authorized dispatch",
    )
    stage_status: Optional[str] = Field(
        "live",
        description="Dispatch engine implementation status",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if mock record for demonstration",
    )


class DecisionTraceContract(BaseModel):
    """End-to-end Decision Trace contract capturing the complete immutable audit DAG."""

    schema_version: str = Field(
        "1.0.0",
        description="Semantic version of this contract schema",
    )
    trace_id: str = Field(
        ...,
        description="Unique identifier for this decision trace (e.g. TRACE-TG-23731-86324-001)",
    )
    site_id: str = Field(
        ...,
        description="Site identifier to which this trace pertains (sites.site_id)",
    )
    alert_id: Optional[int] = Field(
        None,
        description="Alert identifier (alerts.id) if an alert was triggered",
    )
    steps: List[TraceStep] = Field(
        ...,
        description="Ordered list of execution steps covering pipeline stages",
    )
    notification: NotificationTrace = Field(
        ...,
        description="Notification dispatch status and Twilio delivery audit record",
    )
    created_at: str = Field(
        ...,
        description="ISO 8601 timestamp when decision trace was initiated",
    )
    updated_at: str = Field(
        ...,
        description="ISO 8601 timestamp of most recent stage progression",
    )
