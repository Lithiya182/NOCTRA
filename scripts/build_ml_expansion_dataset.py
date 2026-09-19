"""Build temporal expansion-risk ML dataset from FIRMS history.

Reads: data/firms_history_jharia.csv
Writes: data/ml_expansion_features.csv
        audit/ml_expansion_dataset_report.txt

No SQLite ingestion, no model training.
"""

import csv
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
AUDIT_DIR = ROOT / "audit"
AUDIT_DIR.mkdir(exist_ok=True)

INPUT_CSV = DATA_DIR / "firms_history_jharia.csv"
OUTPUT_CSV = DATA_DIR / "ml_expansion_features.csv"
REPORT_TXT = AUDIT_DIR / "ml_expansion_dataset_report.txt"

# Production clustering uses 1km (CLUSTER_RADIUS_M = 1000)
# 0.01 degree ≈ 1.11 km at equator, slightly less at higher latitudes
# This is consistent with production clustering
GRID_RESOLUTION = 0.01  # degrees

# Dataset date range
DATE_MIN = datetime(2026, 6, 3).date()
DATE_MAX = datetime(2026, 6, 30).date()
ALL_DATES = [DATE_MIN + timedelta(days=i) for i in range((DATE_MAX - DATE_MIN).days + 1)]
DATE_SET = set(ALL_DATES)

