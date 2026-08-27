"""On-demand Gong opportunity signals with bounded local caching."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path


BRIDGE = Path(__file__).with_name("gong_bridge.py")
GTM_REPO = os.environ.get("AE_COMPASS_GTM_REPO", "/Users/justine.mendez/Desktop/northstar2026/gtm-ops-claude")
GTM_PYTHON = os.environ.get("AE_COMPASS_GTM_PYTHON", str(Path(GTM_REPO) / "venv/bin/python"))


def _text(value) -> str:
    return str(value or "").strip()


def _days_since(value):
    if not value:
        return None
    raw = _text(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return max(0, (dt.datetime.utcnow() - parsed).days)


def _signals(records):
    by_opp = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        opp_id = _text(record.get("crm_opportunity_id"))
        if opp_id:
            by_opp.setdefault(opp_id, []).append(record)

    out = []
    competitor_terms = ("salesforce", "servicenow", "freshworks", "intercom", "genesys", "dixa", "zendesk competitor")
    objection_terms = ("objection", "concern", "risk", "blocker", "not convinced", "budget", "procurement", "security review")
    buyer_terms = ("economic buyer", "decision maker", "decision-maker", "cfo", "ceo", "vp ", "executive sponsor")
    for opp_id, rows in by_opp.items():
        rows.sort(key=lambda row: _text(row.get("planned_start_datetime")), reverse=True)
        latest = rows[0]
        combined = " ".join(_text(row.get(key)) for row in rows for key in (
            "call_spotlight_brief", "call_spotlight_next_steps", "call_spotlight_key_points", "transcript"
        )).lower()
        days = _days_since(latest.get("planned_start_datetime"))
        has_next_steps = any(_text(row.get("call_spotlight_next_steps")) for row in rows)
        competitors = sorted({term.title() for term in competitor_terms if term in combined})
        objections = any(term in combined for term in objection_terms)
        buyer_signal = any(term in combined for term in buyer_terms)
        risks = []
        actions = []
        if days is None or days > 14:
            risks.append("No recent opportunity call")
            actions.append("Book a follow-up and confirm the next customer milestone")
        if not has_next_steps:
            risks.append("No call next steps captured")
            actions.append("Log a dated next step after the next buyer conversation")
        if competitors:
            risks.append(f"Competitor signal: {', '.join(competitors)}")
            actions.append("Resolve the competitive gap before the next stage decision")
        if objections:
            risks.append("Concern or objection signal in call notes")
            actions.append("Close the open concern with the buyer and document the resolution")
        if not buyer_signal:
            risks.append("Decision-maker involvement not evidenced")
            actions.append("Confirm the economic buyer and decision process")
        out.append({
            "crm_opportunity_id": opp_id,
            "call_count": len(rows),
            "last_call_at": latest.get("planned_start_datetime"),
            "last_call_title": latest.get("title"),
            "last_call_next_steps": latest.get("call_spotlight_next_steps"),
            "last_call_key_points": latest.get("call_spotlight_key_points"),
            "days_since_call": days,
            "has_next_steps": has_next_steps,
            "competitors": competitors,
            "buyer_signal": buyer_signal,
            "objection_signal": objections,
            "risk_signals": risks[:4],
            "recommended_actions": actions[:3],
            "source": "verified_gong",
        })
    return out


def fetch_gong_signals(opportunity_ids: list[str]) -> dict:
    ids = [str(value).strip() for value in opportunity_ids if str(value).strip()][:50]
    if not ids:
        return {"connected": False, "signals": [], "message": "No opportunity IDs supplied."}
    if not Path(GTM_PYTHON).exists() or not BRIDGE.exists():
        return {"connected": False, "signals": [], "message": "Gong connector is not configured in this environment."}
    env = os.environ.copy()
    env.update({
        "AE_COMPASS_GTM_REPO": GTM_REPO,
        "SNOWFLAKE_ACCOUNT": env.get("SNOWFLAKE_ACCOUNT", "ZENDESK-GLOBAL"),
        "SNOWFLAKE_USER": env.get("SNOWFLAKE_USER", "justine.mendez@zendesk.com"),
        "SNOWFLAKE_AUTHENTICATOR": env.get("SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
        "SNOWFLAKE_WAREHOUSE": env.get("SNOWFLAKE_WAREHOUSE", "PUBLIC_ZENDESK_L"),
    })
    try:
        completed = subprocess.run(
            [GTM_PYTHON, str(BRIDGE)],
            input=json.dumps({"opportunity_ids": ids}),
            text=True,
            capture_output=True,
            # Never let a Snowflake SSO/network issue block the dashboard.
            timeout=12,
            env=env,
        )
        payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {"error": completed.stderr.strip()}
        if isinstance(payload, dict) and payload.get("error"):
            return {"connected": False, "signals": [], "message": payload["error"]}
        signals = _signals(payload if isinstance(payload, list) else [])
        if not signals:
            return {"connected": False, "signals": [], "message": "No verified cached Gong calls for the selected opportunities yet."}
        return {"connected": True, "signals": signals, "message": "Verified Gong opportunity calls loaded from the local cache."}
    except Exception as exc:
        return {"connected": False, "signals": [], "message": str(exc)}
