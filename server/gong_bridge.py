"""Small read-only bridge to the existing GTM Ops Gong connector.

AE Compass stays self-contained: this helper only runs when the local
reference connector is present and returns the requested opportunity calls as
JSON. No Gong data is copied into the UI bundle.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

repo = os.environ.get("AE_COMPASS_GTM_REPO", "/Users/justine.mendez/Desktop/northstar2026/gtm-ops-claude")
sys.path.insert(0, repo)

try:
    from connections.gong.cache import DB_PATH
except Exception as exc:  # pragma: no cover - depends on local connector setup
    print(json.dumps({"error": f"Gong connector unavailable: {exc}"}))
    raise SystemExit(0)

try:
    payload = json.load(sys.stdin)
    ids = [str(value).strip() for value in payload.get("opportunity_ids", []) if str(value).strip()]
    if not ids:
        print(json.dumps([]))
        raise SystemExit(0)
    # The dashboard must stay fast and deterministic. Read only records that
    # have already been verified and stored by the reference connector's local
    # cache; never start an interactive Snowflake SSO flow during page load.
    if not Path(DB_PATH).exists():
        print(json.dumps({"error": "No verified Gong cache is available yet."}))
        raise SystemExit(0)
    placeholders = ", ".join("?" for _ in ids[:50])
    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"""
            SELECT crm_opportunity_id, conversation_key, title,
                   planned_start_datetime, planned_end_datetime,
                   call_spotlight_brief, call_spotlight_next_steps,
                   call_spotlight_key_points, speakers
            FROM gong_calls
            WHERE crm_opportunity_id IN ({placeholders})
            ORDER BY planned_start_datetime DESC
            """,
            ids[:50],
        ).fetchall()
    frame = [dict(row) for row in rows]
    print(json.dumps(frame, default=str))
except Exception as exc:  # pragma: no cover - live connector failure is surfaced safely
    print(json.dumps({"error": str(exc)}))