def grid_key(lat: float, lon: float, resolution: float = GRID_RESOLUTION) -> str:
    """Generate grid cell key from lat/lon."""
    grid_lat = int(round(lat / resolution) * resolution * 100)  # scale to int
    grid_lon = int(round(lon / resolution) * resolution * 100)
    return f"grid_{grid_lat}_{grid_lon}"

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def main():
    print("=== Building Temporal Expansion-Risk Dataset ===")

    # Load raw detections
    with open(DATA_DIR / "firms_history_jharia.csv", "r") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)

    print(f"Loaded {len(raw_rows)} raw detections")

    # Parse and validate
    detections = []
    for r in raw_rows:
        try:
            det = {
                'latitude': float(r['latitude']),
                'longitude': float(r['longitude']),
                'bright_ti4': float(r['bright_ti4']),
                'scan': float(r['scan']),
                'track': float(r['track']),
                'acq_date': datetime.strptime(r['acq_date'], '%Y-%m-%d').date(),
                'acq_time': r['acq_time'],
                'satellite': r['satellite'],
                'instrument': r['instrument'],
                'confidence': r['confidence'],
                'version': r['version'],
                'bright_ti5': float(r['bright_ti5']),
                'frp': float(r['frp']),
                'daynight': r['daynight'],
                'type': r.get('type', ''),
            }
            detections.append(det)
        except Exception as e:
            print(f"  Skipping row: {e}")

    print(f"Parsed {len(detections)} detections")

    # Assign grid cell to each detection
    for det in detections:
        det['grid_id'] = grid_key(det['latitude'], det['longitude'])

    # Group by grid_id and date
    grid_date_detections = defaultdict(lambda: defaultdict(list))
    for det in detections:
        grid_date_detections[det['grid_id']][det['acq_date']].append(det)

    print(f"Found {len(grid_date_detections)} unique grid cells with detections")

    # Build temporal site features
    site_date_features = []

    for grid_id, date_dets in grid_date_detections.items():
        # Get grid cell center (approximate)
        # Extract from grid_id
        parts = grid_id.split('_')
        if len(parts) >= 3:
            center_lat = float(parts[1]) / 100 * GRID_RESOLUTION
            center_lon = float(parts[2]) / 100 * GRID_RESOLUTION
        else:
            continue

        # For each date with detections, build features
        for date in sorted(date_dets.keys()):
            dets = date_dets[date]

            # Basic detection stats
            detection_count = len(dets)
            total_frp = sum(d['frp'] for d in dets)
            mean_frp = total_frp / detection_count
            max_frp = max(d['frp'] for d in dets)
            mean_brightness = sum(d['bright_ti4'] for d in dets) / detection_count
            max_brightness = max(d['bright_ti4'] for d in dets)
            day_count = sum(1 for d in dets if d['daynight'] == 'D')
            night_count = detection_count - day_count
            night_fraction = night_count / detection_count if detection_count > 0 else 0.0

            # Confidence
            low_conf = sum(1 for d in dets if d['confidence'] == 'l')
            nominal_conf = sum(1 for d in dets if d['confidence'] == 'n')

            # Build feature dict
            feat = {
                'site_id': f"grid_{grid_id}",
                'date': date.isoformat(),
                'latitude': center_lat,
                'longitude': center_lon,
                'detection_count': detection_count,
                'total_frp': total_frp,
                'mean_frp': mean_frp,
                'max_frp': max_frp,
                'mean_brightness': mean_brightness,
                'max_brightness': max_brightness,
                'day_detection_count': day_count,
                'night_detection_count': night_count,
                'night_fraction': night_fraction,
                'low_confidence_count': low_conf,
                'nominal_confidence_count': nominal_conf,
            }
            site_date_features.append(feat)

    print(f"Built {len(site_date_features)} site-date feature rows")

    # Sort by site and date
    site_date_features.sort(key=lambda x: (x['site_id'], x['date']))

    # Build temporal features with lag/rolling
    # Group by site
    by_site = defaultdict(list)
    for feat in site_date_features:
        by_site[feat['site_id']].append(feat)

    # Date set for coverage checking
    date_set = set(ALL_DATES)

    # Build temporal features per site
    final_rows = []

    for site_id, feats in by_site.items():
        feats.sort(key=lambda x: x['date'])

        # Map date -> feature index
        date_to_idx = {f['date']: i for i, f in enumerate(feats)}

        for i, feat in enumerate(feats):
            current_date = datetime.fromisoformat(feat['date']).date()

            # Helper to get feature at offset (negative = past)
            def get_past_feature(offset_days, key, default=None):
                target_date = current_date - timedelta(days=offset_days)
                if target_date not in date_set:
                    return 'coverage_unknown'
                target_str = target_date.isoformat()
                if target_str not in date_to_idx:
                    return 'no_detection'
                return feats[date_to_idx[target_str]].get(key, default)

            # Helper for rolling window
            def rolling_window(days_back, key, agg='count'):
                """Compute rolling aggregation over past N days (excluding today)."""
                vals = []
                for offset in range(1, days_back + 1):
                    target_date = current_date - timedelta(days=offset)
                    if target_date not in date_set:
                        continue  # unknown coverage
                    target_str = target_date.isoformat()
                    if target_str in date_to_idx:
                        val = feats[date_to_idx[target_str]].get(key, 0)
                        vals.append(val)
                    else:
                        vals.append(0)  # no detection = 0
                if not vals:
                    return 'coverage_unknown'
                if agg == 'count':
                    return len([v for v in vals if v != 'coverage_unknown' and v != 'no_detection' and v > 0])
                elif agg == 'mean':
                    valid_vals = [v for v in vals if isinstance(v, (int, float)) and v > 0]
                    return sum(valid_vals) / len(valid_vals) if valid_vals else 0
                elif agg == 'max':
                    valid_vals = [v for v in vals if isinstance(v, (int, float))]
                    return max(valid_vals) if valid_vals else 0
                return None

            # Lag features
            active_today = 1
            active_previous_day = get_past_feature(1, 'detection_count', 0)
            if active_previous_day in ('coverage_unknown', 'no_detection'):
                active_previous_day_flag = active_previous_day
                active_previous_day = 0 if active_previous_day == 'no_detection' else 'coverage_unknown'
            else:
                active_previous_day_flag = 1 if active_previous_day > 0 else 0

            active_previous_2_days = get_past_feature(2, 'detection_count', 0)
            if active_previous_2_days in ('coverage_unknown', 'no_detection'):
                active_previous_2_days = 0 if active_previous_2_days == 'no_detection' else 'coverage_unknown'

            active_previous_3_days = get_past_feature(3, 'detection_count', 0)
            if active_previous_3_days in ('coverage_unknown', 'no_detection'):
                active_previous_3_days = 0 if active_previous_3_days == 'no_detection' else 'coverage_unknown'

            # Consecutive active days before today
            consec = 0
            for offset in range(1, 31):
                target_date = current_date - timedelta(days=offset)
                if target_date not in date_set:
                    consec = 'coverage_unknown'
                    break
                target_str = target_date.isoformat()
                if target_str in date_to_idx:
                    if feats[date_to_idx[target_str]].get('detection_count', 0) > 0:
                        consec += 1
                    else:
                        break
                else:
                    break

            days_since_prev = get_past_feature(1, 'detection_count', 'no_detection')
            if days_since_prev == 'no_detection':
                for offset in range(2, 31):
                    target_date = current_date - timedelta(days=offset)
                    if target_date not in date_set:
                        days_since_prev = 'coverage_unknown'
                        break
                    target_str = target_date.isoformat()
                    if target_str in date_to_idx:
                        if feats[date_to_idx[target_str]].get('detection_count', 0) > 0:
                            days_since_prev = offset
                            break
                    else:
                        continue
                else:
                    days_since_prev = 'no_recent_detection'

            # Detection count previous day
            det_prev = get_past_feature(1, 'detection_count', 'no_detection')
            if det_prev in ('coverage_unknown', 'no_detection'):
                detection_count_previous_day = det_prev
            else:
                detection_count_previous_day = det_prev

            # FRP previous day
            frp_prev = get_past_feature(1, 'mean_frp', 'no_detection')
            max_frp_prev = get_past_feature(1, 'max_frp', 'no_detection')

            # FRP change
            if isinstance(frp_prev, (int, float)) and feat['mean_frp'] is not None:
                frp_change = feat['mean_frp'] - frp_prev
                if frp_prev > 0:
                    frp_pct_change = (frp_change / frp_prev) * 100
                else:
                    frp_pct_change = 'div_zero'
            else:
                frp_change = frp_prev if frp_prev in ('coverage_unknown', 'no_detection', 'div_zero') else 'coverage_unknown'
                frp_pct_change = 'coverage_unknown'

            # Rolling features
            rolling_3day_det = rolling_window(3, 'detection_count', 'count')
            rolling_3day_mean_frp = rolling_window(3, 'mean_frp', 'mean')
            rolling_3day_max_frp = rolling_window(3, 'max_frp', 'max')

            rolling_7day_det = rolling_window(7, 'detection_count', 'count')
            rolling_7day_mean_frp = rolling_window(7, 'mean_frp', 'mean')
            rolling_7day_max_frp = rolling_window(7, 'max_frp', 'max')

            # Build row
            row = {
                'site_id': feat['site_id'],
                'date': feat['date'],
                'latitude': feat['latitude'],
                'longitude': feat['longitude'],
                # Base features
                'detection_count': feat['detection_count'],
                'total_frp': feat['total_frp'],
                'mean_frp': feat['mean_frp'],
                'max_frp': feat['max_frp'],
                'mean_brightness': feat['mean_brightness'],
                'max_brightness': feat['max_brightness'],
                'day_detection_count': feat['day_detection_count'],
                'night_detection_count': feat['night_detection_count'],
                'night_fraction': feat['night_fraction'],
                'low_confidence_count': feat['low_confidence_count'],
                'nominal_confidence_count': feat['nominal_confidence_count'],
                # Temporal features
                'active_today': active_today,
                'active_previous_day': active_previous_day,
                'active_previous_day_flag': active_previous_day_flag if isinstance(active_previous_day_flag, int) else active_previous_day_flag,
                'active_previous_2_days': active_previous_2_days,
                'active_previous_3_days': active_previous_3_days,
                'consecutive_active_days_before_today': consec,
                'days_since_previous_detection': days_since_prev,
                'detection_count_previous_day': detection_count_previous_day,
                'frp_previous_day': frp_prev,
                'max_frp_previous_day': max_frp_prev,
                'frp_change_vs_previous_day': frp_change,
                'frp_percent_change_vs_previous_day': frp_pct_change,
                'rolling_3day_detection_count': rolling_3day_det,
                'rolling_3day_mean_frp': rolling_3day_mean_frp,
                'rolling_3day_max_frp': rolling_3day_max_frp,
                'rolling_7day_detection_count': rolling_7day_det,
                'rolling_7day_mean_frp': rolling_7day_mean_frp,
                'rolling_7day_max_frp': rolling_7day_max_frp,
            }
            final_rows.append(row)

    # Now compute expansion target
    print("Computing expansion targets...")

    # First, compute spatial footprint per site/date
    site_date_footprint = {}
    for grid_id, date_dets in grid_date_detections.items():
        center_lat = float(grid_id.split('_')[1]) / 100 * GRID_RESOLUTION
        center_lon = float(grid_id.split('_')[2]) / 100 * GRID_RESOLUTION

        for date, dets in date_dets.items():
            # Compute footprint: convex hull area or max pairwise distance
            coords = [(d['latitude'], d['longitude']) for d in dets]
            if len(coords) == 1:
                max_dist = 0.0
            else:
                max_dist = 0.0
                for i in range(len(coords)):
                    for j in range(i+1, len(coords)):
                        dist = haversine_km(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
                        max_dist = max(max_dist, dist)

            # Use string date for consistent key format
            date_str = date.isoformat()
            key = (f"grid_{grid_id}", date_str)
            site_date_footprint[key] = max_dist

    # Compute expansion target
    # Use a separate list for threshold computation to avoid mixing with final_rows
    expansion_data = []

    for feat in site_date_features:
        site_id = feat['site_id']
        date = feat['date']
        current_date = datetime.fromisoformat(date).date()

        # Current footprint
        curr_key = (feat['site_id'], date)
        curr_footprint = site_date_footprint.get(curr_key, 0.0)

        # Next day footprint
        next_date = current_date + timedelta(days=1)
        next_str = next_date.isoformat()
        next_footprint = site_date_footprint.get((feat['site_id'], next_str), None)

        if next_footprint is None:
            # Check if next date has coverage
            if next_date not in DATE_SET:
                target = 'coverage_unknown'
            else:
                next_key = (feat['site_id'], next_str)
                if next_key not in site_date_footprint:
                    target = 0  # no detection = no expansion
                else:
                    target = 0  # should not happen
        else:
            # Calculate expansion
            if curr_footprint == 0:
                target = 1 if next_footprint > 0 else 0
            else:
                # Use percentile-based threshold: 75th percentile of observed expansion ratios
                ratio = next_footprint / curr_footprint
                target = 1 if ratio > 1.5 else 0  # placeholder, will refine

        # We'll compute threshold after collecting all ratios
        expansion_data.append((feat, next_footprint if next_date in DATE_SET else None, curr_footprint))

    # Compute expansion ratios for threshold selection
    ratios = []
    for feat, next_fp, curr_fp in expansion_data:
        if (feat['site_id'], feat['date']) in site_date_footprint and feat['date'] in [str(d) for d in ALL_DATES[:-1]]:
            next_date = datetime.fromisoformat(feat['date']).date() + timedelta(days=1)
            if next_date in DATE_SET:
                key = (feat['site_id'], next_date.isoformat())
                if key in site_date_footprint and site_date_footprint[key] > 0:
                    curr = site_date_footprint.get((feat['site_id'], feat['date']), 0)
                    if curr > 0:
                        ratio = site_date_footprint[key] / curr
                        ratios.append(ratio)

    print(f"Expansion ratios computed: {len(ratios)}")
    if ratios:
        ratios.sort()
        p75 = ratios[int(len(ratios) * 0.75)]
        p90 = ratios[int(len(ratios) * 0.90)]
        print(f"P75: {p75:.3f}, P90: {p90:.3f}")
        threshold = p75
    else:
        threshold = 1.5

    print(f"Selected expansion threshold: {threshold:.3f} (75th percentile)")

    # Build final dataset
    print("Building final dataset...")
    output_rows = []

    # Use final_rows which already contain all temporal features
    for row in final_rows:
        site_id = row['site_id']
        date = row['date']
        current_date = datetime.fromisoformat(date).date()
        next_date = current_date + timedelta(days=1)

        # Target
        next_fp = site_date_footprint.get((row['site_id'], next_date.isoformat()), None)
        curr_fp = site_date_footprint.get((row['site_id'], date), 0.0)

        if next_date not in DATE_SET:
            target = 'coverage_unknown'
        elif next_date not in DATE_SET or (row['site_id'], next_date.isoformat()) not in site_date_footprint:
            target = 0 if curr_fp > 0 else 'no_footprint'
        else:
            next_fp = site_date_footprint.get((row['site_id'], next_date.isoformat()), 0.0)
            curr_fp = site_date_footprint.get((row['site_id'], date), 0.0)
            if curr_fp == 0:
                target = 1 if next_fp > 0 else 0
            else:
                ratio = next_fp / curr_fp if curr_fp > 0 else 1.0
                target = 1 if ratio > threshold else 0

        # Build complete output row from the temporal feature row
        out_row = row.copy()
        out_row['target_expansion_24h'] = target
        out_row['expansion_threshold'] = threshold
        next_date = datetime.fromisoformat(row['date']).date() + timedelta(days=1)
        out_row['next_day_footprint'] = site_date_footprint.get((row['site_id'], next_date.isoformat()), None)
        out_row['current_footprint'] = site_date_footprint.get((row['site_id'], row['date']), 0.0)
        next_fp = site_date_footprint.get((row['site_id'], (datetime.fromisoformat(row['date']).date() + timedelta(days=1)).isoformat()), 0.0)
        out_row['expansion_ratio'] = next_fp / row['max_frp'] if row['max_frp'] > 0 else 'div_zero'

        output_rows.append(out_row)

    print(f"Built {len(output_rows)} output rows")

    # Write CSV
    if output_rows:
        out_path = DATA_DIR / "ml_expansion_features.csv"
        fieldnames = list(output_rows[0].keys())
        with open(DATA_DIR / "ml_expansion_features.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"Written to: {out_path}")

        # Summary
        targets = [r['target_expansion_24h'] for r in output_rows]
        pos = sum(1 for t in targets if t == 1)
        neg = sum(1 for t in targets if t == 0)
        unk = sum(1 for t in targets if t in ('coverage_unknown', 'no_footprint', 'div_zero'))
        print(f"Target distribution: positive={pos}, negative={neg}, unknown={unk}")
    else:
        print("No output rows generated")

if __name__ == "__main__":
    main()
