import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Polygon, Marker, Popup } from "react-leaflet";
import axios from "axios";

const CLASS_COLORS = {
  industrial_fire: "#e63946",
  agricultural_burn: "#f4a261",
  wildfire: "#9b2226",
  other: "#adb5bd",
};
const CLASS_LABELS = {
  industrial_fire: "Industrial fire",
  agricultural_burn: "Agricultural burn",
  wildfire: "Wildfire",
  other: "Other / unknown",
};
const PROVENANCE_BADGE = {
  synthetic: { label: "Demo", color: "#6c757d" },
  firms: { label: "Real", color: "#198754" },
  synthetic_firms: { label: "Mixed", color: "#fd7e14" },
};
const COVERAGE_BADGE = {
  covered: { label: "Coverage OK", color: "#198754" },
  uncertain: { label: "Coverage Uncertain", color: "#fd7e14" },
  unknown: { label: "Coverage Unknown", color: "#6c757d" },
};
const EVIDENCE_SPATIAL_LABELS = {
  polygon_containment: "Inside industrial area",
  proximity: "Near industrial area",
  none: "No relevant spatial evidence",
};
const EVIDENCE_TEMPORAL_LABELS = {
  persistent: "Persistent activity observed",
  sufficient: "Sufficient observations",
  insufficient: "Insufficient temporal evidence",
};
const EVIDENCE_INTENSITY_LABELS = {
  weak: "Weak",
  moderate: "Moderate",
  "high-moderate": "High-Moderate",
  high: "High",
  "very-high": "Very High / Extreme",
};
const EVIDENCE_SUFFICIENCY_LABELS = {
  sufficient: "Sufficient evidence",
  insufficient: "Insufficient evidence",
  conflicting: "Conflicting evidence",
};
const NEED_ICON_COLOR = "#3a86ff";

function provenanceBadge(source, isSynthetic) {
  if (!isSynthetic && source.includes("firms")) return PROVENANCE_BADGE.firms;
  if (isSynthetic && source.includes("firms")) return PROVENANCE_BADGE.synthetic_firms;
  return PROVENANCE_BADGE.synthetic;
}

function coverageBadge(coverageStatus) {
  return COVERAGE_BADGE[coverageStatus] || COVERAGE_BADGE.unknown;
}

function evidenceSpatialLabel(spatial) {
  return EVIDENCE_SPATIAL_LABELS[spatial] || EVIDENCE_SPATIAL_LABELS.none;
}

function evidenceTemporalLabel(temporal) {
  return EVIDENCE_TEMPORAL_LABELS[temporal] || EVIDENCE_TEMPORAL_LABELS.insufficient;
}

function evidenceIntensityLabel(intensity) {
  return EVIDENCE_INTENSITY_LABELS[intensity] || EVIDENCE_INTENSITY_LABELS.weak;
}

function evidenceSufficiencyLabel(sufficiency) {
  return EVIDENCE_SUFFICIENCY_LABELS[sufficiency] || EVIDENCE_SUFFICIENCY_LABELS.insufficient;
}

