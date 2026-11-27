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
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SocietyPulse — Command Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet" />
  <style>
    :root,
    [data-theme="dark"] {
      --primary: #89CEFF;
      --on-primary: #00344D;
      --primary-container: #004C6E;
      --on-primary-container: #C9E6FF;
      --secondary: #A5CBE9;
      --tertiary: #FFB86E;
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
      --header-bg: rgba(15, 20, 24, 0.92);
      --surface-low: #171C20;
      --surface: #1B2024;
      --surface-high: #252B2F;
      --surface-highest: #30353A;
      --on-surface: #DEE3E9;
      --on-surface-variant: #BEC8D2;
      --outline-variant: #2C353D;
      --backdrop: rgba(10, 15, 19, 0.78);
    }

    [data-theme="light"] {
      --primary: #006591;
      --on-primary: #FFFFFF;
      --primary-container: #C9E6FF;
      --on-primary-container: #001E2E;
      --secondary: #2B5B78;
      --tertiary: #8A4B00;
      --error: #BA1A1A;
      --error-container: #FFDAD6;
      --on-error-container: #410002;
      --success: #15803D;
      --success-container: #DCFCE7;
      --on-success-container: #052E16;
      --warning: #B45309;
      --warning-container: #FEF3C7;
      --on-warning-container: #451A03;
      --bg: #F4F7FA;
      --header-bg: rgba(244, 247, 250, 0.92);
      --surface-low: #EEF2F6;
      --surface: #FFFFFF;
      --surface-high: #E2E8F0;
      --surface-highest: #CBD5E1;
      --on-surface: #0F172A;
      --on-surface-variant: #475569;
      --outline-variant: #CBD5E1;
      --backdrop: rgba(15, 23, 42, 0.52);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 14px;
      line-height: 20px;
      background: var(--bg);
      color: var(--on-surface);
      transition: background 0.18s ease, color 0.18s ease;
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

    .mono { font-family: "DM Mono", monospace; }

    header {
      position: sticky;
      top: 0;
      z-index: 20;
      background: var(--header-bg);
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

    .brand-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .brand { display: flex; align-items: center; gap: 10px; }
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
      font-family: inherit;
      border: 0; border-radius: 10px;
      padding: 8px 13px; font-size: 13px; font-weight: 600;
      cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    }

    .btn-primary { background: var(--primary); color: var(--on-primary); }
    .btn-surface { background: var(--surface-high); color: var(--on-surface); border: 1px solid var(--outline-variant); }
    .btn-success { background: var(--success-container); color: var(--on-success-container); border: 1px solid var(--success); }
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

    .admin-bar {
      display: none;
      background: var(--surface);
      border: 1px solid var(--primary);
      border-radius: 14px;
      padding: 14px 16px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
    }
    .admin-bar.show { display: flex; }
    .admin-wing-form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .admin-wing-form input { width: 170px; margin: 0; }

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
      transition: border-color 0.15s ease, background 0.15s ease;
    }
    .inc-card:hover { border-color: var(--primary); }
    .inc-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
    .inc-title { font-size: 15px; font-weight: 600; cursor: pointer; }
    .inc-summary { font-size: 13px; color: var(--on-surface-variant); margin-top: 6px; }
    .inc-reply-box {
      margin-top: 8px; padding: 8px 10px; border-radius: 8px;
      background: var(--surface); border-left: 3px solid var(--primary);
      font-size: 12px; color: var(--on-surface);
    }
    .inc-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; align-items: center; }
    .inc-admin-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--outline-variant); }

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
    .item-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }

    .empty {
      text-align: center; padding: 24px 12px;
      color: var(--on-surface-variant); font-size: 13px;
      border: 1px dashed var(--outline-variant); border-radius: 12px;
    }

    .modal-backdrop {
      position: fixed; inset: 0; z-index: 50;
      background: var(--backdrop);
      display: none; align-items: center; justify-content: center; padding: 16px;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      width: 100%; max-width: 560px; max-height: 90vh; overflow-y: auto;
      background: var(--surface); border: 1px solid var(--outline-variant);
      border-radius: 16px; padding: 20px;
    }
    .modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .modal-title { font-size: 17px; font-weight: 700; }

    label { display: block; font-size: 12px; color: var(--on-surface-variant); margin: 10px 0 4px; font-weight: 500; }
    input, select, textarea {
      width: 100%; font-family: inherit; font-size: 14px;
      background: var(--surface-low); color: var(--on-surface);
      border: 1px solid var(--outline-variant); border-radius: 10px; padding: 9px 12px;
    }
    textarea { min-height: 80px; resize: vertical; }
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
      <div class="brand-left">
        <button type="button" class="btn-surface btn-sm" id="themeBtn" onclick="toggleTheme()" title="Switch Light/Dark Theme">
          <span class="material-symbols-outlined" id="themeIcon">dark_mode</span>
          <span id="themeLabel">Dark</span>
        </button>
        <div class="brand">
          <div class="brand-badge"><span class="material-symbols-outlined">apartment</span></div>
          <div>
            <div class="brand-title" id="societyName">Greenwood Estates</div>
            <div class="brand-sub">Resident Triage &amp; Incident Command</div>
          </div>
        </div>
      </div>

      <div class="controls-row">
        <div class="wing-group" id="wingFilter"></div>
        <button type="button" class="btn-surface" id="adminBtn" onclick="handleAdminClick()">
          <span class="material-symbols-outlined">admin_panel_settings</span>
          <span id="adminLabel">Admin Login</span>
        </button>
        <button type="button" class="btn-primary" onclick="openTriage()">
          <span class="material-symbols-outlined">add_comment</span> Triage Message
        </button>
        <button type="button" class="btn-surface" onclick="loadState()">
          <span class="material-symbols-outlined">refresh</span> Sync
        </button>
      </div>
    </div>
  </header>

  <main>
    <div class="admin-bar" id="adminBar">
      <div>
        <strong>Admin Mode Active</strong>
        <span class="item-sub" style="margin-left:8px;">Add wings, resolve issues, reply, or merge tickets/incidents.</span>
      </div>
      <div class="admin-wing-form">
        <input id="newWingInput" placeholder="New wing (e.g. A, E)" />
        <button type="button" class="btn-primary btn-sm" onclick="addWing()">
          <span class="material-symbols-outlined">add</span> Add Wing
        </button>
        <button type="button" class="btn-danger btn-sm" onclick="resetState()">
          <span class="material-symbols-outlined">restart_alt</span> Reset Demo
        </button>
        <button type="button" class="btn-surface btn-sm" onclick="logoutAdmin()">Logout</button>
      </div>
    </div>

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

  <!-- Admin Login Modal -->
  <div class="modal-backdrop" id="adminModal">
    <div class="modal">
      <div class="modal-head">
        <div class="modal-title">Admin Sign In</div>
        <button type="button" class="btn-surface btn-sm" onclick="closeModal('adminModal')">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>
      <form id="adminForm">
        <label>Admin Username</label>
        <input id="adminUser" value="admin" required />
        <label>Passcode</label>
        <input type="password" id="adminPass" placeholder="Default: admin123" required />
        <div class="item-sub" style="margin-top:8px;">Demo passcode is <code>admin123</code>.</div>
        <div class="modal-actions">
          <button type="button" class="btn-surface" onclick="closeModal('adminModal')">Cancel</button>
          <button type="submit" class="btn-primary">Sign In</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Triage Modal -->
  <div class="modal-backdrop" id="triageModal">
    <div class="modal">
      <div class="modal-head">
        <div class="modal-title">Report an Issue</div>
        <button type="button" class="btn-surface btn-sm" onclick="closeModal('triageModal')">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>
      <form id="triageForm">
        <label>Your Name</label>
        <input id="triageSender" placeholder="e.g., Aarav Sharma" required />
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div>
            <label>Wing</label>
            <select id="triageWing" required></select>
          </div>
          <div>
            <label>Flat No.</label>
            <input id="triageFlat" placeholder="e.g., 402" required />
          </div>
        </div>
        <label>Select Issue</label>
        <select id="triageIssueType">
          <option value="Water Supply">Water Supply</option>
          <option value="Power / Lift">Power / Lift</option>
          <option value="Plumbing / Leakage">Plumbing / Leakage</option>
          <option value="Security / Gate">Security / Gate</option>
          <option value="Parking / Common Area">Parking / Common Area</option>
          <option value="Other">Other</option>
        </select>
        <label>Description</label>
        <textarea id="triageMessage" placeholder="Describe the issue clearly..." required></textarea>
        <div class="modal-actions">
          <button type="button" class="btn-surface" onclick="closeModal('triageModal')">Cancel</button>
          <button type="submit" class="btn-primary" id="triageSubmitBtn">Submit Report</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Incident Detail / Admin Reply / Merge Modal -->
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

      <label>Admin Reply / Resolution Note</label>
      <textarea id="detailReply" placeholder="Write a reply or update for residents..."></textarea>

      <label>Vendor Status</label>
      <input id="detailVendor" placeholder="e.g., Plumber dispatched" />

      <div id="mergeIncidentSection" style="margin-top:12px;padding-top:12px;border-top:1px solid var(--outline-variant);">
        <label>Merge This Incident Into Existing Incident</label>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <select id="mergeTargetSelect" style="flex:1;min-width:180px;"></select>
          <button type="button" class="btn-surface btn-sm" onclick="mergeCurrentIncident()">
            <span class="material-symbols-outlined">call_merge</span> Merge Into Target
          </button>
        </div>
      </div>

      <div class="modal-actions">
        <button type="button" class="btn-success" onclick="quickResolveModal()">
          <span class="material-symbols-outlined">check_circle</span> Mark Resolved
        </button>
        <button type="button" class="btn-surface" onclick="closeModal('detailModal')">Close</button>
        <button type="button" class="btn-primary" onclick="saveIncident()">Save Changes</button>
      </div>
    </div>
  </div>

  <!-- Merge Ticket Modal -->
  <div class="modal-backdrop" id="mergeTicketModal">
    <div class="modal">
      <div class="modal-head">
        <div class="modal-title">Merge Ticket Into Incident</div>
        <button type="button" class="btn-surface btn-sm" onclick="closeModal('mergeTicketModal')">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>
      <div id="mergeTicketInfo" class="item-row"></div>
      <label>Select Target Master Incident</label>
      <select id="ticketTargetIncident"></select>
      <label>Or Create New Master Incident Title</label>
      <input id="newIncidentTitleForTicket" placeholder="e.g., Wing B Water Pressure Issue" />
      <div class="modal-actions">
        <button type="button" class="btn-surface" onclick="closeModal('mergeTicketModal')">Cancel</button>
        <button type="button" class="btn-primary" onclick="confirmMergeTicket()">Merge Ticket</button>
      </div>
    </div>
  </div>

  <script>
    const ADMIN_PASSCODE = "admin123";
    let appState = null;
    let selectedWing = "all";
    let customWings = JSON.parse(localStorage.getItem("sp_custom_wings") || "[]");
    let adminReplies = JSON.parse(localStorage.getItem("sp_admin_replies") || "{}");
    let mergedRecords = JSON.parse(localStorage.getItem("sp_merged_records") || '{"merged_incident_ids":[],"merged_ticket_ids":[]}');
    let isAdmin = localStorage.getItem("sp_is_admin") === "1";
    let showResolved = false;
    let activeTab = "logs";
    let editingIncidentId = null;
    let mergingTicketId = null;

    function persistMeta() {
      localStorage.setItem("sp_admin_replies", JSON.stringify(adminReplies));
      localStorage.setItem("sp_merged_records", JSON.stringify(mergedRecords));
    }

    function applyTheme(theme) {
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("sp_theme", theme);
      const isDark = theme === "dark";
      document.getElementById("themeIcon").textContent = isDark ? "light_mode" : "dark_mode";
      document.getElementById("themeLabel").textContent = isDark ? "Light" : "Dark";
    }

    function toggleTheme() {
      const cur = document.documentElement.getAttribute("data-theme") || "light";
      applyTheme(cur === "dark" ? "light" : "dark");
    }

    function syncAdminUI() {
      const btn = document.getElementById("adminBtn");
      const label = document.getElementById("adminLabel");
      const bar = document.getElementById("adminBar");
      if (isAdmin) {
        btn.className = "btn-success";
        label.textContent = "Admin Active";
        bar.classList.add("show");
      } else {
        btn.className = "btn-surface";
        label.textContent = "Admin Login";
        bar.classList.remove("show");
      }
      renderAll();
    }

    function handleAdminClick() {
      if (isAdmin) {
        document.getElementById("adminBar").classList.toggle("show");
      } else {
        document.getElementById("adminPass").value = "";
        openModal("adminModal");
      }
    }

    function logoutAdmin() {
      isAdmin = false;
      localStorage.removeItem("sp_is_admin");
      syncAdminUI();
    }

    function addWing() {
      if (!isAdmin) return;
      clearErr();
      const inp = document.getElementById("newWingInput");
      const val = inp.value.trim().replace(/^wing\s+/i, "");
      if (!val) return;
      if (!customWings.includes(val)) {
        customWings.push(val);
        localStorage.setItem("sp_custom_wings", JSON.stringify(customWings));
      }
      selectedWing = val;
      inp.value = "";
      renderAll();
    }

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

    function populateTriageWings(preferredWing = "") {
      const sel = document.getElementById("triageWing");
      const wings = getWings(appState || {}).filter(w => w !== "all");
      const list = wings.length ? wings : ["A", "B", "C"];
      sel.innerHTML = list.map(w => `<option value="${esc(w)}">Wing ${esc(w)}</option>`).join("");
      if (preferredWing && list.includes(preferredWing)) sel.value = preferredWing;
      else if (selectedWing !== "all" && list.includes(selectedWing)) sel.value = selectedWing;
    }

    function openTriage(prefillSender = "", prefillWing = "", prefillFlat = "") {
      document.getElementById("triageSender").value = prefillSender || "";
      document.getElementById("triageFlat").value = prefillFlat || "";
      document.getElementById("triageIssueType").value = "Water Supply";
      document.getElementById("triageMessage").value = "";
      populateTriageWings(prefillWing);
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
      const s = new Set(["all", ...customWings]);
      for (const x of (st.master_incidents || [])) if (x.wing) s.add(String(x.wing));
      for (const x of (st.tickets || [])) if (x.wing) s.add(String(x.wing));
      for (const x of (st.residents || [])) if (x.wing) s.add(String(x.wing));
      return Array.from(s);
    }

    function matchesWing(item) {
      if (selectedWing === "all") return true;
      return String(item.wing || "") === selectedWing;
    }

    function getIncidents() {
      return (appState?.master_incidents || []).filter(i => !mergedRecords.merged_incident_ids.includes(i.id || i.incident_id));
    }

    function getTickets() {
      return (appState?.tickets || []).filter(t => !mergedRecords.merged_ticket_ids.includes(t.id || t.ticket_id));
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
      const activeInc = getIncidents().filter(i => (i.status || "active") === "active" && matchesWing(i));
      const openTkts = getTickets().filter(t => (t.status || "open") !== "resolved" && matchesWing(t));
      const logs = (st.execution_logs || []).filter(l => matchesWing(l));
      const suppressed = logs.filter(l => l.action === "duplicate_suppressed" || l.status === "duplicate_suppressed").length + mergedRecords.merged_ticket_ids.length + mergedRecords.merged_incident_ids.length;
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
      const allInc = getIncidents().filter(matchesWing);
      const resolvedCnt = allInc.filter(i => i.status === "resolved").length;
      document.getElementById("resolvedToggleBtn").textContent = showResolved ? `Hide Resolved (${resolvedCnt})` : `Show Resolved (${resolvedCnt})`;

      const list = allInc.filter(i => showResolved ? true : (i.status || "active") === "active");
      const container = document.getElementById("incidentsList");

      if (!list.length) {
        container.innerHTML = `<div class="empty">No master incidents yet. Sign in as Admin to merge tickets into an incident or create one, or submit a triage report.</div>`;
        return;
      }

      container.innerHTML = list.map(inc => {
        const id = inc.id || inc.incident_id || "";
        const flats = Array.isArray(inc.affected_flats) ? inc.affected_flats.join(", ") : "";
        const reply = adminReplies[id] || inc.admin_reply || "";
        return `
          <div class="inc-card">
            <div class="inc-top" onclick="openDetail('${esc(id)}')">
              <div class="inc-title">${esc(inc.title || id || "Incident")}</div>
              <span class="${sevChipClass(inc.severity)}">${esc(inc.severity || "NORMAL")}</span>
            </div>
            ${inc.summary ? `<div class="inc-summary" onclick="openDetail('${esc(id)}')">${esc(inc.summary)}</div>` : ""}
            ${reply ? `<div class="inc-reply-box"><strong>Admin Reply:</strong> ${esc(reply)}</div>` : ""}
            <div class="inc-meta" onclick="openDetail('${esc(id)}')">
              <span class="chip chip-info">${esc(inc.status || "active")}</span>
              ${inc.wing ? `<span class="chip">Wing ${esc(inc.wing)}</span>` : ""}
              ${flats ? `<span class="chip mono">Flats: ${esc(flats)}</span>` : ""}
              ${inc.vendor_status ? `<span class="chip">${esc(inc.vendor_status)}</span>` : ""}
            </div>
            ${isAdmin ? `
              <div class="inc-admin-actions">
                ${(inc.status || "active") !== "resolved" ? `<button type="button" class="btn-success btn-sm" onclick="quickResolveIncident('${esc(id)}')"><span class="material-symbols-outlined">check_circle</span> Resolve</button>` : ""}
                <button type="button" class="btn-surface btn-sm" onclick="openDetail('${esc(id)}')"><span class="material-symbols-outlined">reply</span> Reply / Merge</button>
              </div>
            ` : ""}
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
        const tickets = getTickets().filter(matchesWing).slice().reverse();
        if (!tickets.length) {
          box.innerHTML = `<div class="empty">No open tickets.</div>`;
          return;
        }
        box.innerHTML = tickets.map(t => {
          const tid = t.id || t.ticket_id || "";
          const reply = adminReplies[tid] || "";
          return `
            <div class="item-row">
              <div class="item-head">
                <span>${esc(t.summary || t.message || tid || "Ticket")}</span>
                <span class="chip">${esc(t.status || "open")}</span>
              </div>
              <div class="item-sub">
                ${t.wing ? `Wing ${esc(t.wing)} · ` : ""}${t.sender ? `From ${esc(t.sender)}` : ""}
              </div>
              ${reply ? `<div class="inc-reply-box"><strong>Admin Reply:</strong> ${esc(reply)}</div>` : ""}
              ${isAdmin ? `
                <div class="item-actions">
                  <button type="button" class="btn-surface btn-sm" onclick="openMergeTicket('${esc(tid)}')"><span class="material-symbols-outlined">call_merge</span> Merge to Incident</button>
                  <button type="button" class="btn-surface btn-sm" onclick="replyToTicket('${esc(tid)}')"><span class="material-symbols-outlined">reply</span> Reply</button>
                </div>
              ` : ""}
            </div>
          `;
        }).join("");
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
            <button type="button" class="btn-surface btn-sm" onclick="openTriage('${esc(r.name || label)}', '${esc(r.wing || "")}', '${esc(r.flat || "")}')">Test</button>
          </div>
        `;
      }).join("");
    }

    function openDetail(id) {
      const inc = getIncidents().find(x => (x.id || x.incident_id) === id);
      if (!inc) return;
      editingIncidentId = id;
      document.getElementById("detailTitle").textContent = inc.title || id;
      document.getElementById("detailStatus").value = inc.status || "active";
      document.getElementById("detailReply").value = adminReplies[id] || inc.admin_reply || "";
      document.getElementById("detailVendor").value = inc.vendor_status || "";

      const others = getIncidents().filter(x => (x.id || x.incident_id) !== id);
      const mergeSel = document.getElementById("mergeTargetSelect");
      const mergeSec = document.getElementById("mergeIncidentSection");
      if (isAdmin && others.length) {
        mergeSec.style.display = "block";
        mergeSel.innerHTML = others.map(o => `<option value="${esc(o.id || o.incident_id)}">${esc(o.title || o.id || o.incident_id)}</option>`).join("");
      } else {
        mergeSec.style.display = "none";
      }

      document.getElementById("detailBody").innerHTML = `
        <div class="item-row">
          <div class="item-sub mono">ID: ${esc(id)}</div>
          <div class="item-sub">Severity: <strong>${esc(inc.severity || "NORMAL")}</strong> · Wing: <strong>${esc(inc.wing || "-")}</strong></div>
          ${inc.summary ? `<div class="item-sub" style="margin-top:8px;">${esc(inc.summary)}</div>` : ""}
        </div>
      `;
      openModal("detailModal");
    }

    async function patchIncidentBackend(id, payload) {
      const r = await fetch(`/incidents/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Failed to update incident");
      appState = data.state || data;
    }

    async function quickResolveIncident(id) {
      if (!isAdmin) return;
      clearErr();
      try {
        await patchIncidentBackend(id, { status: "resolved" });
        renderAll();
      } catch (e) {
        showErr(e.message);
      }
    }

    async function quickResolveModal() {
      if (!editingIncidentId) return;
      document.getElementById("detailStatus").value = "resolved";
      await saveIncident();
    }

    async function saveIncident() {
      if (!editingIncidentId) return;
      clearErr();
      const replyVal = document.getElementById("detailReply").value.trim();
      adminReplies[editingIncidentId] = replyVal;
      persistMeta();
      try {
        await patchIncidentBackend(editingIncidentId, {
          status: document.getElementById("detailStatus").value,
          vendor_status: document.getElementById("detailVendor").value,
          admin_reply: replyVal
        });
        closeModal("detailModal");
        renderAll();
      } catch (e) {
        showErr(e.message);
      }
    }

    async function mergeCurrentIncident() {
      if (!isAdmin || !editingIncidentId) return;
      const targetId = document.getElementById("mergeTargetSelect").value;
      if (!targetId || targetId === editingIncidentId) return;
      clearErr();
      const src = getIncidents().find(x => (x.id || x.incident_id) === editingIncidentId);
      const tgt = getIncidents().find(x => (x.id || x.incident_id) === targetId);
      const combinedFlats = Array.from(new Set([...(tgt?.affected_flats || []), ...(src?.affected_flats || [])]));
      const combinedSummary = [tgt?.summary, src?.summary ? `Merged (${src.title || editingIncidentId}): ${src.summary}` : ""].filter(Boolean).join(" | ");
      try {
        await patchIncidentBackend(targetId, {
          affected_flats: combinedFlats,
          summary: combinedSummary
        });
        if (!mergedRecords.merged_incident_ids.includes(editingIncidentId)) {
          mergedRecords.merged_incident_ids.push(editingIncidentId);
          persistMeta();
        }
        closeModal("detailModal");
        renderAll();
      } catch (e) {
        showErr(e.message);
      }
    }

    function replyToTicket(tid) {
      if (!isAdmin) return;
      const current = adminReplies[tid] || "";
      const ans = prompt("Enter admin reply for ticket " + tid + ":", current);
      if (ans === null) return;
      adminReplies[tid] = ans.trim();
      persistMeta();
      renderLedger();
    }

    function openMergeTicket(tid) {
      if (!isAdmin) return;
      const tkt = getTickets().find(x => (x.id || x.ticket_id) === tid);
      if (!tkt) return;
      mergingTicketId = tid;
      document.getElementById("mergeTicketInfo").innerHTML = `
        <div class="item-head">${esc(tkt.summary || tkt.message || tid)}</div>
        <div class="item-sub">Ticket ID: <span class="mono">${esc(tid)}</span> · Wing: ${esc(tkt.wing || "-")} · From: ${esc(tkt.sender || "-")}</div>
      `;
      const sel = document.getElementById("ticketTargetIncident");
      const incs = getIncidents();
      sel.innerHTML = incs.length
        ? incs.map(i => `<option value="${esc(i.id || i.incident_id)}">${esc(i.title || i.id || i.incident_id)} (${esc(i.status || "active")})</option>`).join("")
        : `<option value="">No existing master incident — enter a new title below</option>`;
      document.getElementById("newIncidentTitleForTicket").value = tkt.wing ? `Wing ${tkt.wing} — ${tkt.summary || tkt.message || "Consolidated Issue"}` : (tkt.summary || tkt.message || "Consolidated Issue");
      openModal("mergeTicketModal");
    }

    async function confirmMergeTicket() {
      if (!isAdmin || !mergingTicketId) return;
      clearErr();
      const tkt = getTickets().find(x => (x.id || x.ticket_id) === mergingTicketId);
      const targetId = document.getElementById("ticketTargetIncident").value;
      const newTitle = document.getElementById("newIncidentTitleForTicket").value.trim();

      try {
        if (targetId) {
          const tgt = getIncidents().find(x => (x.id || x.incident_id) === targetId);
          const flats = Array.from(new Set([...(tgt?.affected_flats || []), ...(tkt?.flat ? [String(tkt.flat)] : [])]));
          const note = tkt?.summary || tkt?.message || mergingTicketId;
          const summary = [tgt?.summary, `Merged ticket ${mergingTicketId}: ${note}`].filter(Boolean).join(" | ");
          await patchIncidentBackend(targetId, { affected_flats: flats, summary });
        } else if (newTitle && appState) {
          appState.master_incidents = appState.master_incidents || [];
          appState.master_incidents.push({
            id: "inc_" + Date.now().toString().slice(-5),
            title: newTitle,
            status: "active",
            severity: "MEDIUM",
            wing: tkt?.wing || "",
            affected_flats: tkt?.flat ? [String(tkt.flat)] : [],
            summary: tkt?.summary || tkt?.message || ""
          });
        }
        if (!mergedRecords.merged_ticket_ids.includes(mergingTicketId)) {
          mergedRecords.merged_ticket_ids.push(mergingTicketId);
          persistMeta();
        }
        closeModal("mergeTicketModal");
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
        adminReplies = {};
        mergedRecords = { merged_incident_ids: [], merged_ticket_ids: [] };
        persistMeta();
        renderAll();
      } catch (e) {
        showErr(e.message);
      }
    }

    document.getElementById("adminForm").addEventListener("submit", (e) => {
      e.preventDefault();
      clearErr();
      const pass = document.getElementById("adminPass").value;
      if (pass !== ADMIN_PASSCODE) {
        showErr("Invalid admin passcode. Try admin123.");
        return;
      }
      isAdmin = true;
      localStorage.setItem("sp_is_admin", "1");
      closeModal("adminModal");
      syncAdminUI();
    });

    document.getElementById("triageForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      clearErr();
      const btn = document.getElementById("triageSubmitBtn");
      btn.disabled = true;
      try {
        const sender = document.getElementById("triageSender").value.trim();
        const wing = document.getElementById("triageWing").value;
        const flat = document.getElementById("triageFlat").value.trim();
        const issueType = document.getElementById("triageIssueType").value;
        const desc = document.getElementById("triageMessage").value.trim();

        const r = await fetch("/triage", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sender,
            channel: "app",
            wing,
            flat,
            issue_type: issueType,
            message: desc
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

    applyTheme(localStorage.getItem("sp_theme") || "light");
    syncAdminUI();
    loadState();
  </script>
</body>
</html>"""


@app.get("/")
def index():
    return render_template_string(MOBILE_UI), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)






