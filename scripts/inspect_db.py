from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "thermalguard.db"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
c = conn.cursor()

tables = c.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()
print('Tables:', [t['name'] for t in tables])

for t in tables:
    n = c.execute(f'SELECT COUNT(*) as c FROM {t["name"]}').fetchone()
    print(f'  {t["name"]}: {n["c"]} rows')

sites = c.execute('SELECT classification, COUNT(*) as c FROM sites GROUP BY classification').fetchall()
print('Sites by classification:', dict((s['classification'], s['c']) for s in sites))

alerts = c.execute('SELECT severity, status, COUNT(*) as c FROM alerts GROUP BY severity, status').fetchall()
print('Alerts:', [(a['severity'], a['status'], a['c']) for a in alerts])

polys = c.execute('SELECT kind, COUNT(*) as c FROM polygons GROUP BY kind').fetchall()
print('Polygons:', dict((p['kind'], p['c']) for p in polys))

sample = c.execute('SELECT site_id, classification, confidence, severity, is_anomalous, max_frp, d_industrial_m, d_agri_m, explanation FROM sites LIMIT 5').fetchall()
for s in sample:
    print(f'  {s["site_id"]}: {s["classification"]} conf={s["confidence"]} sev={s["severity"]} anomalous={s["is_anomalous"]} frp={s["max_frp"]:.1f} d_ind={s["d_industrial_m"]:.0f} d_agri={s["d_agri_m"]:.0f} | {s["explanation"][:80]}...')
