"""Small read-only bridge to the existing GTM Ops Gong connector.

AE Compass stays self-contained: this helper only runs when the local
reference connector is present and returns the requested opportunity calls as
JSON. No Gong data is copied into the UI bundle.
"""
import json
import os
import re
import sys

repo = os.environ.get("AE_COMPASS_GTM_REPO", "/Users/justine.mendez/Desktop/northstar2026/gtm-ops-claude")
sys.path.insert(0, repo)

try:
    from connections.snowflake import query as snowflake_query
except Exception as exc:  # pragma: no cover - depends on local connector setup
    print(json.dumps({"error": f"Gong/Snowflake connector unavailable: {exc}"}))
    raise SystemExit(0)

try:
    payload = json.load(sys.stdin)
    ids = [str(value).strip() for value in payload.get("opportunity_ids", []) if re.fullmatch(r"[A-Za-z0-9]{15,18}", str(value).strip())]
    if not ids:
        print(json.dumps([]))
        raise SystemExit(0)
    quoted_ids = ", ".join(f"'{value}'" for value in ids[:50])
    query = f"""
WITH ctx AS (
    SELECT DISTINCT OBJECT_ID, CONVERSATION_KEY
    FROM CLEANSED.GONG.GONG_CONVERSATION_CONTEXTS_BCV
    WHERE OBJECT_ID IN ({quoted_ids})
), calls AS (
    SELECT CONVERSATION_KEY, TITLE, CALL_SPOTLIGHT_BRIEF,
           CALL_SPOTLIGHT_NEXT_STEPS, CALL_SPOTLIGHT_KEY_POINTS,
           PLANNED_START_DATETIME
    FROM CLEANSED.GONG.GONG_CALLS_BCV
    WHERE CALL_SPOTLIGHT_BRIEF IS NOT NULL
      AND TRIM(CALL_SPOTLIGHT_BRIEF) <> ''
)
SELECT ctx.OBJECT_ID AS CRM_OPPORTUNITY_ID,
       ctx.CONVERSATION_KEY,
       calls.TITLE,
       calls.PLANNED_START_DATETIME,
       calls.CALL_SPOTLIGHT_BRIEF,
       calls.CALL_SPOTLIGHT_NEXT_STEPS,
       calls.CALL_SPOTLIGHT_KEY_POINTS
FROM ctx
JOIN calls ON ctx.CONVERSATION_KEY = calls.CONVERSATION_KEY
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY ctx.OBJECT_ID
    ORDER BY calls.PLANNED_START_DATETIME DESC
) = 1
"""
    frame_df = snowflake_query(query)
    frame_df.columns = [str(column).lower() for column in frame_df.columns]
    frame = frame_df.to_dict(orient="records")
    print(json.dumps(frame, default=str))
except Exception as exc:  # pragma: no cover - live connector failure is surfaced safely
    print(json.dumps({"error": str(exc)}))
