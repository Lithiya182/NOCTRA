"""NOCTRA Event Contract.

Mirrors raw FIRMS/VIIRS detections, tracking event_id, site_id, detection refs,
observed_at, spatial/radiometric parameters, and rigorous provenance metadata.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class EventProvenance(BaseModel):
    """Provenance tracking for data integrity and auditability."""

    is_synthetic: int = Field(
        1,
        description="1 if synthetic seed data, 0 if genuine satellite telemetry",
    )
    source: str = Field(
        "synthetic",
        description="Data origin: synthetic | firms_real | viirs_noaa20",
    )
    ingestion_batch: Optional[str] = Field(
        None,
        description="Batch tag under which this detection was ingested (e.g. seed_20251110_20251114)",
    )


class EventContract(BaseModel):
    """Sensor observation event linking satellite telemetry to a formed site."""

    schema_version: str = Field(
        "1.0.0",
        description="Semantic version of this contract schema",
    )
    event_id: str = Field(
        ...,
        description="Unique event identifier (e.g. EVT-TG-23731-86324-001)",
    )
    site_id: str = Field(
        ...,
        description="Site identifier to which this event belongs (matches sites.site_id)",
    )
    detection_refs: List[int] = Field(
        default_factory=list,
        description="Database primary keys from the detections table contributing to this event",
    )
    observed_at: str = Field(
        ...,
        description="ISO 8601 acquisition timestamp (from acq_date and acq_time)",
    )
    latitude: Optional[float] = Field(
        None,
        description="Observation latitude coordinate",
    )
    longitude: Optional[float] = Field(
        None,
        description="Observation longitude coordinate",
    )
    frp: Optional[float] = Field(
        0.0,
        description="Fire Radiative Power (MW) recorded by VIIRS I-band sensor",
    )
    brightness: Optional[float] = Field(
        None,
        description="Brightness temperature in Kelvin (bright_ti4)",
    )
    bright_ti5: Optional[float] = Field(
        None,
        description="VIIRS I-5 thermal channel brightness temperature in Kelvin",
    )
    satellite: Optional[str] = Field(
        None,
        description="Satellite platform (e.g. NOAA-20, Suomi-NPP)",
    )
    instrument: Optional[str] = Field(
        None,
        description="Sensor instrument (e.g. VIIRS)",
    )
    daynight: Optional[str] = Field(
        None,
        description="D=Day pass, N=Night pass",
    )
    confidence: Optional[float] = Field(
        None,
        description="Sensor detection confidence percentage (0-100)",
    )
    provenance: EventProvenance = Field(
        default_factory=EventProvenance,
        description="Provenance tracking attributes",
    )
