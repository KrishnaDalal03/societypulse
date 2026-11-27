import json
from pathlib import Path
from flask import Flask, jsonify, make_response, render_template_string, request
from societypulse_stage4 import run_pipeline

app = Flask(__name__)
DATA_DIR = Path("data")


def _corsify(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
    return response


@app.after_request
def after_request(response):
    return _corsify(response)


@app.route("/<path:any_path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def options_handler(any_path=""):
    return make_response("", 204)


def _load_all_state() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = {}
    for name in ["residents", "tickets", "master_incidents", "execution_logs"]:
        p = DATA_DIR / f"{name}.json"
        state[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    return state


def _save_store(name: str, data: list | dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


@app.get("/state")
def get_state():
    return jsonify(_load_all_state()), 200


@app.post("/triage")
def post_triage():
    payload = request.get_json(force=True, silent=True) or {}
    current = _load_all_state()

    # Support either { "messages": [...] } or a single message { "sender": ..., "channel": ..., "message": ... }
    incoming = payload.get("messages") if isinstance(payload.get("messages"), list) else [payload]

    # Seed from existing tickets/incidents so repeated /triage calls accumulate cleanly
    existing_messages = [
        {
            "sender": t.get("sender", "unknown"),
            "channel": "whatsapp",
            "message": t.get("message", ""),
        }
        for t in current.get("tickets", [])
        if t.get("message")
    ]

    result = run_pipeline(existing_messages + incoming, data_dir=str(DATA_DIR))
    return jsonify(result), 200


@app.patch("/incidents/<incident_id>")
def patch_incident(incident_id: str):
    payload = request.get_json(force=True, silent=True) or {}
    incidents = _load_all_state().get("master_incidents", [])
    updated = None
    for inc in incidents:
        if inc.get("incident_id") == incident_id:
            if "status" in payload:
                inc["status"] = payload["status"]
            if "vendor_status" in payload:
                inc["vendor_status"] = payload["vendor_status"]
            updated = inc
            break
    if not updated:
        return jsonify({"error": "Incident not found"}), 404
    _save_store("master_incidents", incidents)
    return jsonify(updated), 200


@app.post("/reset")
def reset_state():
    for name in ["residents", "tickets", "master_incidents", "execution_logs"]:
        _save_store(name, [])
    return jsonify({"status": "reset", "state": _load_all_state()}), 200

MOBILE_UI = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SocietyPulse — Command Console</title>
  <style>
    :root {
      --bg: #0b1020;
      --card: #131b2e;
      --card-2: #19243d;
      --border: rgba(148, 163, 184, 0.16);
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-2: #22c55e;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(180deg, #0b1020 0%, #0f172a 100%);
      color: var(--text);
      padding: 16px;
    }
    .wrap { max-width: 820px; margin: 0 auto; }
    .top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 16px;
    }
    .brand h1 { margin: 0; font-size: 1.35rem; letter-spacing: -0.02em; }
    .brand p { margin: 2px 0 0; color: var(--muted); font-size: 0.85rem; }
    .stats { display: flex; gap: 8px; flex-wrap: wrap; }
    .pill {
      background: var(--card);
      border: 1px solid var(--border);
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .pill span { color: var(--accent); }
    .panel {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      margin-bottom: 16px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 150px;
      gap: 10px;
    }
    @media (max-width: 560px) {
      .grid { grid-template-columns: 1fr; }
    }
    label {
      display: block;
      font-size: 0.78rem;
      color: var(--muted);
      margin-bottom: 5px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    input, select, textarea {
      width: 100%;
      background: var(--card-2);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 0.95rem;
      outline: none;
    }
    input:focus, select:focus, textarea:focus {
      border-color: var(--accent);
    }
    textarea { resize: vertical; min-height: 76px; margin-top: 10px; }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 15px;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
    }
    .btn-primary { background: var(--accent); color: #061220; }
    .btn-ghost { background: var(--card-2); color: var(--text); border: 1px solid var(--border); }
    .btn-danger { background: rgba(239, 68, 68, 0.16); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.35); }
    .section-title {
      font-size: 0.95rem;
      font-weight: 700;
      margin: 0 0 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .inc-card {
      background: var(--card-2);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 10px;
    }
    .inc-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      font-weight: 700;
    }
    .badge {
      font-size: 0.74rem;
      padding: 3px 8px;
      border-radius: 999px;
      background: rgba(34, 197, 94, 0.15);
      color: #86efac;
      text-transform: uppercase;
    }
    .meta { color: var(--muted); font-size: 0.82rem; margin-top: 6px; }
    .log-item {
      font-size: 0.84rem;
      padding: 8px 10px;
      border-radius: 8px;
      background: var(--card-2);
      border: 1px solid var(--border);
      margin-bottom: 8px;
    }
    pre {
      display: none;
      background: #060913;
      color: #cbd5e1;
      padding: 12px;
      border-radius: 10px;
      overflow-x: auto;
      font-size: 0.78rem;
      border: 1px solid var(--border);
    }
    pre.show { display: block; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="brand">
        <h1>SocietyPulse</h1>
        <p>Live Society Incident Triage &amp; Clustering</p>
      </div>
      <div class="stats">
        <div class="pill">Incidents: <span id="cInc">0</span></div>
        <div class="pill">Tickets: <span id="cTkt">0</span></div>
        <div class="pill">Logs: <span id="cLog">0</span></div>
      </div>
    </div>

    <div class="panel">
      <form id="f">
        <div class="grid">
          <div>
            <label>Sender</label>
            <input name="sender" value="Resident A" required />
          </div>
          <div>
            <label>Channel</label>
            <select name="channel">
              <option value="whatsapp">whatsapp</option>
              <option value="app">app</option>
              <option value="sms">sms</option>
            </select>
          </div>
        </div>
        <label style="margin-top:10px;">Incident Message</label>
        <textarea name="message" placeholder="e.g., Water supply low in Wing B" required></textarea>
        <div class="actions">
          <button type="submit" class="btn-primary">Run Triage</button>
          <button type="button" class="btn-ghost" onclick="loadState()">Refresh</button>
          <button type="button" class="btn-ghost" onclick="toggleRaw()">Raw JSON</button>
          <button type="button" class="btn-danger" onclick="resetState()">Reset</button>
        </div>
      </form>
    </div>

    <div class="panel">
      <div class="section-title">Master Incidents</div>
      <div id="incidents">Loading...</div>
    </div>

    <div class="panel">
      <div class="section-title">Execution Logs</div>
      <div id="logs">Loading...</div>
      <pre id="raw"></pre>
    </div>
  </div>

  <script>
    const incEl = document.getElementById("incidents");
    const logEl = document.getElementById("logs");
    const rawEl = document.getElementById("raw");

    function toggleRaw() {
      rawEl.classList.toggle("show");
    }

    function render(data) {
      const state = data.state || data;
      const incidents = state.master_incidents || [];
      const tickets = state.tickets || [];
      const logs = state.execution_logs || [];

      document.getElementById("cInc").textContent = incidents.length;
      document.getElementById("cTkt").textContent = tickets.length;
      document.getElementById("cLog").textContent = logs.length;
      rawEl.textContent = JSON.stringify(data, null, 2);

      incEl.innerHTML = incidents.length ? incidents.map(i => `
        <div class="inc-card">
          <div class="inc-head">
            <span>${i.title || i.incident_id || "Incident"}</span>
            <span class="badge">${i.status || "active"}</span>
          </div>
          <div class="meta">
            ID: ${i.incident_id || "-"} · Severity: ${i.severity || "-"} · Flats: ${(i.affected_flats || []).join(", ") || "-"}
          </div>
        </div>
      `).join("") : `<div class="meta">No master incidents yet. Send a message above.</div>`;

      logEl.innerHTML = logs.length ? logs.slice().reverse().map(l => `
        <div class="log-item">
          <strong>${l.status || "logged"}</strong> · Ticket <code>${l.ticket_id || "-"}</code> → <code>${l.master_incident_id || "-"}</code>
          <div class="meta">Sender: ${l.sender || "-"} · Source: ${l.triage_source || "-"}</div>
        </div>
      `).join("") : `<div class="meta">No execution logs yet.</div>`;
    }

    async function loadState() {
      const r = await fetch("/state");
      render(await r.json());
    }

    async function resetState() {
      const r = await fetch("/reset", { method: "POST" });
      render(await r.json());
    }

    document.getElementById("f").addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = Object.fromEntries(new FormData(e.target).entries());
      const r = await fetch("/triage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      render(await r.json());
    });

    loadState();
  </script>
</body>
</html>"""


@app.get("/")
def index():
    return render_template_string(MOBILE_UI), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

