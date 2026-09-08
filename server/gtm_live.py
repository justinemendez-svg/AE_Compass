"""On-demand GTMI context using the read-only GTM Ops connector."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

BRIDGE = Path(__file__).with_name("gtm_bridge.py")
GTM_REPO = os.environ.get("AE_COMPASS_GTM_REPO", "/Users/justine.mendez/Desktop/northstar2026/gtm-ops-claude")
GTM_PYTHON = os.environ.get("AE_COMPASS_GTM_PYTHON", str(Path(GTM_REPO) / "venv/bin/python"))


def fetch_gtm_context(opportunity_ids: list[str]) -> dict:
    ids = [str(value).strip() for value in opportunity_ids if str(value).strip()][:50]
    if not ids:
        return {"connected": False, "records": [], "message": "No opportunity IDs supplied."}
    if not Path(GTM_PYTHON).exists() or not BRIDGE.exists():
        return {"connected": False, "records": [], "message": "GTM connector is not configured in this environment."}
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
            timeout=30,
            env=env,
        )
        payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {"error": completed.stderr.strip()}
        if isinstance(payload, dict) and payload.get("error"):
            return {"connected": False, "records": [], "message": payload["error"]}
        return {"connected": True, "records": payload if isinstance(payload, list) else [], "message": "Verified GTMI context loaded from the GTM Ops connector."}
    except Exception as exc:
        return {"connected": False, "records": [], "message": str(exc)}
