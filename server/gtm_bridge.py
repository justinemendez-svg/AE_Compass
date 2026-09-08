"""Read-only GTMI bridge backed by the existing GTM Ops Snowflake connector."""
import json
import os
import re
import sys

repo = os.environ.get("AE_COMPASS_GTM_REPO", "/Users/justine.mendez/Desktop/northstar2026/gtm-ops-claude")
sys.path.insert(0, repo)

try:
    from connections.snowflake import query as snowflake_query
except Exception as exc:
    print(json.dumps({"error": f"GTM/Snowflake connector unavailable: {exc}"}))
    raise SystemExit(0)

try:
    payload = json.load(sys.stdin)
    ids = [
        str(value).strip() for value in payload.get("opportunity_ids", [])
        if re.fullmatch(r"[A-Za-z0-9]{15,18}", str(value).strip())
    ][:50]
    if not ids:
        print(json.dumps([]))
        raise SystemExit(0)
    quoted_ids = ", ".join(f"'{value}'" for value in ids)
    query = f"""
SELECT
    CRM_OPPORTUNITY_ID,
    SOURCE_SNAPSHOT_DATE,
    DATE_LABEL,
    PRODUCT,
    STAGE_NAME,
    OPPORTUNITY_IS_COMMISSIONABLE,
    PRODUCT_ARR_USD,
    PRODUCT_BOOKING_ARR_USD
FROM FUNCTIONAL.GTM_SALES_OPS.GTMSI_CONSOLIDATED_PIPELINE_BOOKINGS
WHERE CRM_OPPORTUNITY_ID IN ({quoted_ids})
  AND (DATE_LABEL = 'today' OR SOURCE_SNAPSHOT_DATE >= DATEADD(day, -7, CURRENT_DATE))
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY CRM_OPPORTUNITY_ID, PRODUCT
    ORDER BY SOURCE_SNAPSHOT_DATE DESC
) = 1
"""
    frame = snowflake_query(query)
    frame.columns = [str(column).lower() for column in frame.columns]
    print(json.dumps(frame.to_dict(orient="records"), default=str))
except Exception as exc:
    print(json.dumps({"error": str(exc)}))
