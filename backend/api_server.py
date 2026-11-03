"""
R&D Proposal Monitor — API Server
===================================
Lightweight Flask server that:
  - Serves /api/proposals   (all current proposals)
  - Serves /api/notifications  (change alerts)
  - POST /api/notifications/read/<id>   (mark read)
  - POST /api/notifications/read-all   (mark all read)
  - POST /api/scan   (trigger an immediate scan)
  - Serves the frontend dashboard at /

Run:  python api_server.py
Deps: pip install flask flask-cors
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE        = Path(__file__).parent.parent
DATA_DIR    = BASE / "data"
FRONTEND    = BASE / "frontend"
PROPOSALS_F = DATA_DIR / "proposals.json"
NOTIF_F     = DATA_DIR / "notifications.json"

app = Flask(__name__, static_folder=str(FRONTEND))
CORS(app)   # allow dashboard (same machine, different port) to call API


# ── Helpers ───────────────────────────────────────────────────────────────────
def load(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            pass
    return default


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(FRONTEND), "dashboard.html")


@app.route("/api/proposals")
def proposals():
    data = load(PROPOSALS_F, {"icmr": [], "dbt": [], "lastScan": "Never", "totalOpen": 0})
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
    """Kick off an immediate scraper run without waiting for the scheduler."""
    scraper = BASE / "backend" / "scraper.py"
    subprocess.Popen([sys.executable, str(scraper), "--once"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return jsonify({"ok": True, "message": "Scan triggered", "time": datetime.now().strftime("%d %b %Y, %I:%M %p")})


@app.route("/api/status")
def status():
    proposals = load(PROPOSALS_F, {})
    notifs    = load(NOTIF_F, [])
    return jsonify({
        "lastScan":    proposals.get("lastScan", "Never"),
        "totalOpen":   proposals.get("totalOpen", 0),
        "totalAll":    proposals.get("totalAll", 0),
        "unreadCount": sum(1 for n in notifs if n.get("unread")),
    })


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    print("R&D Monitor API  →  http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
