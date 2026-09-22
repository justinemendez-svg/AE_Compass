"""Read-only current-product enrichment from the GTM Ops Snowflake connector."""

from __future__ import annotations

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


PRODUCT_FIELDS = [
    ("WITH_COPILOT_PRODUCT_ANALYTICS_CURRENT_DATE", "Copilot"),
    ("WITH_AI_AGENTS_PRODUCT_ANALYTICS_CURRENT_DATE", "AI Agents"),
    ("WITH_ES_CURRENT_DATE", "ES"),
    ("WITH_WEM_CURRENT_DATE", "WEM"),
    ("WITH_FORETHOUGHT_CURRENT_DATE", "Forethought"),
    ("WITH_ADPP_CURRENT_DATE", "ADPP"),
    ("WITH_PROFSERV_CURRENT_DATE", "ProfServ"),
    ("WITH_ZENDESK_AR_CURRENT_DATE", "Zendesk AR"),
    ("WITH_CONTACT_CENTER_CURRENT_DATE", "Contact Center"),
    ("WITH_ULTIMATE_CURRENT_DATE", "Ultimate"),
    ("WITH_ULTIMATE_AR_CURRENT_DATE", "Ultimate AR"),
    ("WITH_QA_CURRENT_DATE", "QA"),
    ("WITH_WFM_CURRENT_DATE", "WFM"),
]


def _is_true(value):
    return value is True or str(value).strip().casefold() in {"true", "1", "t", "yes"}


def _yes_no(value):
    if value is None or str(value).strip().casefold() in {"", "nan", "none"}:
        return ""
    return "Yes" if _is_true(value) else "No"


def _text(value):
    text = str(value or "").strip()
    return "" if text.casefold() in {"nan", "none"} else text


try:
    payload = json.load(sys.stdin)
    ids = [
        str(value).strip()
        for value in payload.get("account_ids", [])
        if re.fullmatch(r"001[A-Za-z0-9]{12,15}", str(value).strip())
    ][:2000]
    if not ids:
        print(json.dumps({}))
        raise SystemExit(0)

    quoted_ids = ", ".join("'" + value.replace("'", "''") + "'" for value in ids)
    columns = ["CRM_ACCOUNT_ID", "KEY_VERTICALS", "TOP_3000_FLAG", "WITH_ELA_CURRENT_DATE", "COHORTS"]
    columns += [field for field, _ in PRODUCT_FIELDS]
    query = f"""
SELECT {', '.join(columns)}
FROM FUNCTIONAL.GTM_SALES_OPS.PENETRATION_DASH
WHERE CRM_ACCOUNT_ID IN ({quoted_ids})
"""
    frame = snowflake_query(query)
    frame.columns = [str(column).upper() for column in frame.columns]

    enriched = {}
    for row in frame.to_dict(orient="records"):
        account_id = str(row.get("CRM_ACCOUNT_ID") or "").strip()
        if not account_id:
            continue
        wem_present = _is_true(row.get("WITH_WEM_CURRENT_DATE"))
        products = []
        for field, label in PRODUCT_FIELDS:
            if label in {"QA", "WFM"} and wem_present:
                continue
            if _is_true(row.get(field)):
                products.append(label)
        enriched[account_id] = {
            "current_product": "; ".join(products),
            "vertical": _text(row.get("KEY_VERTICALS")),
            "top_3000": _yes_no(row.get("TOP_3000_FLAG")),
            "with_ela": _yes_no(row.get("WITH_ELA_CURRENT_DATE")),
            "cohorts": _text(row.get("COHORTS")),
        }
    print(json.dumps(enriched, default=str))
except Exception as exc:
    print(json.dumps({"error": str(exc)}))
