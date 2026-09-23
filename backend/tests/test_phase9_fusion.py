"""Phase 9 regression & unit tests: Thermal + Visual Evidence Fusion."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.classifier import ClassResult, Evidence, fuse_evidence
from app.main import app

client = TestClient(app)


def test_fusion_no_imagery_fallback():
    """Verify sites without imagery or CNN predictions fall back cleanly to thermal evidence."""
    base_evidence = Evidence(
        spatial="proximity",
        temporal="sufficient",
        intensity="moderate",
        sufficiency="sufficient",
        reason="Within 400m of industrial polygon with 3/5 recent passes",
        visual="none",
    )
    base_result = ClassResult(
        classification="industrial_fire",
        confidence=0.80,
        explanation=base_evidence.reason,
        features={},
        evidence=base_evidence,
    )

    # 1. No imagery available
    fused_no_img = fuse_evidence(base_result, cnn_prediction="industrial_fire", cnn_confidence=0.75, has_imagery=False)
    assert fused_no_img.evidence.visual == "none"
    assert fused_no_img.evidence.sufficiency == "sufficient"
    assert fused_no_img.explanation == base_evidence.reason
    assert fused_no_img.classification == "industrial_fire"

    # 2. Imagery present but CNN prediction is None
    fused_no_pred = fuse_evidence(base_result, cnn_prediction=None, cnn_confidence=None, has_imagery=True)
    assert fused_no_pred.evidence.visual == "none"
    assert fused_no_pred.evidence.sufficiency == "sufficient"
    assert fused_no_pred.explanation == base_evidence.reason
    assert fused_no_pred.classification == "industrial_fire"


def test_fusion_corroborating_visual_evidence():
    """Verify matching CNN prediction reinforces evidence sufficiency and updates reason string."""
    base_evidence = Evidence(
        spatial="polygon_containment",
        temporal="persistent",
        intensity="high",
        sufficiency="sufficient",
        reason="Inside industrial polygon (strong spatial evidence)",
        visual="none",
    )
    base_result = ClassResult(
        classification="industrial_fire",
        confidence=0.90,
        explanation=base_evidence.reason,
        features={},
        evidence=base_evidence,
    )

    fused = fuse_evidence(base_result, cnn_prediction="industrial_fire", cnn_confidence=0.82, has_imagery=True)
    assert fused.evidence.visual == "corroborating"
    assert fused.evidence.sufficiency == "sufficient"
    assert "Visual evidence corroborates thermal classification" in fused.explanation
    assert fused.classification == "industrial_fire"


def test_fusion_conflicting_visual_evidence():
    """Verify disagreeing CNN prediction marks evidence sufficiency as conflicting and flags for review."""
    base_evidence = Evidence(
        spatial="none",
        temporal="insufficient",
        intensity="weak",
        sufficiency="insufficient",
        reason="No spatial evidence, insufficient temporal evidence",
        visual="none",
    )
    base_result = ClassResult(
        classification="other",
        confidence=0.40,
        explanation=base_evidence.reason,
        features={},
        evidence=base_evidence,
    )

    # CNN predicts industrial_fire while thermal says other
    fused = fuse_evidence(base_result, cnn_prediction="industrial_fire", cnn_confidence=0.65, has_imagery=True)
    assert fused.evidence.visual == "conflicting"
    assert fused.evidence.sufficiency == "conflicting"
    assert "Visual evidence conflicts with thermal classification" in fused.explanation
    assert "flagged for human review" in fused.explanation
    # Rule-based thermal classification remains strictly authoritative!
    assert fused.classification == "other"


def test_fusion_sites_api_integration():
    """Verify /api/sites returns visual_evidence and evidence_sufficiency fields."""
    res = client.get("/api/sites")
    assert res.status_code == 200
    sites = res.json()
    assert len(sites) > 0

    for site in sites:
        assert "visual_evidence" in site
        assert "evidence_sufficiency" in site
        assert site["visual_evidence"] in ("none", "corroborating", "conflicting", "uninformative")

        # Sites with imagery should have fused evidence evaluated
        img_res = client.get(f"/api/sites/{site['site_id']}/imagery")
        imagery = img_res.json() if img_res.status_code == 200 else []
        has_avail_img = any(img.get("status") == "available" for img in imagery)

        if not has_avail_img:
            assert site["visual_evidence"] == "none"
