"""Production WSGI entrypoint for the new AE Compass AppFoundry app.

This is deliberately a new deployable wrapper around the existing AE Compass
data adapter. It does not import, modify, or depend on the Vision application.
The same API contract is used by the React UI, so local and AppFoundry builds
share one frontend and one set of server-owned calculations.
"""
from __future__ import annotations

import json
import os
import re
import sys
import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
try:
    from flask_cors import CORS
except ImportError:  # local smoke tests can run with Flask alone
    def CORS(*_args, **_kwargs):
        return None

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import mock_server as backend  # noqa: E402
from assistant import AssistantUnavailable, answer_question  # noqa: E402


app = Flask(__name__, static_folder=str(ROOT / "dist" / "renderer"), static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})


def _query():
    return {key: value for key, value in request.args.items()}


def _json(value, status=200):
    return jsonify(value), status


class _HeaderShim:
    def __init__(self):
        self.headers = request.headers


@app.get("/api/health")
def health():
    return _json({"status": "ok", "app": "AE Compass", "environment": "appfoundry"})


@app.get("/api/auth/me")
def auth_me():
    return _json(backend.auth_identity(_HeaderShim()))


@app.get("/api/profile")
def profile():
    email = (request.args.get("email") or "").strip().lower()
    for user in backend.WORKDAY_USERS:
        if (user.get("EMAIL") or "").strip().lower() != email:
            continue
        role = backend.workday_access_type(user)
        is_admin = email == "justine.mendez@zendesk.com"
        return _json({
            "authenticated": True,
            "email": email,
            "name": (user.get("FULL_NAME") or "").strip(),
            "subject_id": str(user.get("EMPLOYEE_ID") or ""),
            "role": "Admin" if is_admin else role,
            "access_level": "full" if is_admin else ("hierarchy" if role != "AE" else "own profile"),
            "scope_value": "all" if is_admin else (user.get("FULL_NAME") or "").strip(),
            "source": "appfoundry",
        })
    return _json({"authenticated": False, "email": email, "name": None}, 404)


GETTERS = {
    "/api/roster": lambda q: backend.get_roster(),
    "/api/directory": lambda q: backend.get_directory(),
    "/api/account_landscape": backend.get_account_landscape,
    "/api/pipeline": backend.get_pipeline,
    "/api/bookings": backend.get_bookings,
    "/api/pipeline_by_product": backend.get_pipeline_by_product,
    "/api/gtmi_pipeline_summary": backend.get_gtmi_pipeline_summary,
    "/api/metrics/summary": backend.get_metrics_summary,
    "/api/stage_distribution": backend.get_stage_distribution,
    "/api/historical": backend.get_historical,
    "/api/linearity": backend.get_linearity,
    "/api/pipe_creation": backend.get_pipe_creation,
    "/api/forecast": backend.get_forecast,
    "/api/forecast/team": backend.get_team_forecast,
    "/api/quota/team": backend.get_team_quota,
}


@app.get("/api/admin/uploads")
def uploads():
    if not backend.admin_request_authorized(_HeaderShim()):
        return _json({"error": "Admin authentication required."}, 401)
    return _json(backend.STATE.get("uploads", []))


@app.post("/api/admin/verify")
def verify_admin():
    data = request.get_json(silent=True) or {}
    token = backend.issue_admin_token(str(data.get("password") or ""))
    return _json({"valid": bool(token), "admin_token": token})


