import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Polygon, Marker, Popup, useMap } from "react-leaflet";
import axios from "axios";

axios.defaults.headers.common["X-API-Key"] = import.meta.env.VITE_API_KEY || "noctra-dev-key-2026";

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
const NEED_ICON_COLOR = "#3a86ff";

function provenanceBadge(source, isSynthetic) {
  if (!isSynthetic && source.includes("firms")) return PROVENANCE_BADGE.firms;
  if (isSynthetic && source.includes("firms")) return PROVENANCE_BADGE.synthetic_firms;
  return PROVENANCE_BADGE.synthetic;
}

function coverageBadge(coverageStatus) {
  return COVERAGE_BADGE[coverageStatus] || COVERAGE_BADGE.unknown;
}

function urlBase64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

function MapViewController({ targetLocation }) {
  const map = useMap();
  useEffect(() => {
    window.__tgMap = map;
  }, [map]);
  useEffect(() => {
    if (targetLocation && targetLocation.center) {
      map.flyTo(targetLocation.center, targetLocation.zoom || 13, { duration: 1.2 });
    }
  }, [targetLocation, map]);
  return null;
}

function SatelliteImageryPanel({ siteId }) {
  const [imagery, setImagery] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    axios.get(`/api/sites/${siteId}/imagery`)
      .then((r) => { if (active) { setImagery(r.data); setLoading(false); } })
      .catch(() => { if (active) { setImagery([]); setLoading(false); } });
    return () => { active = false; };
  }, [siteId]);

  if (loading) {
    return (
      <div className="imagery-panel">
        <div className="imagery-title">🛰️ Satellite Snapshot</div>
        <div className="hint">Checking imagery…</div>
      </div>
    );
  }

  if (!imagery || imagery.length === 0) {
    return (
      <div className="imagery-panel">
        <div className="imagery-title">🛰️ Satellite Snapshot (Sentinel-2 L2A)</div>
        <div className="imagery-placeholder-box">
          <span className="imagery-icon">🛰️</span>
          <div>No optical imagery acquired yet</div>
          <div className="imagery-subhint">Sentinel-2 STAC fetch pending (Phase 7)</div>
        </div>
      </div>
    );
  }

  return (
    <div className="imagery-panel">
      <div className="imagery-title">🛰️ Satellite Snapshots ({imagery.length})</div>
      <div className="imagery-grid">
        {imagery.map((img) => {
          const imgUrl = img.file_path ? (img.file_path.startsWith("/") ? img.file_path : `/${img.file_path}`) : null;
          return (
            <div key={img.id} className="imagery-card">
              {imgUrl ? (
                <img src={imgUrl} alt={`Sentinel-2 ${img.acquired_date}`} className="imagery-thumb" />
              ) : (
                <div className="imagery-no-thumb">No Image</div>
              )}
              <div className="imagery-meta">
                <div>Date: <b>{img.acquired_date || "—"}</b></div>
                <div>Cloud: <b>{img.cloud_cover_pct != null ? `${img.cloud_cover_pct.toFixed(1)}%` : "—"}</b></div>
                <span className="prov-badge" style={{ background: img.is_synthetic ? "#6c757d" : "#198754" }}>
                  {img.is_synthetic ? "Synthetic" : "Copernicus"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function App() {
  const [sites, setSites] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [needs, setNeeds] = useState([]);
  const [polygons, setPolygons] = useState([]);
  const [filters, setFilters] = useState({ industrial_fire: true, agricultural_burn: true, wildfire: true, other: true });
  const [provFilter, setProvFilter] = useState("real"); // 'all' | 'real' | 'demo'
  const [notes, setNotes] = useState({});
  const [toast, setToast] = useState(null);
  const [pushStatus, setPushStatus] = useState("off");
  const errorShown = useRef({});

  const [targetLocation, setTargetLocation] = useState(null);
  const [selectedSiteId, setSelectedSiteId] = useState(null);
  const markerRefs = useRef({});
  useEffect(() => {
    window.__tgMarkerRefs = markerRefs.current;
  });

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

  const handleAlertClick = (alert) => {
    if (alert.site && alert.site.lat != null && alert.site.lon != null) {
      setTargetLocation({ center: [alert.site.lat, alert.site.lon], zoom: 13, id: Date.now() });
      setSelectedSiteId(alert.site.site_id);
      if (markerRefs.current[alert.site.site_id]) {
        markerRefs.current[alert.site.site_id].openPopup();
      }
    }
  };

  useEffect(() => {
    if (selectedSiteId && markerRefs.current[selectedSiteId]) {
      markerRefs.current[selectedSiteId].openPopup();
    }
  }, [selectedSiteId, visibleSites]);

  const transition = async (alert, action) => {
    try {
      const analystNote = notes[alert.id] || null;
      const { data } = await axios.post(`/api/alerts/${alert.id}/transition`, {
        action,
        analyst_note: analystNote,
        reviewed_by: "analyst",
      });
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

  const submitFeedback = async (alert, feedback) => {
    try {
      const analystNote = notes[alert.id] || null;
      await axios.post(`/api/alerts/${alert.id}/feedback`, {
        feedback,
        analyst_note: analystNote,
        reviewed_by: "analyst",
      });
      setToast(`Feedback logged: ${feedback === "correct" ? "👍 Verified Correct" : "👎 Misclassified"} for Alert #${alert.id}`);
    } catch (e) {
      setToast(`feedback submission failed: ${e.message}`);
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
            <p className="hint">Severe/extreme detections appear here automatically within ~2s. Click any card to locate on map.</p>
            <div className="alert-list">
              {visibleAlerts.slice(0, 30).map((a) => (
                <div key={a.id} className={`alertcard ${a.status} ${a.severity}`} onClick={() => handleAlertClick(a)} style={{ cursor: "pointer" }}>
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
                    {a.suggested_priority && (
                      <div className="prio-row small">
                        🎯 RL Priority: <b className={`prio-badge prio-${a.suggested_priority}`}>{a.suggested_priority.toUpperCase()}</b>
                        {a.suggested_priority_confidence != null ? ` (${(a.suggested_priority_confidence * 100).toFixed(0)}%)` : ""}
                      </div>
                    )}
                    {a.site?.visual_evidence && a.site.visual_evidence !== "none" && (
                      <div className={`evidence-badge evidence-${a.site.visual_evidence}`}>
                        {a.site.visual_evidence === "conflicting" ? "⚡ Visual Evidence: CONFLICTING" : "✓ Visual Evidence: CORROBORATING"}
                      </div>
                    )}
                    <div className="small">CAP msgType: {a.cap?.info?.[0]?.severity ?? "—"} / {a.cap?.info?.[0]?.urgency ?? "—"}</div>
                    {a.analyst_note && (
                      <div className="analyst-note">📝 {a.analyst_note} <span className="small">({a.reviewed_by || "analyst"})</span></div>
                    )}
                  </div>
                  <div className="feedback-row" onClick={(e) => e.stopPropagation()}>
                    <span className="small">Human review:</span>
                    {a.feedback_label ? (
                      <span className={`feedback-badge ${a.feedback_label}`}>
                        {a.feedback_label === "correct" ? "👍 Verified Correct" : "👎 Misclassified"}
                      </span>
                    ) : (
                      <div className="feedback-btns">
                        <button className="feedback-btn" title="Confirm classification is correct" onClick={(e) => { e.stopPropagation(); submitFeedback(a, "correct"); }}>👍 Correct</button>
                        <button className="feedback-btn" title="Flag misclassification" onClick={(e) => { e.stopPropagation(); submitFeedback(a, "incorrect"); }}>👎 Incorrect</button>
                      </div>
                    )}
                  </div>
                  {a.status === "alert_triggered" && (
                    <>
                      <input
                        className="note-input"
                        type="text"
                        placeholder="Add analyst note (optional)..."
                        value={notes[a.id] || ""}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })}
                      />
                      <div className="actions" onClick={(e) => e.stopPropagation()}>
                        <button className="confirm" onClick={(e) => { e.stopPropagation(); transition(a, "confirm"); }}>Confirm → SMS + Web Push</button>
                        <button className="dismiss" onClick={(e) => { e.stopPropagation(); transition(a, "dismiss"); }}>Dismiss</button>
                      </div>
                    </>
                  )}
                  {a.status !== "alert_triggered" && <div className="statussmall">{a.status}</div>}
                </div>
              ))}
              {!alerts.length && <div className="hint">Waiting for alerts…</div>}
            </div>
          </section>

          <section>
            <h3>Public needs queue</h3>
            <p className="hint">"I need help" requests from the public page land here in ~5s.</p>
            <div className="need-list">
              {needs.slice(0, 10).map((n) => (
                <div key={n.id} className="needcard">
                  <b>{n.kind === "sos" ? "🆘 SOS" : n.kind === "safe" ? "✅ I'm safe" : "❗ Need help"}</b>
                  <span>{n.lat.toFixed(4)}, {n.lon.toFixed(4)}</span>
                  <div className="small">{n.message}</div>
                </div>
              ))}
              {!needs.length && <div className="hint">No public requests yet.</div>}
            </div>
          </section>
        </aside>

        <main className="maparea">
          <MapContainer center={[23.76, 86.42]} zoom={5} scrollWheelZoom style={{ height: "100%", width: "100%" }}>
            <MapViewController targetLocation={targetLocation} />
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
              <CircleMarker key={s.site_id} ref={(el) => { if (el) markerRefs.current[s.site_id] = el; }} center={[s.lat, s.lon]}
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
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Evidence & AI Analysis</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>CNN Prediction: <b>{s.cnn_prediction ? `${s.cnn_prediction} (${(s.cnn_confidence * 100).toFixed(0)}%)` : '—'}</b></div>
                    <div>Visual Evidence: <b style={{color: s.visual_evidence === 'conflicting' ? '#f87171' : s.visual_evidence === 'corroborating' ? '#4ade80' : 'inherit'}}>{(s.visual_evidence || 'none').toUpperCase()}</b></div>
                    <div>RL Suggested Priority: <b>{(s.suggested_priority || 'routine').toUpperCase()}</b> ({s.suggested_priority_confidence != null ? (s.suggested_priority_confidence * 100).toFixed(0) + '%' : '—'})</div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Location</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>Lat: <b>{s.lat?.toFixed(5)}</b></div>
                    <div>Lon: <b>{s.lon?.toFixed(5)}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <div style={{fontSize: '12px', fontWeight: '600', marginBottom: '4px'}}>Thermal Behavior</div>
                  <div style={{fontSize: '11px', lineHeight: '1.6'}}>
                    <div>FRP Intensity: <b>{(s.frp_intensity || '—').replace('-', ' ').toUpperCase()}</b></div>
                    <div>Current FRP: <b>{s.frp_last?.toFixed(1)}</b> MW</div>
                    <div>Max FRP: <b>{s.max_frp?.toFixed(1)}</b> MW</div>
                    <div>Avg FRP: <b>{s.frp_mean?.toFixed(1)}</b> MW (±{s.frp_std?.toFixed(1)} MW)</div>
                    <div>FRP Trend: <b>{s.frp_trend?.replace('_', ' ').toUpperCase()}</b></div>
                    <div>Observations: <b>{s.detection_count ?? '—'}</b></div>
                    <div>Active Passes: <b>{s.active_pass_count ?? '—'}</b></div>
                    <div>Observation Span: <b>{s.days_span ?? '—'}</b> days</div>
                    <div>Expansion: <b>{s.expansion_magnitude !== null && s.expansion_magnitude !== undefined ? s.expansion_magnitude.toFixed(3) + ' km²' : 'insufficient data'}</b></div>
                    <div>Coverage: <b>{(s.coverage_status || 'unknown').toUpperCase()}</b></div>
                  </div>
                  <hr style={{margin: '6px 0', borderColor: '#334155'}}/>
                  <SatelliteImageryPanel siteId={s.site_id} />
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