"""NOCTRA Review Contract.

Mirrors the `alert_reviews` table plus reviewer_id (FK to reviewers table)
and structured override fields (corrected_class, corrected_severity).
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class ReviewContract(BaseModel):
    """Human review decision, operational audit trail, and structured overrides."""

    schema_version: str = Field(
        "1.0.0",
        description="Semantic version of this contract schema",
    )
    id: Optional[int] = Field(
        None,
        description="Primary key identifier in the alert_reviews database table",
    )
    alert_id: int = Field(
        ...,
        description="Foreign key to the alerts table (alerts.id)",
    )
    site_id: str = Field(
        ...,
        description="Site identifier associated with the review (sites.site_id)",
    )
    action: str = Field(
        ...,
        description="Review action taken: confirm | dismiss | feedback | note",
    )
    previous_status: Optional[str] = Field(
        None,
        description="Alert status prior to this review action",
    )
    new_status: str = Field(
        ...,
        description="Alert status following this review action",
    )
    analyst_note: Optional[str] = Field(
        None,
        description="Operational justification and qualitative field notes recorded by the reviewer",
    )
    reviewed_by: str = Field(
        ...,
        description="Name of the authenticated human reviewer (strictly resolved from token)",
    )
    feedback_label: Optional[str] = Field(
        None,
        description="Classification correctness feedback label: correct | incorrect",
    )
    created_at: str = Field(
        ...,
        description="ISO 8601 timestamp when this review action was committed",
    )

    # NOCTRA Extension Fields:
    reviewer_id: Optional[int] = Field(
        None,
        description="Foreign key identifier in reviewers table (reviewers.id)",
    )
    corrected_class: Optional[str] = Field(
        None,
        description="Structured override for fire classification: industrial_fire | agricultural_burn | wildfire | other",
    )
    corrected_severity: Optional[str] = Field(
        None,
        description="Structured override for severity tier: minor | moderate | severe | extreme",
    )
    stage_status: Optional[str] = Field(
        "partially_implemented",
        description="Stage status: audit review live; structured override fields unbuilt in UI/DB schema",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if hand-authored mock data for unbuilt fields",
    )
