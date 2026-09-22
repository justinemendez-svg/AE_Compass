"""Read-only Salesforce/Bullseye account adapter for Account Landscape."""

from __future__ import annotations

import json
import re
import subprocess
import os
import sys
import copy
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ACCOUNT_SOQL = """
SELECT Id, Name, OwnerId, Owner.Name, Owner_Role_Name__c,
       zd_account_type__c, zd_account_status__c, Account_ARR_in_USD__c,
       X2014_Renewal_status__c, AE_Prospecting_Tier__c,
       Sell_AE_Prospecting_Tier__c, Bullseye_Fit_Score__c,
       Propensity_Score_Tier__c, Reason_for_Recommendation__c,
       Recommended_AR__c, Recommended_AR_Quantity__c,
       Return_to_Bullseye_Detail__c, Return_to_Bullseye_Value_DateStamp__c,
       Zuora__CustomerPriority__c,
       Product_Plans__c, zd_plan__c, zd_Last_paid_plan__c, CS_Last_Paid_Plan__c,
       Total_Number_of_Seats__c, Support_Agent_Count__c, Sell_Account_Seat_Count_Legacy__c,
       Support_Agents__c, zd_max_agents__c, CS_Max_Agents__c,
       Instance_Rollup_Max_Agents__c, High_Water_Support_Plan__c,
       AE_Health_Status__c, C_C_Score__c
FROM Account
WHERE Junk_Reason__c = null
  AND Account_ARR_in_USD__c >= 0
""".strip()


INSTANCE_SOQL_PREFIX = """
SELECT Account__c, Support_Plan__c, zd_max_agents__c,
       Support_Agents__c, Instance_Status__c
FROM Zendesk_Account__c
WHERE Account__c IN (
""".strip()

_ACCOUNT_CACHE_TTL_SECONDS = 120
_ACCOUNT_CACHE = {}


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return None


