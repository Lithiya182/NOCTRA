# NOCTRA Data Contracts

This directory contains the authoritative Pydantic v2 data contracts for the NOCTRA platform upgrade.

These contracts formalize the boundaries between pipeline stages and replace ad-hoc dictionary representations with typed, validated data schemas.

---

## The Core Rule: Governance & Mutation Policy

> [!CAUTION]
> ### STRICT CONTRACT CHANGE GOVERNANCE RULE
> **Any change, addition, deprecation, or removal in `contracts/` REQUIRES a Pull Request reviewed and explicitly approved by all three core engineers (Engineering Trio) before merging into main.**
> 
> No single engineer or automated process may alter these contracts independently. All downstream subsystems (ingestion, classification, fusion, UI, and review console) depend directly upon these frozen interfaces.

---

## Contract Inventory

| Contract | File | Schema Version | Description | Target NOCTRA Stage |
|---|---|---|---|---|
| **Site** | [`site.py`](site.py) | `1.0.0` | Mirrors the `sites` DB table plus `ThermalDNA` behavioral profile | Stage 2 (Site Formation) & Stage 3 (Thermal DNA) |
| **Event** | [`event.py`](event.py) | `1.0.0` | Satellite telemetry observation event linking detections to formed sites | Stage 1 (FIRMS Ingestion) |
| **Evidence** | [`evidence.py`](evidence.py) | `1.0.0` | Multi-stage evidence: Rule classification, EBM shadow, Severity hysteresis, EWMA/CUSUM, Sentinel-2, Bayesian fusion, and Routing | Stages 4, 5, 6, 7, 8, 9 |
| **Review** | [`review.py`](review.py) | `1.0.0` | Human review audit trail mirroring `alert_reviews` plus reviewer FK & structured overrides | Stage 10 (Human Review Console) |
| **Trace** | [`trace.py`](trace.py) | `1.0.0` | Ordered 12-stage execution DAG (`TraceStep`) and notification dispatch audit (`NotificationTrace`) | Stage 11 (Twilio Dispatch) & Stage 12 (Decision Trace) |

---

## Design Principles

1. **Schema Versioning**: Every contract specifies a mandatory `schema_version` (starting at `1.0.0`).
2. **Backward Compatibility & Adaptation**: Contracts mirror existing SQLite column names (`sites`, `detections`, `alerts`, `alert_reviews`) to avoid inventing speculative schemas while providing structured extensions for missing stages.
3. **Honest Staging Flags**: Every field derived from unbuilt or experimental stages is explicitly optional and annotated with `stage_status` (`"unbuilt"`, `"partially_implemented"`, `"shadow"`, or `"experimental"`) and `"mock": true` when populated with synthetic fixture data.
4. **Human Gating Enforcement**: The `trace.py` and `evidence.py` contracts strictly enforce human-review gating: notification dispatch status defaults to `not_dispatched` or `gated_awaiting_review` and requires an authorized reviewer identity before any external transmission.
