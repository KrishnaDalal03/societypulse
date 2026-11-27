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
<html lang="en" class="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SocietyPulse — Command Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet" />
  <style>
    :root {
      --primary: #89CEFF;
      --on-primary: #00344D;
      --primary-container: #004C6E;
      --on-primary-container: #C9E6FF;
      --secondary: #A5CBE9;
      --tertiary: #FFB86E;
      --tertiary-container: #492900;
      --on-tertiary-container: #FFDCBD;
      --error: #FFB4AB;
      --error-container: #690005;
      --on-error-container: #FFDAD6;
      --success: #4ADE80;
      --success-container: #0F3D24;
      --on-success-container: #BBF7D0;
      --warning: #FBBF24;
      --warning-container: #452806;
      --on-warning-container: #FDE68A;
      --bg: #0F1418;
      --surface-lowest: #0A0F13;
      --surface-low: #171C20;
      --surface: #1B2024;
      --surface-high: #252B2F;
      --surface-highest: #30353A;
      --on-surface: #DEE3E9;
      --on-surface-variant: #BEC8D2;
      --outline: #88929B;
      --outline-variant: #2C353D;
      --font-sans: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: "DM Mono", monospace;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 20px;
      background: var(--bg);
      color: var(--on-surface);
    }

    .material-symbols-outlined {
      display: inline-block;
      width: 1em;
      height: 1em;
      line-height: 1 !important;
      box-sizing: content-box;
      overflow: hidden;
      white-space: nowrap;
      direction: ltr;
      vertical-align: middle;
      font-size: 18px;
    }

    .mono { font-family: var(--font-mono); }

    header {
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(15, 20, 24, 0.92);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--outline-variant);
    }

    .header-inner {
      max-width: 1280px;
      margin: 0 auto;
      padding: 14px 20px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .brand { display: flex; align-items: center; gap: 12px; }
    .brand-badge {
      width: 38px; height: 38px; border-radius: 10px;
      background: var(--primary-container); color: var(--primary);
      display: grid; place-items: center; font-weight: 700;
    }
    .brand-title { font-size: 18px; font-weight: 700; letter-spacing: -0.2px; }
    .brand-sub { font-size: 12px; color: var(--on-surface-variant); }

    .controls-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }

    .wing-group {
      display: flex; flex-wrap: wrap; gap: 4px;
      background: var(--surface-low); padding: 4px;
      border-radius: 10px; border: 1px solid var(--outline-variant);
    }

    .wing-btn {
      background: transparent; color: var(--on-surface-variant);
      border: 0; border-radius: 7px; padding: 6px 10px;
      font-size: 12px; font-weight: 600; cursor: pointer;
    }
    .wing-btn.active { background: var(--primary-container); color: var(--on-primary-container); }

    button {
      font-family: var(--font-sans);
      border: 0; border-radius: 10px;
      padding: 8px 14px; font-size: 13px; font-weight: 600;
      cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    }

    .btn-primary { background: var(--primary); color: var(--on-primary); }
    .btn-surface { background: var(--surface-high); color: var(--on-surface); border: 1px solid var(--outline-variant); }
    .btn-danger { background: var(--error-container); color: var(--on-error-container); border: 1px solid rgba(255,180,171,0.25); }
    .btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 8px; }

    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }
    @media (max-width: 900px) { .stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 480px) { .stats-grid { grid-template-columns: 1fr; } }

    .stat-card {
      background: var(--surface);
      border: 1px solid var(--outline-variant);
      border-radius: 14px;
      padding: 16px;
    }
    .stat-label { font-size: 12px; color: var(--on-surface-variant); display: flex; justify-content: space-between; align-items: center; }
    .stat-val { font-size: 30px; line-height: 36px; font-weight: 700; margin-top: 8px; letter-spacing: -0.5px; }

    .main-grid {
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 20px;
      align-items: start;
    }
    .col-left { grid-column: span 7; display: flex; flex-direction: column; gap: 12px; }
    .col-right { grid-column: span 5; display: flex; flex-direction: column; gap: 12px; }
    @media (max-width: 960px) {
      .col-left, .col-right { grid-column: span 12; }
    }

    .panel {
      background: var(--surface);
      border: 1px solid var(--outline-variant);
      border-radius: 14px;
      padding: 16px;
    }

    .panel-head {
      display: flex; justify-content: space-between; align-items: center;
      gap: 10px; margin-bottom: 14px; flex-wrap: wrap;
    }
    .panel-title { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px; }

    .inc-card {
      background: var(--surface-low);
      border: 1px solid var(--outline-variant);
      border-radius: 12px;
      padding: 14px;
      margin-bottom: 10px;
      cursor: pointer;
      transition: border-color 0.15s ease, background 0.15s ease;
    }
    .inc-card:hover { border-color: var(--primary); background: var(--surface-high); }
    .inc-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
    .inc-title { font-size: 15px; font-weight: 600; }
    .inc-summary { font-size: 13px; color: var(--on-surface-variant); margin-top: 6px; }
    .inc-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; align-items: center; }

    .chip {
      font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 999px;
      background: var(--surface-highest); color: var(--on-surface-variant);
    }
    .chip-high { background: var(--error-container); color: var(--on-error-container); }
    .chip-med { background: var(--warning-container); color: var(--on-warning-container); }
    .chip-low { background: var(--success-container); color: var(--on-success-container); }
    .chip-info { background: var(--primary-container); color: var(--on-primary-container); }

    .tabs {
      display: flex; gap: 6px;
      background: var(--surface-low); padding: 4px; border-radius: 10px;
      border: 1px solid var(--outline-variant); margin-bottom: 12px;
    }
    .tab-btn {
      flex: 1; justify-content: center;
      background: transparent; color: var(--on-surface-variant);
      border-radius: 7px; padding: 7px 10px; font-size: 12px;
    }
    .tab-btn.active { background: var(--surface-high); color: var(--on-surface); }

    .item-row {
      background: var(--surface-low);
      border: 1px solid var(--outline-variant);
      border-radius: 10px;
      padding: 11px 12px;
      margin-bottom: 8px;
    }
    .item-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; }
    .item-sub { font-size: 12px; color: var(--on-surface-variant); margin-top: 4px; }

    .empty {
      text-align: center; padding: 24px 12px;
      color: var(--on-surface-variant); font-size: 13px;
      border: 1px dashed var(--outline-variant); border-radius: 12px;
    }

    .modal-backdrop {
      position: fixed; inset: 0; z-index: 50;
      background: rgba(10, 15, 19, 0.78);
      display: none; align-items: center; justify-content: center; padding: 16px;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      width: 100%; max-width: 540px; max-height: 90vh; overflow-y: auto;
      background: var(--surface); border: 1px solid var(--outline-variant);
      border-radius: 16px; padding: 20px;
    }
    .modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .modal-title { font-size: 17px; font-weight: 700; }

    label { display: block; font-size: 12px; color: var(--on-surface-variant); margin: 10px 0 4px; font-weight: 500; }
    input, select, textarea {
      width: 100%; font-family: var(--font-sans); font-size: 14px;
      background: var(--surface-low); color: var(--on-surface);
      border: 1px solid var(--outline-variant); border-radius: 10px; padding: 9px 12px;
    }
    textarea { min-height: 84px; resize: vertical; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; flex-wrap: wrap; }

    .banner-err {
      background: var(--error-container); color: var(--on-error-container);
      border: 1px solid rgba(255,180,171,0.35); border-radius: 12px;
      padding: 12px 14px; display: none; justify-content: space-between; align-items: center; gap: 10px;
    }
    .banner-err.show { display: flex; }
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <div class="brand">
        <div class="brand-badge"><span class="material-symbols-outlined">apartment</span></div>
        <div>
          <div class="brand-title" id="societyName">SocietyPulse</div>
          <div class="brand-sub">Resident Triage &amp; Incident Command</div>
        </div>
      </div>

      <div class="controls-row">
        <div class="wing-group" id="wingFilter"></div>
        <button type="button" class="btn-primary" onclick="openTriage()">
          <span class="material-symbols-outlined">add_comment</span> Triage Message
        </button>
        <button type="button" class="btn-surface" onclick="loadState()">
          <span class="material-symbols-outlined">refresh</span> Sync
        </button>
        <button type="button" class="btn-danger" onclick="resetState()">
          <span class="material-symbols-outlined">restart_alt</span> Reset
        </button>
      </div>
    </div>
  </header>

  <main>
    <div class="banner-err" id="errBanner">
      <span id="errText"></span>
      <button type="button" class="btn-surface btn-sm" onclick="loadState()">Retry</button>
    </div>

    <section class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Active Incidents <span class="material-symbols-outlined" style="color:var(--primary)">warning</span></div>
        <div class="stat-val" id="mActive">0</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Open Tickets <span class="material-symbols-outlined" style="color:var(--tertiary)">confirmation_number</span></div>
        <div class="stat-val" id="mTickets">0</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Duplicates Suppressed <span class="material-symbols-outlined" style="color:var(--secondary)">filter_alt</span></div>
        <div class="stat-val" id="mSuppressed">0</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">SLA High Urgency <span class="material-symbols-outlined" style="color:var(--error)">schedule</span></div>
        <div class="stat-val" id="mSla">0</div>
      </div>
    </section>

    <section class="main-grid">
      <div class="col-left">
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title">
              <span class="material-symbols-outlined" style="color:var(--primary)">crisis_alert</span>
              Master Incidents
            </div>
            <button type="button" class="btn-surface btn-sm" id="resolvedToggleBtn" onclick="toggleResolved()">
              Show Resolved (0)
            </button>
          </div>
          <div id="incidentsList"></div>
        </div>
      </div>

      <div class="col-right">
        <div class="panel">
          <div class="panel-title" style="margin-bottom:12px;">
            <span class="material-symbols-outlined" style="color:var(--secondary)">receipt_long</span>
            Operations Ledger
          </div>
          <div class="tabs">
            <button type="button" class="tab-btn active" data-tab="logs" onclick="switchTab('logs')">Logs</button>
            <button type="button" class="tab-btn" data-tab="tickets" onclick="switchTab('tickets')">Tickets</button>
            <button type="button" class="tab-btn" data-tab="residents" onclick="switchTab('residents')">Residents</button>
          </div>
          <div id="ledgerList"></div>
        </div>
      </div>
    </section>
  </main>

  <!-- Triage Modal -->
  <div class="modal-backdrop" id="triageModal">
    <div class="modal">
      <div class="modal-head">
        <div class="modal-title">New Resident Triage</div>
        <button type="button" class="btn-surface btn-sm" onclick="closeModal('triageModal')">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>
      <form id="triageForm">
        <label>Resident / Sender</label>
        <input name="sender" id="triageSender" placeholder="e.g., +919820112233 or Aarav Sharma" required />
        <label>Channel</label>
        <select name="channel" id="triageChannel">
          <option value="whatsapp">whatsapp</option>
          <option value="app">app</option>
          <option value="sms">sms</option>
        </select>
        <label>Message</label>
        <textarea name="message" id="triageMessage" placeholder="Describe the issue (wing, flat, urgency)..." required></textarea>
        <div class="modal-actions">
          <button type="button" class="btn-surface" onclick="closeModal('triageModal')">Cancel</button>
          <button type="submit" class="btn-primary" id="triageSubmitBtn">Submit Triage</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Incident Detail Modal -->
  <div class="modal-backdrop" id="detailModal">
    <div class="modal">
      <div class="modal-head">
        <div class="modal-title" id="detailTitle">Incident</div>
        <button type="button" class="btn-surface btn-sm" onclick="closeModal('detailModal')">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>
      <div id="detailBody"></div>
      <label>Incident Status</label>
      <select id="detailStatus">
        <option value="active">active</option>
        <option value="resolved">resolved</option>
      </select>
      <label>Vendor Status</label>
      <input id="detailVendor" placeholder="e.g., Plumber dispatched" />
      <div class="modal-actions">
        <button type="button" class="btn-surface" onclick="closeModal('detailModal')">Close</button>
        <button type="button" class="btn-primary" onclick="saveIncident()">Save Changes</button>
      </div>
    </div>
  </div>

  <script>
    let appState = null;
    let selectedWing = "all";
    let showResolved = false;
    let activeTab = "logs";
    let editingIncidentId = null;

    function esc(v) {
      return String(v ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }

    function showErr(msg) {
      const el = document.getElementById("errBanner");
      document.getElementById("errText").textContent = msg;
      el.classList.add("show");
    }
    function clearErr() {
      document.getElementById("errBanner").classList.remove("show");
    }

    function openModal(id) { document.getElementById(id).classList.add("open"); }
    function closeModal(id) { document.getElementById(id).classList.remove("open"); }

    function openTriage(prefillSender = "") {
      document.getElementById("triageSender").value = prefillSender || "";
      document.getElementById("triageMessage").value = "";
      openModal("triageModal");
    }

    function toggleResolved() {
      showResolved = !showResolved;
      renderAll();
    }

    function switchTab(tab) {
      activeTab = tab;
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
      renderLedger();
    }

    function getWings(st) {
      const s = new Set(["all"]);
      for (const x of (st.master_incidents || [])) if (x.wing) s.add(x.wing);
      for (const x of (st.tickets || [])) if (x.wing) s.add(x.wing);
      for (const x of (st.residents || [])) if (x.wing) s.add(x.wing);
      return Array.from(s);
    }

    function matchesWing(item) {
      if (selectedWing === "all") return true;
      return (item.wing || "") === selectedWing;
    }

    function renderWings() {
      const wings = getWings(appState || {});
      document.getElementById("wingFilter").innerHTML = wings.map(w => `
        <button type="button" class="wing-btn ${selectedWing === w ? "active" : ""}" onclick="setWing('${esc(w)}')">
          ${w === "all" ? "All Wings" : "Wing " + esc(w)}
        </button>
      `).join("");
    }

    function setWing(w) {
      selectedWing = w;
      renderAll();
    }

    function renderStats() {
      const st = appState || {};
      const activeInc = (st.master_incidents || []).filter(i => (i.status || "active") === "active" && matchesWing(i));
      const openTkts = (st.tickets || []).filter(t => (t.status || "open") !== "resolved" && matchesWing(t));
      const logs = (st.execution_logs || []).filter(l => matchesWing(l));
      const suppressed = logs.filter(l => l.action === "duplicate_suppressed" || l.status === "duplicate_suppressed").length;
      const slaUrgent = activeInc.filter(i => {
        const sev = String(i.severity || "").toUpperCase();
        const rem = i.sla_minutes_remaining;
        return sev === "HIGH" && (rem === null || rem === undefined || Number(rem) <= 20);
      }).length;

      document.getElementById("mActive").textContent = activeInc.length;
      document.getElementById("mTickets").textContent = openTkts.length;
      document.getElementById("mSuppressed").textContent = suppressed;
      document.getElementById("mSla").textContent = slaUrgent;
    }

    function sevChipClass(sev) {
      const s = String(sev || "").toUpperCase();
      if (s === "HIGH" || s === "CRITICAL") return "chip chip-high";
      if (s === "MEDIUM" || s === "MED") return "chip chip-med";
      return "chip chip-low";
    }

    function renderIncidents() {
      const allInc = (appState?.master_incidents || []).filter(matchesWing);
      const resolvedCnt = allInc.filter(i => i.status === "resolved").length;
      const btn = document.getElementById("resolvedToggleBtn");
      btn.textContent = showResolved ? `Hide Resolved (${resolvedCnt})` : `Show Resolved (${resolvedCnt})`;

      const list = allInc.filter(i => showResolved ? true : (i.status || "active") === "active");
      const container = document.getElementById("incidentsList");

      if (!list.length) {
        container.innerHTML = `<div class="empty">No master incidents match the current filter.</div>`;
        return;
      }

      container.innerHTML = list.map(inc => {
        const id = inc.id || inc.incident_id || "";
        const flats = Array.isArray(inc.affected_flats) ? inc.affected_flats.join(", ") : "";
        return `
          <div class="inc-card" onclick="openDetail('${esc(id)}')">
            <div class="inc-top">
              <div class="inc-title">${esc(inc.title || id || "Incident")}</div>
              <span class="${sevChipClass(inc.severity)}">${esc(inc.severity || "NORMAL")}</span>
            </div>
            ${inc.summary ? `<div class="inc-summary">${esc(inc.summary)}</div>` : ""}
            <div class="inc-meta">
              <span class="chip chip-info">${esc(inc.status || "active")}</span>
              ${inc.wing ? `<span class="chip">Wing ${esc(inc.wing)}</span>` : ""}
              ${flats ? `<span class="chip mono">Flats: ${esc(flats)}</span>` : ""}
              ${inc.vendor_status ? `<span class="chip">${esc(inc.vendor_status)}</span>` : ""}
            </div>
          </div>
        `;
      }).join("");
    }

    function renderLedger() {
      const st = appState || {};
      const box = document.getElementById("ledgerList");

      if (activeTab === "logs") {
        const logs = (st.execution_logs || []).filter(matchesWing).slice().reverse();
        if (!logs.length) {
          box.innerHTML = `<div class="empty">No execution logs yet.</div>`;
          return;
        }
        box.innerHTML = logs.map(l => `
          <div class="item-row">
            <div class="item-head">
              <span>${esc(l.status || l.action || "logged")}</span>
              <span class="chip mono">${esc(l.triage_source || "pipeline")}</span>
            </div>
            <div class="item-sub mono">
              ${l.ticket_id ? `tkt: ${esc(l.ticket_id)} ` : ""}${l.master_incident_id ? `→ ${esc(l.master_incident_id)}` : ""}
            </div>
            ${l.sender ? `<div class="item-sub">Sender: ${esc(l.sender)}</div>` : ""}
          </div>
        `).join("");
        return;
      }

      if (activeTab === "tickets") {
        const tickets = (st.tickets || []).filter(matchesWing).slice().reverse();
        if (!tickets.length) {
          box.innerHTML = `<div class="empty">No tickets recorded yet.</div>`;
          return;
        }
        box.innerHTML = tickets.map(t => `
          <div class="item-row">
            <div class="item-head">
              <span>${esc(t.summary || t.message || t.id || t.ticket_id || "Ticket")}</span>
              <span class="chip">${esc(t.status || "open")}</span>
            </div>
            <div class="item-sub">
              ${t.wing ? `Wing ${esc(t.wing)} · ` : ""}${t.sender ? `From ${esc(t.sender)}` : ""}
            </div>
          </div>
        `).join("");
        return;
      }

      const residents = (st.residents || []).filter(matchesWing);
      if (!residents.length) {
        box.innerHTML = `<div class="empty">No residents in this wing.</div>`;
        return;
      }
      box.innerHTML = residents.map(r => {
        const label = r.phone || r.name || r.id || "";
        return `
          <div class="item-row" style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
            <div>
              <div class="item-head">${esc(r.name || label)}</div>
              <div class="item-sub">${r.wing ? `Wing ${esc(r.wing)}` : ""} ${r.flat ? `· Flat ${esc(r.flat)}` : ""} ${r.phone ? `· ${esc(r.phone)}` : ""}</div>
            </div>
            <button type="button" class="btn-surface btn-sm" onclick="openTriage('${esc(label)}')">Test</button>
          </div>
        `;
      }).join("");
    }

    function openDetail(id) {
      const inc = (appState?.master_incidents || []).find(x => (x.id || x.incident_id) === id);
      if (!inc) return;
      editingIncidentId = id;
      document.getElementById("detailTitle").textContent = inc.title || id;
      document.getElementById("detailStatus").value = inc.status || "active";
      document.getElementById("detailVendor").value = inc.vendor_status || "";
      document.getElementById("detailBody").innerHTML = `
        <div class="item-row">
          <div class="item-sub mono">ID: ${esc(id)}</div>
          <div class="item-sub">Severity: <strong>${esc(inc.severity || "NORMAL")}</strong> · Wing: <strong>${esc(inc.wing || "-")}</strong></div>
          ${inc.summary ? `<div class="item-sub" style="margin-top:8px;">${esc(inc.summary)}</div>` : ""}
        </div>
      `;
      openModal("detailModal");
    }

    async function saveIncident() {
      if (!editingIncidentId) return;
      clearErr();
      try {
        const r = await fetch(`/incidents/${encodeURIComponent(editingIncidentId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: document.getElementById("detailStatus").value,
            vendor_status: document.getElementById("detailVendor").value
          })
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "Failed to update incident");
        appState = data.state || data;
        closeModal("detailModal");
        renderAll();
      } catch (e) {
        showErr(e.message);
      }
    }

    function renderAll() {
      if (appState?.society_name) {
        document.getElementById("societyName").textContent = appState.society_name;
      }
      renderWings();
      renderStats();
      renderIncidents();
      renderLedger();
    }

    async function loadState() {
      clearErr();
      try {
        const r = await fetch("/state");
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "Failed to fetch state");
        appState = data.state || data;
        renderAll();
      } catch (e) {
        showErr(e.message);
      }
    }

    async function resetState() {
      clearErr();
      try {
        const r = await fetch("/reset", { method: "POST" });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "Failed to reset state");
        appState = data.state || data;
        renderAll();
      } catch (e) {
        showErr(e.message);
      }
    }

    document.getElementById("triageForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      clearErr();
      const btn = document.getElementById("triageSubmitBtn");
      btn.disabled = true;
      try {
        const r = await fetch("/triage", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sender: document.getElementById("triageSender").value.trim(),
            channel: document.getElementById("triageChannel").value,
            message: document.getElementById("triageMessage").value.trim()
          })
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "Triage request failed");
        appState = data.state || data;
        closeModal("triageModal");
        renderAll();
      } catch (err) {
        showErr(err.message);
      } finally {
        btn.disabled = false;
      }
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


