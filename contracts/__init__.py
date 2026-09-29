"""NOCTRA Frozen Architecture Contracts.

Exports Pydantic v2 contracts for:
- SiteContract & ThermalDNA (contracts/site.py)
- EventContract & EventProvenance (contracts/event.py)
- EvidenceContract & Sub-stages (contracts/evidence.py)
- ReviewContract (contracts/review.py)
- DecisionTraceContract, TraceStep, & NotificationTrace (contracts/trace.py)
- DemoSiteBundle (comprehensive fixture container)
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from .site import SiteContract, ThermalDNA
from .event import EventContract, EventProvenance
from .evidence import (
    EvidenceContract,
    RuleClassificationEvidence,
    EBMShadowEvidence,
    SeverityEvidence,
    ChangeEvidence,
    SentinelEvidence,
    SignalLikelihoodRatio,
    FusionEvidence,
    RoutingEvidence,
)
from .review import ReviewContract
from .trace import DecisionTraceContract, TraceStep, NotificationTrace


class DemoSiteBundle(BaseModel):
    """Unified container for a complete demo site fixture encompassing all contracts."""

    schema_version: str = Field(
        "1.0.0",
        description="Semantic version of this bundle schema",
    )
    fixture_id: str = Field(
        ...,
        description="Fixture identifier (e.g. SITE-001, SITE-002)",
    )
    title: str = Field(
        ...,
        description="Human-readable title describing the scenario",
    )
    site: SiteContract
    event: EventContract
    evidence: EvidenceContract
    review: Optional[ReviewContract] = None
    trace: DecisionTraceContract


__all__ = [
    "SiteContract",
    "ThermalDNA",
    "EventContract",
    "EventProvenance",
    "EvidenceContract",
    "RuleClassificationEvidence",
    "EBMShadowEvidence",
    "SeverityEvidence",
    "ChangeEvidence",
    "SentinelEvidence",
    "SignalLikelihoodRatio",
    "FusionEvidence",
    "RoutingEvidence",
    "ReviewContract",
    "DecisionTraceContract",
    "TraceStep",
    "NotificationTrace",
    "DemoSiteBundle",
]
