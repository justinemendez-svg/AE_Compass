"""Read-only live Salesforce Opportunity pull for local AE Compass."""

import json
import re
import subprocess
from datetime import date

try:
    from quarter_utils import canonical_quarter
except ModuleNotFoundError:
    from server.quarter_utils import canonical_quarter


SOQL = """
SELECT Id, Name, OwnerId, Owner.Name, StageName, Type, CloseDate,
       Total_Commissionable_ARR_in_USD__c, Non_Commissionable__c,
       ForecastCategoryName
FROM Opportunity
WHERE StageName IN ('01 - Qualify Need','02 - Confirm Need','03 - Establish Value',
                    '04 - Demonstrate Value','05 - Secure Commitment',
                    '06 - Contracting','07 - Signed','08 - Closed')
  AND Non_Commissionable__c = false
  AND Total_Commissionable_ARR_in_USD__c > 0
  AND CloseDate = THIS_FISCAL_QUARTER
""".strip()


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_live():
    result = subprocess.run(
        ["sf", "data", "query", "--target-org", "prod", "--query", SOQL, "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        check=True,
    )
    payload = json.loads(result.stdout)
    records = payload.get("result", {}).get("records", [])
    rows = []
    for record in records:
        owner = record.get("Owner") or {}
        stage = str(record.get("StageName") or "")
        amount = _number(record.get("Total_Commissionable_ARR_in_USD__c"))
        close_date = str(record.get("CloseDate") or "")[:10]
        rows.append({
            "ownerid": record.get("OwnerId") or "",
            "opportunity_owner_name": owner.get("Name") or "",
            "crm_opportunity_id": record.get("Id") or "",
            "opportunity_name": record.get("Name") or "",
            "crm_account_name": "",
            "stage_name": stage,
            "opportunity_type": record.get("Type") or "",
            "opportunity_status": "Closed" if re.match(r"^0[78]", stage) else "Open",
            "product": "Total Booking",
            "product_arr_usd": amount,
            "product_booking_arr_usd": amount,
            "closedate": close_date,
            "close_year_quarter": canonical_quarter("", close_date),
            "opportunity_is_commissionable": True,
            "vp_deal_forecast__c": record.get("ForecastCategoryName") or "",
            "manager_forecast__c": "",
            "gtm_team": "",
            "stage_2_plus_date_c": "",
            "d_score_latest__c": "",
            "date_label": "today",
            "current_vp_team": "",
            "current_dir_team": "",
            "current_mgr_team": "",
            "pro_forma_market_segment": "",
            "manager_name": "",
            "director_name": "",
            "rvp_name": "",
            "svp_name": "",
        })
    return rows
