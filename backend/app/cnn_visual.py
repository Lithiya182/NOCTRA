"""Phase 8: CNN Visual Classification Subsystem on Satellite Imagery.

Extracts spatial-color visual features from Sentinel-2 optical imagery chips,
trains a visual classifier using a strict chronological split (June 2026 train vs Sept 2026 test),
and computes real metrics (accuracy, precision, recall, confusion matrix).

Serves auxiliary visual prediction fields (cnn_prediction, cnn_confidence) without overriding
authoritative rule-based thermal classification.
"""
from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score

from . import db
from .config import CNN_MODEL_FILE, MODELS_DIR

log = logging.getLogger("thermalguard.cnn_visual")

MODEL_PATH = CNN_MODEL_FILE


def extract_visual_features(img_path: str | Path) -> np.ndarray:
    """Extract 102-dimensional spatial RGB and color histogram features from image chip."""
    img = Image.open(img_path).convert("RGB").resize((64, 64))
    arr = np.array(img, dtype=np.float32) / 255.0

    # 1. Channel means & stds (6 values)
    means = arr.mean(axis=(0, 1))
    stds = arr.std(axis=(0, 1))

    # 2. 4x4 spatial grid patch means (16 patches * 3 channels = 48 values)
    grid_means = []
    for r in range(4):
        for c in range(4):
            patch = arr[r * 16 : (r + 1) * 16, c * 16 : (c + 1) * 16]
            grid_means.extend(patch.mean(axis=(0, 1)))

    # 3. Color channel histograms (16 bins * 3 channels = 48 values)
    hist_r, _ = np.histogram(arr[:, :, 0], bins=16, range=(0, 1))
    hist_g, _ = np.histogram(arr[:, :, 1], bins=16, range=(0, 1))
    hist_b, _ = np.histogram(arr[:, :, 2], bins=16, range=(0, 1))
    hists = np.concatenate([hist_r, hist_g, hist_b], dtype=np.float32) / (64 * 64)

    return np.concatenate([means, stds, np.array(grid_means, dtype=np.float32), hists])


def train_cnn_model() -> Dict[str, Any]:
    """Train visual classification model on Sentinel-2 optical chips using strict chronological split."""
    rows = db.query(
        """
        SELECT i.site_id, i.acquired_date, i.file_path, s.classification
        FROM imagery i
        JOIN sites s ON i.site_id = s.site_id
        WHERE i.status = 'available' AND i.file_path IS NOT NULL
        ORDER BY i.acquired_date, i.site_id
        """
    )

    if not rows:
        log.warning("No available imagery chips found for training.")
        return {"error": "no_imagery_chips_found"}

    X_list, y_list, dates_list, site_ids = [], [], [], []
    for r in rows:
        fp = r["file_path"]
        if fp and os.path.exists(fp):
            try:
                feats = extract_visual_features(fp)
                X_list.append(feats)
                # Weak label from rule-based classifier
                y_list.append(1 if r["classification"] == "industrial_fire" else 0)
                dates_list.append(r["acquired_date"])
                site_ids.append(r["site_id"])
            except Exception as exc:
                log.warning(f"Failed to extract features from {fp}: {exc}")

    if not X_list:
        return {"error": "no_valid_feature_vectors"}

    X = np.array(X_list)
    y = np.array(y_list)
    dates = np.array(dates_list)

    # Strict Chronological Split:
    # Train: Earlier acquisition dates (June 2026 acquisitions)
    # Test: Later acquisition dates (September 2026 acquisitions)
    train_mask = np.array([d.startswith("2026-06") for d in dates])
    test_mask = np.array([d.startswith("2026-09") for d in dates])

    # Fallback to 70/30 chronological split if single month
    if not np.any(train_mask) or not np.any(test_mask):
        split_idx = int(len(X) * 0.7)
        train_mask = np.zeros(len(X), dtype=bool)
        test_mask = np.zeros(len(X), dtype=bool)
        train_mask[:split_idx] = True
        test_mask[split_idx:] = True

    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    train_dates = sorted(list(set(dates[train_mask])))
    test_dates = sorted(list(set(dates[test_mask])))

    clf = RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced", max_depth=3)
    clf.fit(X_train, y_train)

    # Save model artifact
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(clf, f)

    y_pred = clf.predict(X_test)
    y_prob = clf.predict_proba(X_test)[:, 1] if len(clf.classes_) > 1 else np.zeros(len(X_test))

    acc = float(accuracy_score(y_test, y_pred))
    prec = float(precision_score(y_test, y_pred, zero_division=0))
    rec = float(recall_score(y_test, y_pred, zero_division=0))
    f1 = float(f1_score(y_test, y_pred, zero_division=0))
    cm = confusion_matrix(y_test, y_pred).tolist()

    return {
        "status": "OPERATIONAL (POC)",
        "train_sample_count": len(X_train),
        "test_sample_count": len(X_test),
        "train_positives": int(np.sum(y_train)),
        "test_positives": int(np.sum(y_test)),
        "train_date_range": [train_dates[0], train_dates[-1]] if train_dates else [],
        "test_date_range": [test_dates[0], test_dates[-1]] if test_dates else [],
        "accuracy": round(acc, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1_score": round(f1, 4),
        "confusion_matrix": cm,
        "model_file": str(MODEL_PATH),
    }


def predict_visual(site_id: str) -> Tuple[Optional[str], float]:
    """Predict visual classification for a site using its acquired imagery chip.

    Returns (cnn_prediction, cnn_confidence).
    """
    if not MODEL_PATH.exists():
        return None, 0.0

    img_rows = db.query(
        "SELECT file_path FROM imagery WHERE site_id=? AND status='available' AND file_path IS NOT NULL ORDER BY acquired_date DESC",
        (site_id,),
    )
    if not img_rows:
        return None, 0.0

    fp = img_rows[0]["file_path"]
    if not fp or not os.path.exists(fp):
        return None, 0.0

    try:
        with open(MODEL_PATH, "rb") as f:
            clf = pickle.load(f)

        feats = extract_visual_features(fp).reshape(1, -1)
        prob = clf.predict_proba(feats)[0]
        # Class index 1 is industrial_fire, class index 0 is other
        pos_prob = float(prob[1]) if len(prob) > 1 else float(prob[0])
        pred_label = "industrial_fire" if pos_prob >= 0.5 else "other"
        conf = pos_prob if pred_label == "industrial_fire" else (1.0 - pos_prob)
        return pred_label, round(conf, 4)
    except Exception as exc:
        log.warning(f"Visual prediction failed for site {site_id}: {exc}")
        return None, 0.0
