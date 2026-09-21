import { useEffect, useState } from "react";
import axios from "axios";

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

function provenanceBadge(source, isSynthetic) {
  if (!isSynthetic && source?.includes("firms")) return PROVENANCE_BADGE.firms;
  if (isSynthetic && source?.includes("firms")) return PROVENANCE_BADGE.synthetic_firms;
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

function useGeolocation() {
  const [pos, setPos] = useState(null);
  const locate = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (p) => setPos({ lat: +p.coords.latitude.toFixed(5), lon: +p.coords.longitude.toFixed(5) }),
      () => setPos({ lat: 23.76, lon: 86.42 })
    );
  };
  return [pos, locate];
}

export default function App() {
  const [alerts, setAlerts] = useState([]);
  const [activeCount, setActiveCount] = useState(0);
  const [pos, locate] = useGeolocation();
  const [message, setMessage] = useState("");
  const [kind, setKind] = useState("help");
  const [sent, setSent] = useState(null);
  const [pushStatus, setPushStatus] = useState("off");

  useEffect(() => {
    const load = async () => {
      const { data } = await axios.get("/api/alerts").catch(() => ({ data: [] }));
      setAlerts(data.slice(0, 20));
      setActiveCount(data.filter((a) => a.status === "alert_triggered").length);
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const enablePush = async () => {
    try {
      const reg = await navigator.serviceWorker.register("/sw.js");
      const { data } = await axios.get("/api/push/vapid-public-key");
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(data.publicKey),
      });
      await axios.post("/api/push/subscribe", sub.toJSON());
      setPushStatus("on");
    } catch (_) {
      setPushStatus("error");
    }
  };

  const submit = async (k) => {
    const lat = pos?.lat ?? 23.76;
    const lon = pos?.lon ?? 86.42;
    setKind(k);
    try {
      const { data } = await axios.post("/api/needs", {
        kind: k, lat, lon, message: message || (k === "safe" ? "I am safe." : "Please check on me."),
      });
      setSent(data);
      setMessage("");
    } catch (e) {
      setSent({ error: e.message });
    }
  };

  return (
    <div className="public">
      <header className="pubhead">
        <div><b>🛰️ NOCTRA</b><span>Public safety portal — live fire advisories</span></div>
        <button className={`pushbtn ${pushStatus === "on" ? "on" : ""}`} onClick={enablePush} disabled={pushStatus === "on"}>
          {pushStatus === "on" ? "Notifications enabled 🔔" : "Enable notification alerts"}
        </button>
      </header>

      <div className="pubhero">
        <h2>{activeCount > 0 ? `${activeCount} active alert${activeCount > 1 ? "s" : ""} near you` : "No active fire alerts"}</h2>
        <p>Generated from satellite thermal detections, classified by the NOCTRA engine and confirmed by the district control room.</p>
      </div>

      <main className="pubgrid">
        <section>
          <h3>Active advisories</h3>
          {alerts.map((a) => (
            <div key={a.id} className={`advisory ${a.severity} ${a.status}`}>
              <div className="advhead">
                <span className={`badge b-${a.severity}`}>{a.severity.toUpperCase()}</span>
                <b>{CLASS_LABELS[a.site?.classification] ?? "Fire"}</b>
                {a.site && (
                  <>
                    <span className="prov-badge" style={{ background: provenanceBadge(a.site.source, a.site.is_synthetic).color }}>
                      {provenanceBadge(a.site.source, a.site.is_synthetic).label}
                    </span>
                    <span className="prov-badge" style={{ background: coverageBadge(a.site.coverage_status).color }}>
                      {coverageBadge(a.site.coverage_status).label}
                    </span>
                  </>
                )}
                <span className="small">{a.site ? `${a.site.lat.toFixed(3)}, ${a.site.lon.toFixed(3)}` : ""}</span>
              </div>
              <p>{a.cap?.info?.[0]?.headline ?? "Thermal anomaly under observation."}</p>
              <p className="small">{a.cap?.info?.[0]?.description ?? ""}</p>
            </div>
          ))}
          {!alerts.length && <div className="muted">No advisories detected yet.</div>}
        </section>

        <section>
          <h3>Check in with the district control room</h3>
          <div className="statusbox">
            <p className="small">Your location{pos ? `: ${pos.lat}, ${pos.lon}` : " (not shared yet)"}</p>
            <button className="loc" onClick={locate}>📍 Use my location</button>
            <textarea placeholder="Message (optional)" value={message} onChange={(e) => setMessage(e.target.value)} rows={2} />
            <div className="btnrow">
              <button className="btn-safe" onClick={() => submit("safe")}>✅ I'm safe</button>
              <button className="btn-help" onClick={() => submit("help")}>❗ I need help</button>
              <button className="btn-sos" onClick={() => submit("sos")}>🆘 SOS emergency</button>
            </div>
            {sent && (
              <div className="sent">
                {sent.error ? `Send failed: ${sent.error}` : `✓ Sent (ref #${sent.id}). The control room has been notified.`}
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="pubfoot">
        NOCTRA · SIH26162 · CAP 1.2 compliant payloads · SMS via Twilio · Web Push
      </footer>
    </div>
  );
}