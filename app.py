import json
from pathlib import Path
from flask import Flask, jsonify, make_response, request
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)