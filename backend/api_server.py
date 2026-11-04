"""
R&D Proposal Monitor — REST API Server (ICMR, DBT & NBHM Only)
==============================================================
Serves proposals, notifications, agency metadata, and status
for ICMR, DBT, and NBHM.
"""

import json
import sys
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from sources_config import SOURCES_METADATA, AGENCIES_LIST

BASE     = Path(__file__).parent.parent
DATA_DIR = BASE / "data"

PROPOSALS_F = DATA_DIR / "proposals.json"
NOTIF_F     = DATA_DIR / "notifications.json"

app = Flask(__name__, static_folder=str(BASE / "frontend"))

scan_process = None


def is_scan_running():
    global scan_process
    if scan_process is not None:
        if scan_process.poll() is None:
            return True
        scan_process = None
    return False


def load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            pass
    return default


def save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


# ── CORS ─────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


# ── Frontend Route ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(BASE / "frontend"), "dashboard.html")


# ── API Endpoints ─────────────────────────────────────────────────────────────
@app.route("/api/agencies")
def agencies():
    """Returns directory for ICMR, DBT, and NBHM."""
    return jsonify({
        "total": len(AGENCIES_LIST),
        "agencies": SOURCES_METADATA,
        "list": AGENCIES_LIST
    })


@app.route("/api/proposals")
def proposals():
    """Returns proposals across ICMR, DBT, and NBHM."""
    data = load(PROPOSALS_F, {})
    agency_param = request.args.get("agency")
    
    if agency_param and agency_param != "all":
        ap_lower = agency_param.lower()
        all_props = data.get("proposals", [])
        filtered = [p for p in all_props if (p.get("source") or "").lower() == ap_lower]
        
        return jsonify({
            "lastScan": data.get("lastScan", "Never"),
            "totalOpen": len([p for p in filtered if p.get("status") == "open"]),
            "totalAll": len(filtered),
            "agencies": SOURCES_METADATA,
            "proposals": filtered,
        })
    return jsonify(data)


@app.route("/api/notifications")
def notifications():
    data = load(NOTIF_F, [])
    return jsonify(data)


@app.route("/api/notifications/read/<int:notif_id>", methods=["POST"])
def mark_read(notif_id):
    notifs = load(NOTIF_F, [])
    for n in notifs:
        if n.get("id") == notif_id:
            n["unread"] = False
    save(NOTIF_F, notifs)
    return jsonify({"ok": True})


@app.route("/api/notifications/read-all", methods=["POST"])
def mark_all_read():
    notifs = load(NOTIF_F, [])
    for n in notifs:
        n["unread"] = False
    save(NOTIF_F, notifs)
    return jsonify({"ok": True})


@app.route("/api/scan", methods=["POST"])
def trigger_scan():
    """Kick off an immediate non-blocking scraper run using virtual environment Python."""
    global scan_process
    if is_scan_running():
        return jsonify({"ok": True, "scanning": True, "message": "Scan is already running across ICMR, DBT & NBHM", "time": datetime.now().strftime("%d %b %Y, %I:%M %p")})

    scraper = BASE / "backend" / "scraper.py"
    venv_python = BASE / "backend" / "venv" / "bin" / "python3"
    python_bin = str(venv_python) if venv_python.exists() else sys.executable
    scan_process = subprocess.Popen([python_bin, str(scraper), "--once"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return jsonify({"ok": True, "scanning": True, "message": "Scan triggered for ICMR, DBT & NBHM", "time": datetime.now().strftime("%d %b %Y, %I:%M %p")})


@app.route("/api/status")
def status():
    proposals_data = load(PROPOSALS_F, {})
    notifs         = load(NOTIF_F, [])
    return jsonify({
        "lastScan":    proposals_data.get("lastScan", "Never"),
        "totalOpen":   proposals_data.get("totalOpen", 0),
        "totalAll":    proposals_data.get("totalAll", 0),
        "totalAgencies": len(SOURCES_METADATA),
        "unreadCount": sum(1 for n in notifs if n.get("unread")),
        "scanning":    is_scan_running(),
    })


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    print("R&D Monitor (ICMR, DBT & NBHM) API  →  http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
