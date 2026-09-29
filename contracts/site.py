"""NOCTRA Site Contract.

Mirrors the `sites` database table with the addition of the Thermal DNA profile
(typical/median FRP, variability, typical frequency, active hours, typical duration, history days).
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class ThermalDNA(BaseModel):
    """Thermal behavioral fingerprint and baseline characteristics for a site."""

    typical_frp: Optional[float] = Field(
        None,
        description="Typical / median FRP in MW observed across passes",
    )
    median_frp: Optional[float] = Field(
        None,
        description="Median FRP value in MW across historical passes",
    )
    variability: Optional[float] = Field(
        None,
        description="FRP dispersion / variability (standard deviation or IQR in MW)",
    )
    typical_frequency: Optional[float] = Field(
        None,
        description="Typical detection frequency (detections per pass or passes per week)",
    )
    active_hours: Optional[List[int]] = Field(
        None,
        description="Typical UTC active acquisition hours (e.g. [1, 2, 13, 14])",
    )
    typical_duration: Optional[float] = Field(
        None,
        description="Typical thermal cluster persistence duration in hours or days",
    )
    history_days: Optional[int] = Field(
        None,
        description="Total duration of observation history in days",
    )
    stage_status: Optional[str] = Field(
        "unbuilt",
        description="Stage implementation status: live | unbuilt | experimental",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if values are hand-authored / mock for an unbuilt stage",
    )


class SiteContract(BaseModel):
    """Site contract mirroring the SQLite `sites` table plus Thermal DNA."""

    schema_version: str = Field(
        "1.0.0",
        description="Semantic version of this contract schema",
    )
    site_id: str = Field(
        ...,
        description="Primary identifier for the site (e.g. TG-23731-86324)",
    )
    lat: float = Field(
        ...,
        description="Centroid latitude coordinate in degrees",
    )
    lon: float = Field(
        ...,
        description="Centroid longitude coordinate in degrees",
    )
    classification: str = Field(
        "other",
        description="Class: industrial_fire | agricultural_burn | wildfire | other",
    )
    confidence: float = Field(
        0.0,
        description="Classification confidence score (0.0 to 1.0)",
    )
    explanation: str = Field(
        "",
        description="Human-readable rule classification explanation",
    )
    severity: str = Field(
        "minor",
        description="Severity tier: minor | moderate | severe | extreme",
    )
    is_anomalous: int = Field(
        0,
        description="1 if flagged as anomalous (severe/extreme), 0 otherwise",
    )
    status: str = Field(
        "routine",
        description="Operational status: routine | monitoring | alert_triggered | confirmed | dismissed",
    )
    first_seen: Optional[str] = Field(
        None,
        description="ISO 8601 timestamp of first detection",
    )
    last_seen: Optional[str] = Field(
        None,
        description="ISO 8601 timestamp of most recent detection",
    )
    max_frp: float = Field(
        0.0,
        description="Maximum observed Fire Radiative Power (MW)",
    )
    brightness: float = Field(
        0.0,
        description="Maximum observed brightness temperature (K)",
    )
    persistence: int = Field(
        0,
        description="Number of recent satellite passes where site was active (out of 5)",
    )
    consec_days: int = Field(
        0,
        description="Number of consecutive active calendar days",
    )
    duty_cycle_pct: float = Field(
        0.0,
        description="Duty cycle percentage across observation passes",
    )
    d_industrial_m: Optional[float] = Field(
        None,
        description="Distance to nearest industrial polygon in meters",
    )
    d_agri_m: Optional[float] = Field(
        None,
        description="Distance to nearest agricultural polygon in meters",
    )
    d_residential_m: Optional[float] = Field(
        None,
        description="Distance to nearest residential polygon in meters",
    )
    coverage_status: str = Field(
        "unknown",
        description="Satellite coverage status: covered | uncovered | unknown",
    )
    last_pass_date: Optional[str] = Field(
        None,
        description="Date of latest satellite pass over this site",
    )
    days_since_last_pass: Optional[int] = Field(
        None,
        description="Elapsed days since latest satellite pass",
    )
    thermal_dna: Optional[ThermalDNA] = Field(
        None,
        description="Thermal DNA behavioral baseline characteristics",
    )
