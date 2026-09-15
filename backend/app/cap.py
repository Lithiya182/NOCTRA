"""CAP (Common Alerting Protocol 1.2) payload generator - pure string/JSON templating.
No external API required; this is the most credible, dependency-free artifact."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

LABELS = {
    "minor": ("Minor thermal anomaly", "Observation"),  # (event, urgency)
    "moderate": ("Moderate fire risk", "Expected"),
    "severe": ("Severe fire hazard", "Immediate"),
    "extreme": ("Extreme fire emergency", "Immediate"),
}

CATEGORY_MAP = {
    "industrial_fire": "Industrialfire",
    "agricultural_burn": "Other",
    "wildfire": "Wildfire",
    "other": "Other",
}


def build_cap_alert(site: dict, change_status: str = "Actual") -> dict:
    """Build a CAP 1.2 JSON alert from a site row (shared JSON contract).
    status: Actual | Exercise | System; msgType: Alert | Update | Cancel."""
    sent = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    event, urgency = LABELS.get(site["severity"], LABELS["minor"])
    severity = site["severity"].upper()
    certainty = "Observed"
    area_desc = f"{site['lat']:.3f}N {site['lon']:.3f}E (radius 5 km)"

    info = {
        "language": "en-IN",
        "category": CATEGORY_MAP.get(site["classification"], "Other"),
        "event": event,
        "responseType": "Shelter",
        "urgency": urgency,
        "severity": severity,
        "certainty": certainty,
        "senderName": "ThermalGuard Fire Classification System",
        "headline": (
            f"{event.title()} at {site['lat']:.3f}N {site['lon']:.3f}E "
            f"(classification: {site['classification']})"
        ),
        "description": (
            f"{site.get('explanation', '')} Site {site['site_id']} has been classified as "
            f"'{site['classification']}' with confidence {site.get('confidence', 0)}. "
            f"Thermal state persists and is under evaluation by the district control room."
        ),
        "area": {
            "areaDesc": area_desc,
            "circle": f"{site['lat']:.4f},{site['lon']:.4f} {5000.0:.2f}",
        },
    }
    return {
        "identifier": f"thermalguard-{uuid.uuid4().hex[:12]}",
        "sender": "thermalguard@district-control.gov.in",
        "sent": sent,
        "status": change_status,
        "msgType": "Alert",
        "scope": "Public",
        "info": [info],
    }


def cap_to_sms_text(cap: dict) -> str:
    info = cap["info"][0]
    return (
        f"[ThermalGuard] {info['severity'].title()} - {info['event']}. "
        f"{info['headline']}. Area: {info['area']['areaDesc']}. "
        f"Action: stay clear of the affected radius; follow local advisories."
    )


def cap_to_push_title(cap: dict) -> str:
    info = cap["info"][0]
    return f"{info['severity'].title()} fire alert - {info['event']}"

def cap_to_push_body(cap: dict) -> str:
    info = cap["info"][0]
    return f"{info['headline']} | {info['area']['areaDesc']} | confidence: immediate action advised."