@app.post("/api/admin/upload")
def admin_upload():
    if not backend.admin_request_authorized(_HeaderShim()):
        return _json({"error": "Admin authentication required."}, 401)
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _json({"error": "Choose a file before uploading."}, 400)
    filename = Path(upload.filename).name
    if not filename.lower().endswith((".csv", ".tsv")):
        return _json({"error": "Please upload a CSV or TSV file."}, 400)
    content = upload.read()
    backend.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{re.sub(r'[^A-Za-z0-9._-]', '_', filename)}"
    (backend.UPLOAD_DIR / stored_name).write_bytes(content)
    saved_to_source = backend.save_uploaded_source(filename, content)
    text = content.decode("utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    delimiter = "\t" if filename.lower().endswith(".tsv") else ","
    headers = [item.strip() for item in (lines[0].split(delimiter) if lines else [])]
    entry = {
        "id": stored_name,
        "filename": filename,
        "stored_name": stored_name,
        "dataset": request.form.get("dataset", "Pipeline & bookings"),
        "row_count": max(len(lines) - 1, 0),
        "headers": headers,
        "size_bytes": len(content),
        "uploaded_at": datetime.datetime.now().isoformat(),
        "saved_to_source": saved_to_source,
    }
    backend.STATE["uploads"].insert(0, entry)
    backend.save_state()
    return _json({"status": "uploaded", "rows": entry["row_count"], "filename": filename, "dataset": entry["dataset"], "saved_to_source": saved_to_source})


@app.get("/api/admin/data-sources")
def data_sources():
    return _json(backend.data_source_inventory())


@app.get("/api/admin/data-download/<path:filename>")
def data_download(filename):
    safe_name = Path(filename).name
    if safe_name != filename or safe_name.startswith("."):
        return _json({"error": "invalid filename"}, 400)
    path = backend.DATA_DIR / safe_name
    if not path.is_file() or path.suffix.lower() not in {".csv", ".tsv", ".zip", ".json"}:
        return _json({"error": "data file not found"}, 404)
    return send_file(path, as_attachment=True, download_name=safe_name)


@app.get("/api/gong")
def gong():
    ids = [value for value in (request.args.get("opportunity_ids") or "").split("|") if value]
    return _json(backend.fetch_gong_signals(ids))


@app.get("/api/quota/<item_id>")
def quota(item_id):
    return _json({"quota": backend.STATE["quotas"].get(f"{item_id}|{request.args.get('quarter', 'FY2027Q3')}", 0)})


@app.get("/api/notes/<item_id>")
def notes(item_id):
    return _json(backend.STATE["notes"].get(item_id, []))


@app.get("/api/actions/<item_id>")
def actions(item_id):
    return _json(backend.STATE["actions"].get(item_id, []))


@app.get("/api/competencies/<item_id>")
def competencies(item_id):
    return _json(backend.STATE["competencies"].get(item_id, [3, 3, 3, 3, 3]))


@app.get("/api/weekly-tracker/<item_id>")
def weekly_tracker(item_id):
    return _json(backend.STATE["weekly"].get(item_id))


@app.get("/api/deal-maps/<item_id>")
def deal_maps(item_id):
    return _json(backend.STATE["dealmaps"].get(item_id, []))


@app.get("/api/<path:unknown>")
def api_get(unknown):
    path = "/api/" + unknown
    getter = GETTERS.get(path)
    if getter is None:
        return _json({"error": "not found", "path": path}, 404)
    q = _query()
    if path in {"/api/pipeline_by_product", "/api/gtmi_pipeline_summary", "/api/metrics/summary", "/api/historical"} and not backend.has_scope(q):
        return _json({"error": "scope required"}, 400)
    if path == "/api/stage_distribution" and not q.get("owner_id"):
        return _json({"error": "owner_id required"}, 400)
    return _json(getter(q))


@app.post("/api/ask")
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()
    viewer = str(data.get("owner_name") or "").strip()
    quarter = str(data.get("quarter") or "FY2027Q3").strip()
    if not question:
        return _json({"answer": "Ask me about a deal, pipeline, AI, New Business, or what to do next.", "evidence": [], "source": "AE Compass data"})
    rows = backend.get_pipeline({"owner_name": viewer, "quarter": quarter}) if viewer else []
    if not rows:
        return _json({"answer": "I could not find opportunities matched to this profile yet.", "evidence": [], "source": "Workday + GTMI/Salesforce"})
    try:
        return _json(answer_question(question, viewer, quarter, rows, data.get("history", [])))
    except AssistantUnavailable as exc:
        return _json({"error": "assistant_unavailable", "message": str(exc)}, 503)


@app.post("/api/notes/<item_id>")
def notes_post(item_id):
    data = request.get_json(silent=True) or {}
    note = {
        "id": data.get("id"),
        "ae_user_id": item_id,
        "category": data.get("category"),
        "content": data.get("content"),
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    backend.STATE["notes"].setdefault(item_id, []).insert(0, note)
    backend.save_state()
    return _json({"status": "created", "id": note["id"]}, 201)


@app.post("/api/actions/<item_id>")
def actions_post(item_id):
    data = request.get_json(silent=True) or {}
    item = {
        "id": data.get("id"),
        "ae_user_id": item_id,
        "title": data.get("title"),
        "status": data.get("status", "Not Started"),
        "quarter": data.get("quarter"),
        "category": data.get("category", "General"),
    }
    backend.STATE["actions"].setdefault(item_id, []).append(item)
    backend.save_state()
    return _json({"status": "created", "id": item["id"]}, 201)


def _state_write(collection, item_id, value):
    backend.STATE[collection][item_id] = value
    backend.save_state()
    return _json({"status": "ok"})


@app.put("/api/quota/<item_id>")
def quota_put(item_id):
    data = request.get_json(silent=True) or {}
    backend.STATE["quotas"][f"{item_id}|{data.get('quarter', 'FY2027Q3')}"] = float(data.get("quota", 0))
    backend.save_state()
    return _json({"status": "ok"})


@app.put("/api/competencies/<item_id>")
def competencies_put(item_id):
    return _state_write("competencies", item_id, (request.get_json(silent=True) or {}).get("scores", [3, 3, 3, 3, 3]))


@app.put("/api/weekly-tracker/<item_id>")
def weekly_put(item_id):
    return _state_write("weekly", item_id, (request.get_json(silent=True) or {}).get("rows"))


@app.put("/api/deal-maps/<item_id>")
def deal_maps_put(item_id):
    return _state_write("dealmaps", item_id, (request.get_json(silent=True) or {}).get("plans", []))


@app.patch("/api/actions/<item_id>/<action_id>")
def action_patch(item_id, action_id):
    data = request.get_json(silent=True) or {}
    for item in backend.STATE["actions"].get(item_id, []):
        if item.get("id") == action_id:
            item["status"] = data.get("status", item.get("status"))
    backend.save_state()
    return _json({"status": "updated"})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path):
    dist = ROOT / "dist" / "renderer"
    candidate = dist / path
    if path and candidate.exists() and candidate.is_file():
        return send_from_directory(dist, path)
    return send_from_directory(dist, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
