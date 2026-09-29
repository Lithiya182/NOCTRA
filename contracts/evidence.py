"""NOCTRA Evidence Contract.

Unifies classification, EBM shadow inference, severity hysteresis, temporal change
detection (EWMA+CUSUM), optical Sentinel-2 corroboration, Bayesian fusion, and routing.
Every field from unbuilt stages is Optional and flagged with stage_status.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class RuleClassificationEvidence(BaseModel):
    """Stage 4 (Live): Rule-based fire classifier decision and spatial/temporal justification."""

    classification: str = Field(
        ...,
        description="Rule classification: industrial_fire | agricultural_burn | wildfire | other",
    )
    confidence: float = Field(
        0.0,
        description="Confidence score assigned by rule engine (0.0 to 1.0)",
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="Explanatory rationale sentences from rule engine",
    )
    spatial: Optional[str] = Field(
        None,
        description="Spatial evidence type: polygon_containment | proximity | none",
    )
    temporal: Optional[str] = Field(
        None,
        description="Temporal evidence type: persistent | sufficient | insufficient",
    )
    intensity: Optional[str] = Field(
        None,
        description="Intensity evidence level: weak | moderate | high-moderate | high | very-high",
    )
    sufficiency: Optional[str] = Field(
        None,
        description="Evidence sufficiency state: sufficient | insufficient | conflicting",
    )
    stage_status: str = Field(
        "live",
        description="Stage implementation status: live",
    )


class EBMShadowEvidence(BaseModel):
    """Stage 4 (Shadow): Explainable Boosting Machine shadow inference."""

    label: Optional[str] = Field(
        None,
        description="Shadow prediction label from Explainable Boosting Classifier",
    )
    status: str = Field(
        "experimental",
        description="Operational status of shadow model: experimental",
    )
    score: Optional[float] = Field(
        None,
        description="Shadow model prediction probability / score (0.0 to 1.0)",
    )
    feature_importances: Optional[dict[str, float]] = Field(
        None,
        description="Local feature additive contributions / SHAP-style weights",
    )
    stage_status: str = Field(
        "unbuilt",
        description="Stage status: unbuilt / shadow only",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if hand-authored mock data",
    )


class SeverityEvidence(BaseModel):
    """Stage 5: Multi-attribute severity assessment with anti-flapping hysteresis."""

    tier: str = Field(
        "minor",
        description="Severity tier: minor | moderate | severe | extreme",
    )
    model_status: Optional[str] = Field(
        "rule_based",
        description="Severity generator: rule_based | lightgbm_shadow | experimental",
    )
    hysteresis_state: Optional[str] = Field(
        "steady",
        description="Hysteresis state: steady | escalating | de-escalating | locked",
    )
    consecutive_passes_in_tier: Optional[int] = Field(
        1,
        description="Number of consecutive observation passes remaining in this tier",
    )
    stage_status: str = Field(
        "partially_implemented",
        description="Stage status: rule tier live; LightGBM & hysteresis filter unbuilt",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if hand-authored mock data",
    )


class ChangeEvidence(BaseModel):
    """Stage 6: Temporal drift & sudden thermal anomaly detection via EWMA + CUSUM."""

    ewma_baseline: Optional[float] = Field(
        None,
        description="Exponentially Weighted Moving Average baseline thermal intensity in MW",
    )
    cusum: Optional[float] = Field(
        None,
        description="Tabular Cumulative Sum (CUSUM) positive shift statistic",
    )
    change_detected: Optional[bool] = Field(
        None,
        description="True if structural thermal shift / anomaly detected",
    )
    gap_tolerant: Optional[bool] = Field(
        True,
        description="Flag indicating algorithm accounts for irregular pass intervals",
    )
    stage_status: str = Field(
        "unbuilt",
        description="Stage status: unbuilt",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if hand-authored mock data",
    )


class SentinelEvidence(BaseModel):
    """Stage 7: Optical corroboration via high-resolution Sentinel-2 STAC imagery chips."""

    available: bool = Field(
        False,
        description="True if an optical Sentinel-2 imagery chip is available for this site",
    )
    cloud_pct: Optional[float] = Field(
        None,
        description="Cloud cover percentage (0 to 100) over the imagery chip",
    )
    result: Optional[str] = Field(
        None,
        description="Visual assessment: plume_detected | no_burn_scar | corroborating | conflicting | uninformative | none",
    )
    reliability: Optional[float] = Field(
        None,
        description="Conditioned reliability factor (0.0 to 1.0) based on cloud occlusion and resolution",
    )
    file_path: Optional[str] = Field(
        None,
        description="Relative filepath to imagery chip within DATA_DIR / imagery",
    )
    stage_status: str = Field(
        "partially_implemented",
        description="Stage status: file storage and classical CV live; STAC automated fetch unbuilt",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if hand-authored mock data",
    )


class SignalLikelihoodRatio(BaseModel):
    """Likelihood ratio and reliability weighting for an individual evidence signal."""

    signal_name: str = Field(
        ...,
        description="Signal identifier: thermal_rules | ebm_shadow | sentinel2 | cusum",
    )
    lr: float = Field(
        ...,
        description="Raw likelihood ratio P(E|Hazard) / P(E|Benign)",
    )
    reliability: float = Field(
        1.0,
        description="Reliability discount factor (0.0 to 1.0)",
    )
    effective_lr: float = Field(
        ...,
        description="Effective likelihood ratio applied after reliability shrinkage",
    )


class FusionEvidence(BaseModel):
    """Stage 8: Probabilistic Bayesian fusion combining multiple independent signals."""

    prior_odds: Optional[float] = Field(
        None,
        description="Prior odds of active fire hazard before incorporating new evidence",
    )
    signals: Optional[List[SignalLikelihoodRatio]] = Field(
        None,
        description="Per-signal likelihood ratios, reliability metrics, and effective LRs",
    )
    posterior: Optional[float] = Field(
        None,
        description="Calculated posterior probability (0.0 to 1.0) of fire hazard",
    )
    stage_status: str = Field(
        "unbuilt",
        description="Stage status: unbuilt",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if hand-authored mock data",
    )


class RoutingEvidence(BaseModel):
    """Stage 9: Triage routing determining review urgency and dispatch path."""

    path: Literal["benign", "hazard", "unconfirmed"] = Field(
        ...,
        description="Assigned routing path: benign | hazard | unconfirmed",
    )
    reason: str = Field(
        ...,
        description="Operational justification for routing path assignment",
    )
    priority_score: Optional[float] = Field(
        None,
        description="Console review priority score (higher = higher position in review queue)",
    )
    requires_human_review: bool = Field(
        False,
        description="True if event must be verified by a human reviewer before notification",
    )
    stage_status: str = Field(
        "partially_implemented",
        description="Stage status: rule gating live; contextual bandit unbuilt",
    )
    mock: Optional[bool] = Field(
        None,
        description="True if hand-authored mock data",
    )


class EvidenceContract(BaseModel):
    """Consolidated NOCTRA Evidence contract combining all evidence stages."""

    schema_version: str = Field(
        "1.0.0",
        description="Semantic version of this contract schema",
    )
    rule_classification: RuleClassificationEvidence
    ebm_shadow: Optional[EBMShadowEvidence] = Field(default_factory=EBMShadowEvidence)
    severity: SeverityEvidence
    change: Optional[ChangeEvidence] = Field(default_factory=ChangeEvidence)
    sentinel: Optional[SentinelEvidence] = Field(default_factory=SentinelEvidence)
    fusion: Optional[FusionEvidence] = Field(default_factory=FusionEvidence)
    routing: RoutingEvidence
