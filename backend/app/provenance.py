"""Provenance helper module for NOCTRA subsystems (imagery, CNN, RL, detections, etc.).

Ensures consistent provenance metadata tracking across all database entities and subsystems.
Standard fields:
- is_synthetic: int (1 for synthetic/demo data, 0 for real observation data)
- source: str (e.g., 'firms', 'synthetic', 'sentinel2-l2a', 'weak_label_rf', 'resnet18_cnn', 'contextual_bandit')
- ingestion_batch: str | None (batch run identifier or timestamp string)
- created_at: str (ISO 8601 UTC timestamp string)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def get_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Provenance:
    is_synthetic: int = 1
    source: str = "synthetic"
    ingestion_batch: Optional[str] = None
    created_at: str = field(default_factory=get_now_iso)

    def __post_init__(self) -> None:
        # Coerce boolean to int (1 or 0)
        if isinstance(self.is_synthetic, bool):
            self.is_synthetic = 1 if self.is_synthetic else 0
        else:
            self.is_synthetic = 1 if int(self.is_synthetic) != 0 else 0

        if not self.source:
            self.source = "unknown"

        if not self.created_at:
            self.created_at = get_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_synthetic": self.is_synthetic,
            "source": self.source,
            "ingestion_batch": self.ingestion_batch,
            "created_at": self.created_at,
        }


def build_provenance_fields(
    is_synthetic: bool | int = True,
    source: str = "synthetic",
    ingestion_batch: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper to construct a standardized provenance dictionary."""
    prov = Provenance(
        is_synthetic=1 if is_synthetic else 0,
        source=source,
        ingestion_batch=ingestion_batch,
        created_at=created_at or get_now_iso(),
    )
    return prov.to_dict()


def normalize_provenance(
    record: Dict[str, Any], default_source: str = "synthetic"
) -> Dict[str, Any]:
    """Ensure a record dict contains all required provenance fields with normalized types."""
    is_synth_val = record.get("is_synthetic")
    if is_synth_val is None:
        is_synth = 1
    elif isinstance(is_synth_val, bool):
        is_synth = 1 if is_synth_val else 0
    else:
        is_synth = 1 if int(is_synth_val) != 0 else 0

    source = str(record.get("source") or default_source)
    batch = record.get("ingestion_batch")
    created_at = str(record.get("created_at") or get_now_iso())

    out = dict(record)
    out["is_synthetic"] = is_synth
    out["source"] = source
    out["ingestion_batch"] = batch
    out["created_at"] = created_at
    return out
