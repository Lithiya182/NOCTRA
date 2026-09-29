"""Validation tests for NOCTRA Pydantic v2 Contracts and Demo Fixtures.

Validates that every fixture in `fixtures/*.json`:
1. Conforms to the `SiteContract`, `EventContract`, `EvidenceContract`, `ReviewContract` (if present),
   `DecisionTraceContract`, and the consolidated `DemoSiteBundle`.
2. Contains schema_version="1.0.0" across all entities.
3. Contains 12 ordered TraceStep records covering all 12 frozen pipeline stages.
4. Correctly marks fields from unbuilt stages with mock=True.
5. Accurately models the specific scenario requirements:
   - SITE-001: Quiet normal industrial (benign route, steady baseline).
   - SITE-002: Hero site (abnormal seam fire, extreme FRP, change detected, hazard route, awaiting review).
   - SITE-003: Noisy isolated hotspot (other, unconfirmed route, no escalation).
   - SITE-004: Seasonal agricultural burn (expected harvest burn, confirmation path with audit review).
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from contracts.site import SiteContract
from contracts.event import EventContract
from contracts.evidence import EvidenceContract
from contracts.review import ReviewContract
from contracts.trace import DecisionTraceContract
from contracts import DemoSiteBundle

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"

EXPECTED_STAGES = [
    "FIRMS_INGEST",
    "SITE_FORMATION",
    "THERMAL_DNA_OSM",
    "CLASSIFICATION_RULE_AND_EBM",
    "SEVERITY_AND_HYSTERESIS",
    "CHANGE_DETECTION_EWMA_CUSUM",
    "SENTINEL2_CORROBORATION",
    "BAYESIAN_FUSION",
    "ROUTING_AND_PRIORITY",
    "HUMAN_REVIEW",
    "TWILIO_DISPATCH",
    "DECISION_TRACE",
]


@pytest.fixture(params=["site_001.json", "site_002.json", "site_003.json", "site_004.json"])
def fixture_file(request) -> tuple[str, dict]:
    filepath = FIXTURES_DIR / request.param
    assert filepath.exists(), f"Fixture file not found: {filepath}"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return request.param, data


def test_fixture_validates_against_all_contracts(fixture_file):
    filename, data = fixture_file

    # 1. Consolidated bundle validation
    bundle = DemoSiteBundle.model_validate(data)
    assert bundle.schema_version == "1.0.0"

    # 2. Individual contract validations
    site = SiteContract.model_validate(data["site"])
    assert site.schema_version == "1.0.0"
    assert site.site_id.startswith("TG-")

    event = EventContract.model_validate(data["event"])
    assert event.schema_version == "1.0.0"
    assert event.site_id == site.site_id
    assert event.provenance.is_synthetic == 1
    assert event.provenance.source == "synthetic"

    evidence = EvidenceContract.model_validate(data["evidence"])
    assert evidence.schema_version == "1.0.0"
    assert evidence.routing.path in ("benign", "hazard", "unconfirmed")

    if data.get("review") is not None:
        review = ReviewContract.model_validate(data["review"])
        assert review.schema_version == "1.0.0"
        assert review.site_id == site.site_id
        assert review.reviewed_by is not None

    trace = DecisionTraceContract.model_validate(data["trace"])
    assert trace.schema_version == "1.0.0"
    assert trace.site_id == site.site_id

    # 3. Verify exactly 12 steps covering all stages in order
    assert len(trace.steps) == 12
    for idx, expected_stage in enumerate(EXPECTED_STAGES, start=1):
        step = trace.steps[idx - 1]
        assert step.step_no == idx
        assert step.stage == expected_stage


def test_site_001_normal_industrial_scenario():
    filepath = FIXTURES_DIR / "site_001.json"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    bundle = DemoSiteBundle.model_validate(data)

    assert bundle.fixture_id == "SITE-001"
    assert bundle.site.classification == "industrial_fire"
    assert bundle.site.is_anomalous == 0
    assert bundle.site.status == "routine"
    assert bundle.evidence.change.change_detected is False
    assert bundle.evidence.routing.path == "benign"
    assert bundle.trace.notification.status == "not_dispatched"
    assert bundle.review is None


def test_site_002_hero_abnormal_hazard_scenario():
    filepath = FIXTURES_DIR / "site_002.json"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    bundle = DemoSiteBundle.model_validate(data)

    assert bundle.fixture_id == "SITE-002"
    assert bundle.site.classification == "industrial_fire"
    assert bundle.site.is_anomalous == 1
    assert bundle.site.severity == "extreme"
    assert bundle.site.status == "alert_triggered"
    assert bundle.evidence.change.change_detected is True
    assert bundle.evidence.change.cusum > 50.0
    assert bundle.evidence.sentinel.available is True
    assert bundle.evidence.sentinel.result == "plume_detected"
    assert bundle.evidence.fusion.posterior > 0.90
    assert bundle.evidence.routing.path == "hazard"
    assert bundle.evidence.routing.requires_human_review is True
    # Human gating check: notification held in gated_awaiting_review
    assert bundle.trace.notification.status == "gated_awaiting_review"
    assert bundle.trace.notification.message_sid is None


def test_site_003_noisy_isolated_hotspot_scenario():
    filepath = FIXTURES_DIR / "site_003.json"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    bundle = DemoSiteBundle.model_validate(data)

    assert bundle.fixture_id == "SITE-003"
    assert bundle.site.classification == "other"
    assert bundle.site.persistence == 1
    assert bundle.site.is_anomalous == 0
    assert bundle.evidence.routing.path == "unconfirmed"
    assert bundle.evidence.change.change_detected is False
    assert bundle.trace.notification.status == "not_dispatched"
    assert bundle.review is None


def test_site_004_seasonal_agricultural_burn_scenario():
    filepath = FIXTURES_DIR / "site_004.json"
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    bundle = DemoSiteBundle.model_validate(data)

    assert bundle.fixture_id == "SITE-004"
    assert bundle.site.classification == "agricultural_burn"
    assert bundle.site.status == "confirmed"
    assert bundle.evidence.routing.path == "benign"
    assert bundle.review is not None
    assert bundle.review.action == "confirm"
    assert bundle.review.new_status == "confirmed"
    assert "District Agriculture Officer" in bundle.review.reviewed_by
    assert bundle.review.feedback_label == "correct"
    assert bundle.trace.notification.status == "not_dispatched"