function urlBase64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export default function App() {
  const [sites, setSites] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [needs, setNeeds] = useState([]);
  const [polygons, setPolygons] = useState([]);
  const [filters, setFilters] = useState({ industrial_fire: true, agricultural_burn: true, wildfire: true, other: true });
  const [provFilter, setProvFilter] = useState("real"); // 'all' | 'real' | 'demo'
  const [toast, setToast] = useState(null);
  const [pushStatus, setPushStatus] = useState("off");
  const errorShown = useRef({});

  const api = (url) => axios.get(url, { timeout: 5000 }).catch((e) => {
    if (!errorShown.current[url]) {
      errorShown.current[url] = true;
      setToast(`Cannot reach ${url}: ${e.message}`);
    }
    return { data: [] };
  });

  useEffect(() => {
    (async () => {
      const poly = await axios.get("/api/polygons").catch(() => ({ data: [] }));
      if (poly.data) setPolygons(poly.data);
    })();
  }, []);

  useEffect(() => {
    const loadSites = () => api("/api/sites").then((r) => setSites(r.data));
    const loadAlerts = () => api("/api/alerts").then((r) => setAlerts(r.data));
    const loadNeeds = () => api("/api/needs").then((r) => setNeeds(r.data));
    loadSites(); loadAlerts(); loadNeeds();
    const tSite = setInterval(loadSites, 5000);
    const tAlert = setInterval(loadAlerts, 2000); // gov console updates w/o manual refresh
    const tNeed = setInterval(loadNeeds, 5000);
    return () => { clearInterval(tSite); clearInterval(tAlert); clearInterval(tNeed); };
  }, []);

  // Web Push registration (public tier)
  useEffect(() => {
    (async () => {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
      try {
        const reg = await navigator.serviceWorker.register("/sw.js");
        const { data } = await axios.get("/api/push/vapid-public-key");
        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(data.publicKey),
        });
        await axios.post("/api/push/subscribe", sub.toJSON());
        setPushStatus("on");
      } catch (e) {
        setPushStatus("error");
        console.warn("push subscribe failed", e);
      }
    })();
  }, []);

  const visibleSites = useMemo(
    () => sites.filter((s) => filters[s.classification] && matchesProvenance(s, provFilter)),
    [sites, filters, provFilter]
  );
  const visibleAlerts = useMemo(
    () => alerts.filter((a) => matchesProvenance(a.site, provFilter)),
    [alerts, provFilter]
  );
  const stats = useMemo(() => {
    const c = {};
    sites.forEach((s) => { c[s.classification] = (c[s.classification] || 0) + 1; });
    return c;
  }, [sites]);

  function matchesProvenance(site, mode) {
    if (!site) return true;
    if (mode === "all") return true;
    if (mode === "real") return site.is_synthetic === false;
    if (mode === "demo") return site.is_synthetic === true;
    return true;
  }

  const transition = async (alert, action) => {
    try {
      const { data } = await axios.post(`/api/alerts/${alert.id}/transition`, { action });
      const sms = data?.dispatched?.sms;
      const push = data?.dispatched?.push;
      setToast(
        action === "confirm"
          ? `Alert #${alert.id} confirmed. SMS: ${sms?.sent ? "sent ✓" : "not configured (offline)"} · Push: ${push?.sent} delivered`
          : `Alert #${alert.id} dismissed.`
      );
    } catch (e) {
      setToast(`transition failed: ${e.message}`);
    }
  };

  const toggleFilter = (k) => setFilters((f) => ({ ...f, [k]: !f[k] }));

  return (
    <div className="app">
      {toast && <div className="toast" onClick={() => setToast(null)}>{toast}</div>}
      <header className="topbar">
        <div className="brand">🛰️ NOCTRA <span>SIH26162 · District Control Console</span></div>
        <div className="pushbadge">Web Push: {pushStatus === "on" ? "enabled 🔔" : pushStatus === "error" ? "blocked" : "off"}</div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <section>
            <h3>Detected sites</h3>
            {Object.keys(CLASS_COLORS).map((k) => (
              <label key={k} className="filterrow">
                <input type="checkbox" checked={filters[k]} onChange={() => toggleFilter(k)} />
                <span className="dot" style={{ background: CLASS_COLORS[k] }} />
                {CLASS_LABELS[k]}
                <b>{stats[k] || 0}</b>
              </label>
            ))}
          </section>

          <section>
            <h3>Data source</h3>
            <div className="filterrow">
              <label>
                <input type="radio" name="prov" checked={provFilter === "all"} onChange={() => setProvFilter("all")} />
                <span>All</span>
              </label>
            </div>
            <div className="filterrow">
              <label>
                <input type="radio" name="prov" checked={provFilter === "real"} onChange={() => setProvFilter("real")} />
                <span className="prov-badge" style={{ background: PROVENANCE_BADGE.firms.color }}>Real Satellite</span>
              </label>
            </div>
            <div className="filterrow">
              <label>
                <input type="radio" name="prov" checked={provFilter === "demo"} onChange={() => setProvFilter("demo")} />
                <span className="prov-badge" style={{ background: PROVENANCE_BADGE.synthetic.color }}>Demo</span>
              </label>
            </div>
          </section>

          <section>
            <h3>Government alert console</h3>
            <p className="hint">Severe/extreme detections appear here automatically within ~2s.</p>
            <div className="alert-list">
              {visibleAlerts.slice(0, 30).map((a) => (
                <div key={a.id} className={`alertcard ${a.status} ${a.severity}`}>
                  <div className="alerthead">
                    <b>#{a.id}</b>
                    <span className={`sev sev-${a.severity}`}>{a.severity.toUpperCase()}</span>
                    <span className="cls">{a.site?.classification ?? "—"}</span>
                    {a.site && (
                      <span className="prov-badge" style={{ background: provenanceBadge(a.site.source, a.site.is_synthetic).color }}>
                        {provenanceBadge(a.site.source, a.site.is_synthetic).label}
                      </span>
                    )}
                  </div>
                  <div className="alertbody">
                    <div>{a.site ? `${a.site.lat.toFixed(4)}, ${a.site.lon.toFixed(4)}` : ""}</div>
                    <div className="small">{a.site?.explanation}</div>
                    <div className="small">CAP msgType: {a.cap?.info?.[0]?.severity ?? "—"} / {a.cap?.info?.[0]?.urgency ?? "—"}</div>
                  </div>
                  {a.status === "alert_triggered" && (
                    <div className="actions">
                      <button className="confirm" onClick={() => transition(a, "confirm")}>Confirm → SMS + Web Push</button>
                      <button className="dismiss" onClick={() => transition(a, "dismiss")}>Dismiss</button>
                    </div>
                  )}
                  {a.status !== "alert_triggered" && <div className="statussmall">{a.status}</div>}
                </div>
              ))}
              {!alerts.length && <div className="hint">Waiting for alerts…</div>}
            </div>
          </section>

          </aside>

        <main className="maparea">
          <MapContainer center={[23.76, 86.42]} zoom={5} scrollWheelZoom style={{ height: "100%", width: "100%" }}>
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; OpenStreetMap contributors' />
            {polygons.map((p, i) => (
              <Polygon key={`${p.kind}-${i}`} positions={p.ring} pathOptions={{
                color: p.kind === "industrial" ? "#c1121f" : p.kind === "agricultural" ? "#e9c46a" : p.kind === "residential" ? "#5f0f40" : "#2b9348",
                fillOpacity: 0.18, weight: 1.5,
              }}>
                <Popup>{p.kind} · {p.name}</Popup>
              </Polygon>
            ))}
            {visibleSites.map((s) => (
              <CircleMarker key={s.site_id} center={[s.lat, s.lon]}
                radius={Math.min(10, 4 + (s.is_anomalous ? 4 : 0))}
                pathOptions={{
                  color: CLASS_COLORS[s.classification],
                  fillColor: CLASS_COLORS[s.classification],
                  fillOpacity: s.is_anomalous ? 0.95 : 0.55,
                  weight: s.is_anomalous ? 2 : 1,
                }}>
                <Popup>
                  <b>{s.site_id}</b>
                  <span className="prov-badge" style={{ background: provenanceBadge(s.source, s.is_synthetic).color }}>
                    {provenanceBadge(s.source, s.is_synthetic).label}
                  </span>
                  <span className="prov-badge" style={{ background: coverageBadge(s.coverage_status).color }}>
                    {coverageBadge(s.coverage_status).label}
                  </span>
                  <br/>
                  <span className="dot" style={{ background: CLASS_COLORS[s.classification] }} /> {CLASS_LABELS[s.classification]}<br/>
                  Conf: {s.confidence} · Sev: <b>{s.severity}</b><br/>
                  frp: {s.max_frp?.toFixed(1)} MW · brightness: {s.brightness?.toFixed(0)}K<br/>
                  {s.explanation}<br/>
                  Last pass: {s.last_pass_date} ({s.days_since_last_pass} days ago)<br/>
                  Next expected pass: {s.next_expected_pass_date || '—'}<br/>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>What</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Type: <b>{CLASS_LABELS[s.classification]}</b></div>
                    <div>Subtype: <b>{s.evidence?.subtype || 'No evidence'}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Where</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Lat: <b>{s.lat?.toFixed(5)}</b></div>
                    <div>Lon: <b>{s.lon?.toFixed(5)}</b></div>
                    <div>Nearby: {s.evidence?.nearby_context || 'No context available'}</div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>When</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>First seen: <b>{s.first_seen}</b></div>
                    <div>Last pass: <b>{s.last_pass_date} ({s.days_since_last_pass} days ago)</b></div>
                    <div>Next expected pass: <b>{s.next_expected_pass_date || '—'}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Type</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Classification: <b>{CLASS_LABELS[s.classification]}</b></div>
                    <div>Confidence: <b>{s.confidence}</b></div>
                    <div>Severity: <b>{s.severity}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Subtype</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Subtype: <b>{s.evidence?.subtype || 'No evidence'}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Thermal Intensity</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>FRP Intensity: <b>{evidenceIntensityLabel(s.frp_intensity)}</b></div>
                    <div>Current FRP: <b>{s.frp_last?.toFixed(1)}</b> MW</div>
                    <div>Max FRP: <b>{s.max_frp?.toFixed(1)}</b> MW</div>
                    <div>Avg FRP: <b>{s.frp_mean?.toFixed(1)}</b> MW (±{s.frp_std?.toFixed(1)} MW)</div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Persistence</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Temporal: <b>{evidenceTemporalLabel(s.evidence?.temporal)}</b></div>
                    <div>Active passes: <b>{s.active_pass_count ?? '—'}</b> / 5 recent</div>
                    <div>Observation days: <b>{s.observation_days ?? '—'}</b></div>
                    <div>Consecutive days: <b>{s.consec_days ?? '—'}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Activity Change</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>FRP Trend: <b>{(s.frp_trend || '—').replace('_', ' ').toUpperCase()}</b></div>
                    <div>Expansion: <b>{s.expansion_magnitude !== null && s.expansion_magnitude !== undefined ? s.expansion_magnitude.toFixed(3) + ' km²' : 'insufficient data'}</b></div>
                    <div>Cluster expanded: <b>{s.cluster_expanded ? 'Yes' : 'No'}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Nearby Context</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Spatial: <b>{evidenceSpatialLabel(s.evidence?.spatial)}</b></div>
                    <div>Distance to industrial: <b>{s.d_industrial_m?.toFixed(0) ?? '—'} m</b></div>
                    <div>Inside industrial polygon: <b>{s.in_industrial_polygon ? 'Yes' : 'No'}</b></div>
                    <div>Distance to agricultural: <b>{s.d_agri_m?.toFixed(0) ?? '—'} m</b></div>
                    <div>Inside agricultural polygon: <b>{s.in_agri_polygon ? 'Yes' : 'No'}</b></div>
                    <div>Distance to residential: <b>{s.d_residential_m?.toFixed(0) ?? '—'} m</b></div>
                    <div>Inside residential polygon: <b>{s.in_residential_polygon ? 'Yes' : 'No'}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Wind</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Wind: <b>Not available</b></div>
                    <div className="small">Fire-spread prediction not supported</div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Why Prioritized</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>{s.evidence?.reason || 'No prioritization reason available'}</div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Authority Status</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Status: <b>Unverified</b></div>
                    <div className="small">No verification workflow completed</div>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
            {needs.filter((n) => n.kind !== "safe").map((n) => (
              <CircleMarker key={`need-${n.id}`} center={[n.lat, n.lon]} radius={7}
                pathOptions={{ color: NEED_ICON_COLOR, fillColor: NEED_ICON_COLOR, fillOpacity: 0.9 }}>
                <Popup><b>📍 {n.kind === "sos" ? "SOS" : "Need help"}</b><br/>{n.message}</Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </main>
      </div>
    </div>
  );
}