def _run_query(soql):
    result = subprocess.run(
        ["sf", "data", "query", "--target-org", "prod", "--query", soql, "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        check=True,
    )
    return json.loads(result.stdout).get("result", {}).get("records", [])


def _fetch_instance_details(account_ids):
    """Read instance-level plan/seat fields and roll them up by Account ID."""
    ids = sorted({str(value).strip() for value in account_ids if str(value).strip()})
    if not ids:
        return {}
    quoted_ids = ", ".join("'" + value.replace("'", "\\'") + "'" for value in ids)
    try:
        records = _run_query(INSTANCE_SOQL_PREFIX + quoted_ids + ")")
    except Exception:
        # Instance enrichment must never hide the verified Account feed.
        return {}

    details = {}
    for record in records:
        instance_status = str(record.get("Instance_Status__c") or "").strip().casefold()
        if instance_status and instance_status != "active":
            continue
        account_id = str(record.get("Account__c") or "").strip()
        if not account_id:
            continue
        item = details.setdefault(account_id, {"plans": [], "max_seats": [], "support_seats": []})
        plan = str(record.get("Support_Plan__c") or "").strip()
        if plan and plan not in item["plans"]:
            item["plans"].append(plan)
        max_seats = _number(record.get("zd_max_agents__c"))
        if max_seats is not None and max_seats not in item["max_seats"]:
            item["max_seats"].append(max_seats)
        support_seats = _number(
            record.get("Support_Agents__c")
        )
        if support_seats is not None and support_seats not in item["support_seats"]:
            item["support_seats"].append(support_seats)
    return details


def _fetch_penetration_details(account_ids):
    """Read current products and account attributes from PENETRATION_DASH."""
    ids = sorted({str(value).strip() for value in account_ids if str(value).strip()})
    if not ids:
        return {}
    bridge = Path(__file__).with_name("penetration_bridge.py")
    gtm_repo = Path(os.environ.get("AE_COMPASS_GTM_REPO", "/Users/justine.mendez/Desktop/northstar2026/gtm-ops-claude"))
    bridge_python = Path(os.environ.get("AE_COMPASS_GTM_PYTHON", str(gtm_repo / "venv/bin/python")))
    if not bridge_python.exists():
        bridge_python = Path(sys.executable)
    try:
        result = subprocess.run(
            [str(bridge_python), str(bridge)],
            input=json.dumps({"account_ids": ids}),
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
            env={**os.environ, "AE_COMPASS_GTM_REPO": str(gtm_repo)},
        )
        payload = json.loads(result.stdout or "{}")
        return payload if isinstance(payload, dict) and "error" not in payload else {}
    except Exception:
        return {}


def fetch_accounts(owner_name=""):
    """Return only source-backed accounts; failures become an empty feed."""
    cache_key = (owner_name or "").strip().casefold()
    cached = _ACCOUNT_CACHE.get(cache_key)
    if cached and time.monotonic() - cached["created_at"] < _ACCOUNT_CACHE_TTL_SECONDS:
        return copy.deepcopy(cached["rows"])
    try:
        owner_filter = (owner_name or "").strip()
        query = ACCOUNT_SOQL
        if owner_filter and owner_filter.casefold() != "all":
            safe_owner = owner_filter.replace("\\", "\\\\").replace("'", "\\'")
            query += f"\n  AND Owner.Name = '{safe_owner}'"
        else:
            # The tab is AE-scoped in normal use. Keep an admin preview bounded
            # so a large org cannot make the local request hang.
            query += "\nLIMIT 5000"
        records = _run_query(query)
    except Exception:
        return []

    account_ids = [record.get("Id") for record in records]
    # These enrichments use independent read-only sources. Run them together
    # so Snowflake latency does not wait behind the Salesforce instance query.
    with ThreadPoolExecutor(max_workers=2) as executor:
        instance_future = executor.submit(_fetch_instance_details, account_ids)
        penetration_future = executor.submit(_fetch_penetration_details, account_ids)
        instance_details = instance_future.result()
        penetration_details = penetration_future.result()

    owner_filter = (owner_name or "").strip().casefold()
    rows = []
    for record in records:
        owner = record.get("Owner") or {}
        owner_value = str(owner.get("Name") or "").strip()
        if owner_filter and owner_filter != "all" and owner_value.casefold() != owner_filter:
            continue
        arr = _number(record.get("Account_ARR_in_USD__c"))
        # Account ARR is the source of truth for the two UI tabs. Negative
        # ARR rows are excluded; zero is new business, positive is customer.
        if arr is None or arr < 0:
            continue
        instance = instance_details.get(str(record.get("Id") or ""), {})
        instance_plans = instance.get("plans", [])
        instance_max_seats = instance.get("max_seats", [])
        instance_support_seats = instance.get("support_seats", [])
        penetration = penetration_details.get(str(record.get("Id") or ""), {})
        rows.append({
            "account_id": str(record.get("Id") or ""),
            "account_name": str(record.get("Name") or ""),
            "owner_name": owner_value,
            "owner_id": str(record.get("OwnerId") or ""),
            "account_type": "Customer" if arr > 0 else "Prospect",
            "account_status": str(record.get("zd_account_status__c") or ""),
            "arr": arr,
            "bullseye_recommendation": str(record.get("Return_to_Bullseye_Detail__c") or ""),
            "bullseye_reason": str(record.get("Reason_for_Recommendation__c") or ""),
            "bullseye_tier": str(
                record.get("AE_Prospecting_Tier__c")
                or record.get("Sell_AE_Prospecting_Tier__c")
                or record.get("Propensity_Score_Tier__c")
                or record.get("Zuora__CustomerPriority__c")
                or ""
            ),
            "bullseye_updated_at": str(record.get("Return_to_Bullseye_Value_DateStamp__c") or ""),
            "current_product": str(penetration.get("current_product") or ""),
            "vertical": str(penetration.get("vertical") or ""),
            "top_3000": str(penetration.get("top_3000") or ""),
            "with_ela": str(penetration.get("with_ela") or ""),
            "cohorts": str(penetration.get("cohorts") or ""),
            "suite_plan": "; ".join(instance_plans) or str(
                record.get("zd_plan__c")
                or record.get("CS_Last_Paid_Plan__c")
                or record.get("zd_Last_paid_plan__c")
                or record.get("High_Water_Support_Plan__c")
                or record.get("Product_Plans__c")
                or ""
            ),
            "csm_health_status": str(record.get("C_C_Score__c") or record.get("X2014_Renewal_status__c") or record.get("AE_Health_Status__c") or ""),
            "avg_monthly_tickets": None,
            "seats": _number(
                record.get("Total_Number_of_Seats__c")
                if record.get("Total_Number_of_Seats__c") is not None
                else record.get("Support_Agent_Count__c")
                if record.get("Support_Agent_Count__c") is not None
                else record.get("Sell_Account_Seat_Count_Legacy__c")
            ),
            "support_seats": sum(instance_support_seats) if instance_support_seats else _number(record.get("Support_Agent_Count__c") if record.get("Support_Agent_Count__c") is not None else record.get("Support_Agents__c")),
            "max_seats": _number(
                sum(instance_max_seats) if instance_max_seats else
                record.get("Instance_Rollup_Max_Agents__c")
                if record.get("Instance_Rollup_Max_Agents__c") is not None
                else record.get("CS_Max_Agents__c")
                if record.get("CS_Max_Agents__c") is not None
                else record.get("zd_max_agents__c")
            ),
            "opportunities": [],
            "source": "Salesforce Account + Bullseye fields",
        })
    _ACCOUNT_CACHE[cache_key] = {"created_at": time.monotonic(), "rows": copy.deepcopy(rows)}
    return rows


def attach_opportunities(accounts, opportunities):
    """Attach verified opportunity rows using Account ID, then exact name."""
    by_id = {}
    by_name = {}
    for row in opportunities or []:
        account_id = str(row.get("crm_account_id") or "")
        account_name = str(row.get("crm_account_name") or "").strip().casefold()
        if account_id:
            by_id.setdefault(account_id, []).append(row)
        if account_name:
            by_name.setdefault(account_name, []).append(row)
    for account in accounts:
        matches = by_id.get(account["account_id"], []) or by_name.get(account["account_name"].casefold(), [])
        account["opportunities"] = [
            {
                "id": row.get("crm_opportunity_id"),
                "name": row.get("opportunity_name"),
                "stage": row.get("stage_name"),
                "arr": row.get("product_arr_usd"),
                "close_date": row.get("closedate"),
                "status": row.get("opportunity_status"),
            }
            for row in matches
            if row.get("crm_opportunity_id")
        ]
    return accounts
