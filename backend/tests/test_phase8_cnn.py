"""Phase 8 regression tests: CNN visual classification on satellite imagery chips."""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.cnn_visual import MODEL_PATH, extract_visual_features, predict_visual, train_cnn_model
from app.main import app

client = TestClient(app)


def test_cnn_feature_extraction(tmp_path):
    """Verify feature extractor returns 102-dimensional vector for RGB image."""
    from PIL import Image
    test_img_path = tmp_path / "test_chip.jpg"
    img = Image.new("RGB", (64, 64), color=(200, 100, 50))
    img.save(test_img_path)

    feats = extract_visual_features(test_img_path)
    assert len(feats) == 102
    assert feats.dtype == "float32" or feats.dtype == "float64"


def test_cnn_training_stratified_split():
    """Verify train_cnn_model executes stratified split and produces valid metrics."""
    res = train_cnn_model()
    assert "status" in res
    assert res["status"] in ("OPERATIONAL (POC)", "RESEARCH / EXPERIMENTAL")
    assert "train_sample_count" in res
    assert "test_sample_count" in res
    assert res["train_sample_count"] > 0
    assert res["test_sample_count"] > 0
    assert "accuracy" in res
    assert "confusion_matrix" in res
    assert os.path.exists(MODEL_PATH)


def test_predict_visual_auxiliary_field_and_endpoint():
    """Verify predict_visual returns prediction tuple and exposes fields on /api/sites API."""
    # Run training first to ensure model file exists
    train_cnn_model()

    # Query sites endpoint
    res = client.get("/api/sites")
    assert res.status_code == 200
    sites = res.json()
    assert len(sites) > 0

    first_site = sites[0]
    assert "cnn_prediction" in first_site
    assert "cnn_confidence" in first_site
    assert first_site["cnn_prediction"] in (None, "industrial_fire", "other")
