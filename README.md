# ThermalGuard (SIH26162) — Local Build

Smart fire classification + alerting system. Detects industrial fires vs. agricultural
burns vs. wildfires from NASA FIRMS satellite detections, enriched with OSM land-use
polygons, visualized on a Leaflet dashboard, and alerting via SMS (Twilio) and Web Push.

## Quick start (no cloud)

```powershell
# 1. Setup
cp .env.example .env          # fill keys if you have them (optional for offline demo)
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt

# 2. Generate local seed data (if you don't have a FIRMS key pre-fetched)
python scripts\generate_seed_data.py

# 3. Start everything
.\start_dev.ps1
```

- Backend API:  http://localhost:8000  (docs: /docs)
- Dashboard:    http://localhost:5173
- Public page:  http://localhost:5174

Or with docker: `docker-compose up --build`

## Data

- `data/firms_seed.csv`   — pre-fetched/synthesised VIIRS detections (7-10 days) across
  Jharia coalfield, Jamnagar refinery belt, Punjab stubble window, and an Uttarakhand wildfire.
- `data/osm_seed.geojson` — pre-fetched OSM land-use polygons (industrial / agricultural /
  residential / forest) for the same bounding boxes.

Use `scripts\fetch_firms.py` / `scripts\fetch_osm.py` with a real `FIRMS_MAP_KEY` in `.env`
to produce real seed data; otherwise the generator produces deterministic, realistic data.

## Modules (Section 5 success criteria)

| Module | How to verify |
|---|---|
| Data ingestion | `SELECT COUNT(*) FROM detections` == CSV row count |
| Rule classifier | 3 seed regions each labelled by dominant class (see generator output) |
| Registry | re-running ingest never duplicates a site within 1km |
| GIS map | dashboard filters by classification hide/show points |
| Alert engine | severe detection appears in gov console within ~2s polling |
| SMS/Web Push | Confirm in console → real SMS (if Twilio keys set) + browser push |
| Public page | "I need help" writes a row visible in the console needs-map |

## .env contract

```
FIRMS_MAP_KEY, TWILIO_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, CORS_ORIGINS, DB_PATH
```