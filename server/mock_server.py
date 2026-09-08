"""
AE Compass local data server — a zero-dependency local adapter for the
verified Workday, Clari, GTMI, and Salesforce extracts.

It never invents dashboard records. When a source extract is unavailable, the
API returns an empty result so the UI can show a clear data-status message.

Run:  python3 server/mock_server.py   (listens on PORT, default 8080)

User-generated content (notes, action items, competencies, weekly tracker,
deal maps, quotas) is persisted to server/mock_state.json so your tinkering
survives restarts. Delete that file to reset.
"""

import json
import csv
import os
import random
import re
import datetime
import cgi
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from quarter_utils import canonical_quarter
from sfdc_live import fetch_live
from gong_live import fetch_gong_signals
from assistant import AssistantUnavailable, answer_question

STATE_FILE = Path(__file__).parent / "mock_state.json"
UPLOAD_DIR = Path(__file__).parent / "uploads"
LOCAL_AUTH_EMAIL = os.environ.get("AE_COMPASS_LOCAL_EMAIL", "justine.mendez@zendesk.com").strip().lower()
DRIVE_HIERARCHY_FILE = Path("/Users/justine.mendez/Library/CloudStorage/GoogleDrive-justine.mendez@zendesk.com/Shared drives/GTM Ops/APAC/AE Compass/workday_hierarchy_chris_donato.csv")
CLARI_FORECAST_FILE = DRIVE_HIERARCHY_FILE.parent / "clari_forecast_current_quarter.csv"
PIPELINE_EXPORT_FILE = Path(os.environ.get("PIPELINE_EXPORT_FILE", str(DRIVE_HIERARCHY_FILE.parent / "gtmsi_pipeline_current_quarter.csv")))
SFDC_EXPORT_FILE = Path(os.environ.get("SFDC_EXPORT_FILE", str(DRIVE_HIERARCHY_FILE.parent / "salesforce_opportunities_current_quarter.csv")))
WORKDAY_USERS = []

def source_data_as_of():
    """Return the latest verified local extract timestamp, when available."""
    paths = [CLARI_FORECAST_FILE, PIPELINE_EXPORT_FILE, SFDC_EXPORT_FILE]
    timestamps = [path.stat().st_mtime for path in paths if path.exists()]
    if not timestamps:
        return None
    return datetime.datetime.fromtimestamp(max(timestamps)).isoformat(timespec="seconds")

def workday_access_type(user):
    title = (user.get("JOB_TITLE") or user.get("BUSINESS_TITLE") or "").lower()
    level = (user.get("MANAGEMENT_LEVEL") or "").lower()
    if "account executive" in title or "sales representative" in title:
        return "AE"
    if "senior vice president" in title or "regional evp" in title or "svp" in level:
        return "SVP"
    if "director" in title or "director" in level:
        return "Director"
    if "vice president" in title or "rvp" in level:
        return "RVP"
    if "manager" in title or "manager" in level or "leader" in title:
        return "FLM"
    # Workday staff who are not sales roles must never be labelled as AEs.
    return "GTM"

def auth_identity(handler):
    """Mirror App Foundry identity injection.

    App Foundry supplies the signed-in employee email in X-Forwarded-Email.
    The local fallback is intentionally development-only and can be replaced
    with AE_COMPASS_LOCAL_EMAIL while testing a known local identity.
    """
    forwarded = (handler.headers.get("X-Forwarded-Email") or "").strip().lower()
    email = forwarded or LOCAL_AUTH_EMAIL
    source = "appfoundry" if forwarded else "local-development-fallback"
    for user in WORKDAY_USERS:
        if (user.get("EMAIL") or "").strip().lower() != email:
            continue
        access_type = workday_access_type(user)
        # A leader's own row may not repeat their name in its C_STAFF field;
        # use the authenticated person's canonical name as the scope key.
        scope_value = (user.get("FULL_NAME") or "").strip()
        is_admin = email == "justine.mendez@zendesk.com"
        return {"authenticated": True, "email": email, "name": user.get("FULL_NAME"), "subject_id": str(user.get("EMPLOYEE_ID") or ""), "role": "Admin" if is_admin else access_type, "access_level": "full" if is_admin else ("hierarchy" if access_type != "AE" else "own profile"), "scope_value": "all" if is_admin else scope_value, "source": source}
    for person in get_roster():
        expected = re.sub(r"[^a-z0-9]+", ".", person["ae_name"].lower()).strip(".") + "@zendesk.com"
        if email == expected:
            return {"authenticated": True, "email": email, "name": person["ae_name"], "subject_id": person["user_id"], "role": "AE", "access_level": "scoped", "source": source}
    return {"authenticated": False, "email": email, "name": None, "subject_id": None, "role": None, "access_level": None, "source": source}

# ─── FISCAL CALENDAR ──────────────────────────────────────────────────────────
QUARTERS = ["FY2027Q1", "FY2027Q2", "FY2027Q3", "FY2027Q4"]
FQ_MAP = {
    "FY2027Q1": ("2026-02-01", "2026-04-30"),
    "FY2027Q2": ("2026-05-01", "2026-07-31"),
    "FY2027Q3": ("2026-08-01", "2026-10-31"),
    "FY2027Q4": ("2026-11-01", "2027-01-31"),
    "FY2028Q1": ("2027-02-01", "2027-04-30"),
}

AI_PRODUCTS = ["AI_Expert", "Copilot", "Ultimate", "Ultimate_AR", "Zendesk_AR", "QA", "WEM", "Forethought_AI_Agents"]
CORE_PRODUCTS = ["Support", "Suite", "Sell", "Talk", "Guide", "Chat"]
OPEN_STAGES = ["02 - Prospect", "03 - Qualify", "04 - Validate", "05 - Negotiate", "06 - Legal/Contract"]
WON_STAGES = ["07 - Signed", "08 - Closed"]

def is_pipeline_stage(stage):
    match = re.match(r"^(\d+)", (stage or "").strip())
    return bool(match) and 2 <= int(match.group(1)) <= 6
SEGMENTS = ["Enterprise", "Commercial", "Mid-Market", "SMB"]
FORECASTS = ["Commit", "Best Case", "Pipeline", "Omitted"]

FIRST_NAMES = ["James", "Maria", "David", "Sarah", "Michael", "Emma", "Daniel", "Olivia", "Chris", "Ava",
               "Ryan", "Sofia", "Kevin", "Laura", "Brian", "Nina", "Alex", "Priya", "Tom", "Grace",
               "Lucas", "Chloe", "Ethan", "Isla", "Noah", "Zoe", "Liam", "Mia", "Owen", "Ruby",
               "Marco", "Elena", "Hugo", "Amara", "Felix", "Yuki", "Omar", "Lena", "Ravi", "Anna"]
LAST_NAMES = ["Smith", "Garcia", "Chen", "Patel", "Johnson", "Kim", "Brown", "Nguyen", "Silva", "Muller",
              "Rossi", "Dubois", "Hansen", "Costa", "Novak", "Ahmed", "Tanaka", "Lopez", "Wagner", "Ivanov",
              "Andersson", "Reyes", "Fischer", "Okafor", "Bianchi", "Haddad", "Sato", "Moreau", "Klein", "Petrov"]

ACCOUNT_WORDS = ["Acme", "Globex", "Initech", "Umbrella", "Soylent", "Hooli", "Stark", "Wayne", "Wonka",
                 "Cyberdyne", "Aperture", "Tyrell", "Nakatomi", "Vandelay", "Pied Piper", "Massive Dynamic",
                 "Gekko", "Oscorp", "Bluth", "Prestige", "Sterling", "Dunder Mifflin", "Vehement", "Kruger"]
ACCOUNT_SUFFIX = ["Corp", "Inc", "Group", "Labs", "Systems", "Technologies", "Global", "Solutions", "Industries"]


def make_generator():
    """Deterministically generate a full fake org + pipeline dataset."""
    rng = random.Random(42)

    def person():
        return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"

    # Local fallback hierarchy seed. The running Compass uses the Workday
    # export when it is available.
    svps = [
        "Adrian Fallow",
        "Andy Lawson",
        "Eduardo Lugo",
        "Jamie O'Dyer",
        "Jim Priestley",
        "Mitch Young",
    ]

    roster = []          # one row per AE (dashboard roster)
    rows = []            # pipeline_data-equivalent rows
    uid = 1000
    oppid = 500000

    for svp in svps:
        for _ in range(2):                       # RVPs per SVP
            rvp = person()
            vp_team = f"{rvp.split()[0]}'s Region"
            for _ in range(2):                   # Directors per RVP
                director = person()
                dir_team = f"{director.split()[0]} Dir Team"
                for _ in range(rng.randint(2, 3)):   # Managers per Director
                    manager = person()
                    mgr_team = f"{manager.split()[0]} Mgr Team"
                    for _ in range(rng.randint(3, 5)):   # AEs per Manager
                        uid += 1
                        ae_name = person()
                        user_id = f"005{uid:07d}AE"
                        segment = rng.choice(SEGMENTS)
                        roster.append({
                            "user_id": user_id,
                            "ae_name": ae_name,
                            "vp_team_c": vp_team,
                            "dir_team_c": dir_team,
                            "mgr_team_c": mgr_team,
                            "market_segment_c": segment,
                            "manager_name": manager,
                            "director_name": director,
                            "rvp_name": rvp,
                            "svp_name": svp,
                        })

                        # Generate deals for this AE across quarters
                        for quarter in QUARTERS:
                            n_deals = rng.randint(2, 6)
                            for _ in range(n_deals):
                                oppid += 1
                                opp_id = f"006{oppid:07d}"
                                won = rng.random() < 0.45
                                stage = rng.choice(WON_STAGES) if won else rng.choice(OPEN_STAGES)
                                status = "Closed" if won else "Open"
                                otype = "New Business" if rng.random() < 0.55 else "Expansion"
                                total_amount = round(rng.uniform(15000, 450000), 2)

                                acct = f"{rng.choice(ACCOUNT_WORDS)} {rng.choice(ACCOUNT_SUFFIX)}"
                                opp_name = f"{acct} - {otype}"

                                qstart, qend = FQ_MAP[quarter]
                                d0 = datetime.date.fromisoformat(qstart)
                                d1 = datetime.date.fromisoformat(qend)
                                closedate = (d0 + datetime.timedelta(
                                    days=rng.randint(0, (d1 - d0).days))).isoformat()
                                # stage 2+ date: sometime in the ~90 days before close
                                s2date = (datetime.date.fromisoformat(closedate) -
                                          datetime.timedelta(days=rng.randint(10, 80))).isoformat()

                                dscore = str(rng.randint(40, 95))
                                vpf = rng.choice(FORECASTS)
                                mgrf = rng.choice(FORECASTS)

                                base = {
                                    "ownerid": user_id,
                                    "opportunity_owner_name": ae_name,
                                    "crm_opportunity_id": opp_id,
                                    "opportunity_name": opp_name,
                                    "crm_account_name": acct,
                                    "stage_name": stage,
                                    "opportunity_type": otype,
                                    "opportunity_status": status,
                                    "closedate": closedate,
                                    "stage_2_plus_date_c": s2date,
                                    "gtm_team": segment,
                                    "vp_deal_forecast__c": vpf,
                                    "manager_forecast__c": mgrf,
                                    "close_year_quarter": quarter,
                                    "d_score_latest__c": dscore,
                                    "opportunity_is_commissionable": True,
                                    "current_vp_team": vp_team,
                                    "current_dir_team": dir_team,
                                    "current_mgr_team": mgr_team,
                                    "pro_forma_market_segment": segment,
                                    "manager_name": manager,
                                    "director_name": director,
                                    "rvp_name": rvp,
                                    "svp_name": svp,
                                }

                                booking = total_amount if won else 0.0

                                # Total Booking aggregate row
                                rows.append({**base,
                                             "product": "Total Booking",
                                             "product_arr_usd": total_amount,
                                             "product_booking_arr_usd": booking})

                                # Split the amount across 1-3 component products
                                pool = rng.sample(AI_PRODUCTS + CORE_PRODUCTS, rng.randint(1, 3))
                                weights = [rng.random() for _ in pool]
                                wsum = sum(weights) or 1
                                for prod, w in zip(pool, weights):
                                    share = round(total_amount * w / wsum, 2)
                                    rows.append({**base,
                                                 "product": prod,
                                                 "product_arr_usd": share,
                                                 "product_booking_arr_usd": round(booking * w / wsum, 2)})
    return roster, rows


ROSTER, ROWS = [], []


def load_drive_hierarchy():
    """Build the AE roster from the latest Workday hierarchy export."""
    if not DRIVE_HIERARCHY_FILE.exists():
        return None
    try:
        with DRIVE_HIERARCHY_FILE.open(newline="", encoding="utf-8-sig") as handle:
            users = list(csv.DictReader(handle))
        # Keep the local Compass directory aligned with the Workday extract
        # contract, even if a future upload contains extra rows.
        users = [
            user for user in users
            if (user.get("C_STAFF") or "").strip() == "Chris Donato"
            and (user.get("WORKER_STATUS") or "1").strip().lower() in {"1", "true", "active"}
            and (user.get("_FIVETRAN_DELETED") or "false").strip().lower() in {"false", "0", "no", ""}
        ]
        global WORKDAY_USERS
        WORKDAY_USERS = users
        actual = []
        for user in users:
            title = (user.get("JOB_TITLE") or user.get("BUSINESS_TITLE") or "").strip()
            if not re.search(r"account executive|sales representative", title, re.IGNORECASE):
                continue
            # Workday already materializes the requested reporting path.
            svp_name = (user.get("C_STAFF_1") or "").strip() or None
            rvp_name = (user.get("C_STAFF_2") or "").strip() or None
            director_name = (user.get("C_STAFF_3") or "").strip() or None
            manager_name = (user.get("C_STAFF_4") or "").strip() or None
            actual.append({
                "user_id": user.get("EMPLOYEE_ID", "").strip(),
                "ae_name": user.get("FULL_NAME", "").strip(),
                "vp_team_c": rvp_name or "",
                "dir_team_c": director_name or "",
                "mgr_team_c": manager_name or "",
                "market_segment_c": (user.get("REGION") or "").strip(),
                "manager_name": manager_name,
                "director_name": director_name,
                "rvp_name": rvp_name,
                "svp_name": svp_name,
                "email": (user.get("EMAIL") or "").strip().lower(),
                "title": title,
                "access_type": "AE",
                "access_level": "own profile",
            })
        return actual or None
    except Exception:
        return None


def load_pipeline_export():
    """Load the manually refreshed GTMSI export and normalize its fields."""
    if not PIPELINE_EXPORT_FILE.exists():
        return None

    try:
        with PIPELINE_EXPORT_FILE.open(newline="", encoding="utf-8-sig") as handle:
            source_rows = list(csv.DictReader(handle))
        rows = []
        for source in source_rows:
            row = {(key or "").strip().lower(): (value or "").strip() for key, value in source.items()}
            closedate = row.get("closedate") or row.get("closed_date") or row.get("close_date") or row.get("closed date") or ""
            def number(key):
                try:
                    return float(str(row.get(key, "0")).replace(",", "") or 0)
                except (TypeError, ValueError):
                    return 0.0
            def optional(*keys):
                for key in keys:
                    if key in row:
                        return row[key] or None
                return None
            def bool_value(value):
                if value is None or str(value).strip() == "":
                    return None
                return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}
            is_sfdc_opportunity = "booking_arr__c" in row or "booking_arr_c" in row
            non_commissionable = (row.get("non_commissionable__c") or row.get("non_commissionable_c") or
                                  row.get("non-commissionable__c") or row.get("non-commissionable") or
                                  row.get("non_commissionable"))
            if is_sfdc_opportunity and ((non_commissionable is None or str(non_commissionable).strip().lower() in {"true", "1", "yes", "t"}) or number("booking_arr__c") <= 0):
                continue
            rows.append({
                "ownerid": row.get("ownerid", ""), "opportunity_owner_name": row.get("opportunity_owner_name", ""),
                "crm_opportunity_id": row.get("crm_opportunity_id", ""), "opportunity_name": row.get("opportunity_name", ""),
                "crm_account_name": row.get("crm_account_name", ""), "stage_name": row.get("stage_name", ""),
                "opportunity_type": row.get("opportunity_type", ""), "opportunity_status": row.get("opportunity_status", ""),
                "product": row.get("product", ""), "product_arr_usd": number("product_arr_usd"),
                "product_booking_arr_usd": number("booking_arr__c") or number("booking_arr_c") or number("product_booking_arr_usd"),
                "closedate": closedate, "stage_2_plus_date_c": row.get("stage_2_plus_date_c", ""), "gtm_team": row.get("gtm_team", ""),
                "vp_deal_forecast__c": row.get("vp_deal_forecast__c", ""), "manager_forecast__c": row.get("manager_forecast__c", ""),
                "quote_status": optional("quote_status", "quote", "cpq_quote_status", "has_quote"),
                "has_executive_relationships": bool_value(optional("has_executive_relationships", "has executive relationships", "has_executive_relationships__c", "executive_relationships")),
                "zendesk_executive_connect": optional("zendesk_executive_connect", "zendesk executive connect", "zendesk_executive_connect__c", "executive_connect"),
                "close_year_quarter": canonical_quarter(row.get("close_year_quarter"), closedate),
                "d_score_latest__c": row.get("d_score_latest__c", ""), "date_label": row.get("date_label", "today"),
                "opportunity_is_commissionable": row.get("opportunity_is_commissionable", "true").lower() in {"true", "1", "yes", "t"},
                "current_vp_team": row.get("current_vp_team", ""), "current_dir_team": row.get("current_dir_team", ""),
                "current_mgr_team": row.get("current_mgr_team", ""), "pro_forma_market_segment": row.get("pro_forma_market_segment", ""),
                "manager_name": row.get("manager_name", ""), "director_name": row.get("director_name", ""),
                "rvp_name": row.get("rvp_name", ""), "svp_name": row.get("svp_name", ""),
            })
        return rows or None
    except Exception:
        return None


def load_sfdc_signed_export(path=None, content=None, filename=""):
    """Load Salesforce Opportunities as the source of truth for Signed.

    Salesforce exports are intentionally kept separate from GTMI.  GTMI owns
    open pipeline; SFDC owns signed value.  Only commissionable, positive ARR
    opportunities in stages 07/08 are eligible.
    """
    try:
        if content is not None:
            text = content.decode("utf-8-sig", errors="replace")
            delimiter = "\t" if filename.lower().endswith(".tsv") else ","
            source_rows = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
        elif path and path.exists():
            with path.open(newline="", encoding="utf-8-sig") as handle:
                source_rows = list(csv.DictReader(handle))
        else:
            return None

        def clean(source):
            return {(key or "").strip().lower(): (value or "").strip() for key, value in source.items()}

        def first(row, *keys):
            for key in keys:
                value = row.get(key.lower(), "")
                if value != "":
                    return value
            return ""

        def number(value):
            try:
                return float(str(value or "0").replace(",", "").replace("$", "").strip() or 0)
            except (TypeError, ValueError):
                return 0.0

        def false_value(value):
            return str(value or "").strip().lower() in {"false", "0", "no", "n", "f"}

        rows = []
        for source in source_rows:
            row = clean(source)
            stage = first(row, "stagename", "stage_name", "stage", "stage name").strip()
            stage_number = re.match(r"^(\d+)", stage)
            if not stage_number or int(stage_number.group(1)) not in {1, 2, 3, 4, 5, 6, 7, 8}:
                continue
            booking = number(first(row, "booking_arr__c", "booking_arr_c", "booking arr", "booking_arr"))
            total_commissionable = number(first(row, "total_commissionable_arr_c", "total_commissionable_arr", "total commissionable arr"))
            non_commissionable = first(row, "non-commissionable", "non_commissionable", "non_commissionable__c", "non-commissionable__c")
            # Salesforce report uses TOTAL_COMMISSIONABLE_ARR_C for both
            # open pipeline and signed; GTMI is the source with separate ARR
            # versus booking-ARR fields.
            eligible_amount = total_commissionable
            if booking <= 0 or eligible_amount <= 0 or not false_value(non_commissionable):
                continue
            closedate = first(row, "closedate", "close_date", "close date")
            rows.append({
                "ownerid": first(row, "ownerid", "owner_id", "opportunity_owner_id"),
                "opportunity_owner_name": first(row, "opportunity owner", "opportunity_owner_name", "opportunity owner name", "owner.name", "owner_name"),
                "crm_opportunity_id": first(row, "id", "opportunity_id", "crm_opportunity_id"),
                "opportunity_name": first(row, "name", "opportunity_name", "opportunity name"),
                "crm_account_name": first(row, "account.name", "account_name", "crm_account_name", "account name"),
                "stage_name": stage,
                "opportunity_type": first(row, "type", "opportunity_type", "opportunity type"),
                "opportunity_status": "Closed" if int(stage_number.group(1)) in {7, 8} else "Open",
                "product": first(row, "product", "product_name") or "Total Booking",
                "product_arr_usd": total_commissionable,
                "product_booking_arr_usd": total_commissionable,
                "closedate": closedate,
                "close_year_quarter": canonical_quarter(first(row, "close_year_quarter", "close_fiscal_quarter"), closedate),
                "opportunity_is_commissionable": True,
                "gtm_team": first(row, "gtm_team", "team"),
            })
        return rows
    except Exception:
        return None
    try:
        with PIPELINE_EXPORT_FILE.open(newline="", encoding="utf-8-sig") as handle:
            source_rows = list(csv.DictReader(handle))
        rows = []
        for source in source_rows:
            row = {(key or "").strip().lower(): (value or "").strip() for key, value in source.items()}
            closedate = row.get("closedate") or row.get("closed_date") or row.get("close_date") or row.get("closed date") or ""
            def number(key):
                try:
                    return float(str(row.get(key, "0")).replace(",", "") or 0)
                except (TypeError, ValueError):
                    return 0.0
            is_sfdc_opportunity = "booking_arr__c" in row or "booking_arr_c" in row
            non_commissionable = (
                row.get("non_commissionable__c")
                or row.get("non_commissionable_c")
                or row.get("non-commissionable__c")
                or row.get("non-commissionable")
                or row.get("non_commissionable")
            )
            if is_sfdc_opportunity and (
                (non_commissionable is None or str(non_commissionable).strip().lower() in {"true", "1", "yes", "t"})
                or number("booking_arr__c") <= 0
            ):
                continue
            rows.append({
                "ownerid": row.get("ownerid", ""), "opportunity_owner_name": row.get("opportunity_owner_name", ""),
                "crm_opportunity_id": row.get("crm_opportunity_id", ""), "opportunity_name": row.get("opportunity_name", ""),
                "crm_account_name": row.get("crm_account_name", ""), "stage_name": row.get("stage_name", ""),
                "opportunity_type": row.get("opportunity_type", ""), "opportunity_status": row.get("opportunity_status", ""),
                "product": row.get("product", ""), "product_arr_usd": number("product_arr_usd"),
                # Salesforce Opportunity exports call this Booking_ARR__c;
                # GTMSI exports call it product_booking_arr_usd.
                "product_booking_arr_usd": number("booking_arr__c") or number("booking_arr_c") or number("product_booking_arr_usd"), "closedate": closedate,
                "stage_2_plus_date_c": row.get("stage_2_plus_date_c", ""), "gtm_team": row.get("gtm_team", ""),
                "vp_deal_forecast__c": row.get("vp_deal_forecast__c", ""), "manager_forecast__c": row.get("manager_forecast__c", ""),
                "quote_status": row.get("quote_status") or row.get("quote") or row.get("cpq_quote_status") or row.get("has_quote"),
                "has_executive_relationships": row.get("has_executive_relationships") or row.get("has executive relationships"),
                "zendesk_executive_connect": row.get("zendesk_executive_connect") or row.get("zendesk executive connect") or row.get("executive_connect"),
                "close_year_quarter": canonical_quarter(row.get("close_year_quarter"), closedate),
                "d_score_latest__c": row.get("d_score_latest__c", ""), "date_label": row.get("date_label", "today"),
                "opportunity_is_commissionable": row.get("opportunity_is_commissionable", "true").lower() in {"true", "1", "yes", "t"},
                "current_vp_team": row.get("current_vp_team", ""), "current_dir_team": row.get("current_dir_team", ""),
                "current_mgr_team": row.get("current_mgr_team", ""), "pro_forma_market_segment": row.get("pro_forma_market_segment", ""),
                "manager_name": row.get("manager_name", ""), "director_name": row.get("director_name", ""),
                "rvp_name": row.get("rvp_name", ""), "svp_name": row.get("svp_name", ""),
            })
        return rows or None
    except Exception:
        return None


DRIVE_ROSTER = load_drive_hierarchy()
SFDC_EXPORT_ROWS = load_sfdc_signed_export(SFDC_EXPORT_FILE) or []
try:
    SFDC_ROWS = fetch_live()
except Exception:
    # Local CSV remains a safe offline fallback when Salesforce CLI auth is
    # unavailable. It is never mixed with GTMI rows.
    SFDC_ROWS = SFDC_EXPORT_ROWS
if DRIVE_ROSTER:
    ROSTER = DRIVE_ROSTER
    # Never attach synthetic performance to real people. Actual performance
    # will arrive through the separate manual performance export.
    ROWS = []

PIPELINE_EXPORT = load_pipeline_export()
if PIPELINE_EXPORT:
    ROWS = PIPELINE_EXPORT


# ─── PERSISTENT USER STATE ────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"notes": {}, "actions": {}, "competencies": {}, "weekly": {}, "dealmaps": {}, "quotas": {}, "uploads": []}


STATE = load_state()
STATE.setdefault("uploads", [])


def save_state():
    STATE_FILE.write_text(json.dumps(STATE, indent=2))


# ─── QUERY HELPERS (mirror the SQL in app.py) ─────────────────────────────────
def scope_filter(row, q):
    """Apply the local role hierarchy scope precedence."""
    if q.get("all"):
        return True
    if q.get("owner_name"):
        # The dashboard selection comes from Workday FULL_NAME. Resolve the
        # SFDC owner through the joined Salesforce User name; never compare a
        # Workday employee ID directly to Salesforce OWNER_ID.
        return (row.get("opportunity_owner_name") or "").strip().casefold() == q["owner_name"].strip().casefold()
    if q.get("owner_id"):
        return row["ownerid"] == q["owner_id"]
    if q.get("mgr_team"):
        return row["current_mgr_team"] == q["mgr_team"]
    if q.get("dir_team"):
        return row["current_dir_team"] == q["dir_team"]
    if q.get("vp_team"):
        return row["current_vp_team"] == q["vp_team"]
    if q.get("svp_name"):
        return row["svp_name"] == q["svp_name"]
    return None  # no scope


def has_scope(q):
    return any(q.get(k) for k in ("owner_id", "owner_name", "mgr_team", "dir_team", "vp_team", "svp_name", "all"))


def get_roster():
    return ROSTER


def get_forecast(q):
    name = (q.get("name") or "").strip()
    quarter = q.get("quarter", "FY2027Q3")
    if not name or not CLARI_FORECAST_FILE.exists():
        return {"name": name, "quarter": quarter, "quota": 0, "forecast": 0, "bookings": 0, "ai_target": 0, "ai_bookings": 0, "nb_target": 0, "nb_bookings": 0, "pipeline": 0, "pipeline_target": 0}
    with CLARI_FORECAST_FILE.open(newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if canonical_quarter(r.get("YEAR_QUARTER")) == quarter]
    if name.casefold() == "all":
        def num(row, key):
            try: return float(row.get(key) or 0)
            except (TypeError, ValueError): return 0
        quota = sum(num(row, "QUARTER_QUOTA") for row in rows)
        bookings = sum(num(row, "SIGNED") for row in rows)
        return {"name": "All authorized AEs", "quarter": quarter, "quota": quota,
                "forecast": sum(num(row, "QUARTER_FORECAST") for row in rows),
                "bookings": bookings, "ai_target": quota * 0.45,
                "ai_bookings": sum(num(row, "AI_SIGNED") for row in rows),
                "nb_target": quota * 0.25,
                "nb_bookings": sum(num(row, "NB_SIGNED") for row in rows),
                "pipeline": sum(num(row, "PIPELINE") for row in rows),
                "pipeline_target": max(quota - bookings, 0) * 3}
    row = next((r for r in rows if (r.get("NAME") or "").strip().casefold() == name.casefold()), None)
    if not row:
        return {"name": name, "quarter": quarter, "quota": 0, "forecast": 0, "bookings": 0, "ai_target": 0, "ai_bookings": 0, "nb_target": 0, "nb_bookings": 0, "pipeline": 0, "pipeline_target": 0}
    def num(key):
        try: return float(row.get(key) or 0)
        except (TypeError, ValueError): return 0
    quota = num("QUARTER_QUOTA")
    bookings = num("SIGNED")
    # Targets are intentionally derived from the Clari quarter quota so they
    # stay consistent even when the source file does not carry target columns.
    return {"name": row.get("NAME", name), "quarter": quarter, "quota": quota, "forecast": num("QUARTER_FORECAST"), "bookings": bookings, "ai_target": quota * 0.45, "ai_bookings": num("AI_SIGNED"), "nb_target": quota * 0.25, "nb_bookings": num("NB_SIGNED"), "pipeline": num("PIPELINE"), "pipeline_target": max(quota - bookings, 0) * 3}


def get_team_forecast(q):
    quarter = q.get("quarter", "FY2027Q3")
    names = {value.strip().casefold() for value in (q.get("names") or "").split("|") if value.strip()}
    totals = {"quota": 0, "forecast": 0, "bookings": 0, "ai_target": 0, "ai_bookings": 0, "nb_target": 0, "nb_bookings": 0, "pipeline": 0, "pipeline_target": 0}
    if not names or not CLARI_FORECAST_FILE.exists():
        return {"name": "Team", "quarter": quarter, **totals}
    with CLARI_FORECAST_FILE.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if (row.get("NAME") or "").strip().casefold() not in names or canonical_quarter(row.get("YEAR_QUARTER")) != quarter:
                continue
            for output, source in (("quota", "QUARTER_QUOTA"), ("forecast", "QUARTER_FORECAST"), ("bookings", "SIGNED"), ("ai_target", "AI_QUARTER_QUOTA"), ("ai_bookings", "AI_SIGNED"), ("nb_target", "NB_QUARTER_QUOTA"), ("nb_bookings", "NB_SIGNED"), ("pipeline", "PIPELINE")):
                try: totals[output] += float(row.get(source) or 0)
                except (TypeError, ValueError): pass
    totals["ai_target"] = totals["quota"] * 0.45
    totals["nb_target"] = totals["quota"] * 0.25
    totals["pipeline_target"] = max(totals["quota"] - totals["bookings"], 0) * 3
    return {"name": "Team", "quarter": quarter, **totals}


def get_directory():
    """Return the active Workday directory used for admin access grants."""
    managed_svp_hierarchies = {
        "Adrian Fallow",
        "Andy Lawson",
        "Andrew Lawson",  # Workday's current spelling for Andy Lawson.
        "Eduardo Lugo",
        "Jamie O'Dyer",
        "Jamie O'Dwyer",  # Workday's current spelling.
        "Jim Priestley",
        "Mitch Young",
    }
    included_svp_names = {
        "Adrian Fallow",
        "Andrew Lawson",
        "Eduardo Lugo",
        "Jamie O'Dwyer",
        "Jim Priestley",
        "Mitch Young",
    }
    directory = []
    seen = set()
    for user in WORKDAY_USERS:
        employee_id = (user.get("EMPLOYEE_ID") or "").strip()
        name = (user.get("FULL_NAME") or "").strip()
        svp_name = (user.get("C_STAFF_1") or "").strip()
        if not employee_id or not name or employee_id in seen or (
            svp_name in managed_svp_hierarchies and name not in included_svp_names
        ):
            continue
        seen.add(employee_id)
        role = "SVP" if name in included_svp_names else workday_access_type(user)
        if role == "GTM":
            role = (user.get("BUSINESS_TITLE") or user.get("JOB_TITLE") or user.get("MANAGEMENT_LEVEL") or "GTM").strip()
        directory.append({
            "id": employee_id,
            "name": name,
            "email": (user.get("EMAIL") or "").strip().lower(),
            "source": role,
        })
    return directory


def get_pipeline(q):
    quarter = q.get("quarter")
    out = []
    seen_s1 = set()
    # The live Salesforce adapter can be limited to the current snapshot and
    # therefore have no rows for a future quarter. Select the source per
    # requested quarter so Next Quarter can still use the verified extract.
    live_has_quarter = bool(SFDC_ROWS) and (
        not quarter or any(canonical_quarter("", r.get("closedate")) == quarter for r in SFDC_ROWS)
    )
    source_rows = SFDC_ROWS if live_has_quarter else ROWS
    for r in source_rows:
        stage = (r["stage_name"] or "").strip()
        is_s1 = bool(re.search(r"(?:^|\D)0*1(?:\D|$)", stage))
        # Stage 1 is an early-signal list, not active pipeline: source rows
        # can carry a product-level ARR and a stage label instead of the
        # Total Booking/Open shape used by Stage 2–6 pipeline rows.
        if not (r["opportunity_is_commissionable"]
                and (r["product"] == "Total Booking" or is_s1)
                and (is_pipeline_stage(stage) or is_s1)
                and r["product_arr_usd"] > 0
                and (is_s1 or r["opportunity_status"] == "Open")):
            continue
        s = scope_filter(r, q)
        if s is False:
            continue
        if quarter:
            # My Deals quarter tabs are driven by the actual Salesforce
            # CloseDate. Imported fiscal-quarter labels can be stale, so do
            # not let them decide which tab receives an opportunity.
            if canonical_quarter("", r["closedate"]) != quarter:
                continue
        if is_s1:
            # Product-level extracts can repeat one Stage 1 opportunity.
            # Keep one record per opportunity so the S1 list is truthful.
            opportunity_key = r["crm_opportunity_id"] or r["opportunity_name"]
            if opportunity_key in seen_s1:
                continue
            seen_s1.add(opportunity_key)
        out.append({
            "crm_opportunity_id": r["crm_opportunity_id"],
            "opportunity_name": r["opportunity_name"],
            "crm_account_name": r["crm_account_name"],
            "opportunity_owner_name": r["opportunity_owner_name"],
            "opportunity_owner_id": r["ownerid"],
            "stage_name": r["stage_name"],
            "opportunity_type": r["opportunity_type"],
            "opportunity_status": r["opportunity_status"],
            "product_arr_usd": r["product_arr_usd"],
            "product_booking_arr_usd": r["product_booking_arr_usd"],
            "closedate": r["closedate"],
            "stage_2_plus_date_c": r["stage_2_plus_date_c"],
            "gtm_team": r["gtm_team"],
            "vp_deal_forecast__c": r["vp_deal_forecast__c"],
            "manager_forecast__c": r["manager_forecast__c"],
            "quote_status": r.get("quote_status"),
            "has_executive_relationships": r.get("has_executive_relationships"),
            "zendesk_executive_connect": r.get("zendesk_executive_connect"),
            "economic_buyer_status": r.get("economic_buyer_status"),
            "executive_sponsor_status": r.get("executive_sponsor_status"),
            "close_fiscal_quarter": canonical_quarter("", r["closedate"]),
            "d_score_latest__c": r["d_score_latest__c"],
        })
    out.sort(key=lambda x: x["product_arr_usd"], reverse=True)
    # Do not truncate the scoped result: Stage 1 opportunities are included
    # for the early-signal view and must remain visible for full/admin scope.
    return out


def get_metrics_summary(q):
    quarter = q.get("quarter", "FY2027Q3")
    # Use the live Salesforce snapshot when it contains the requested quarter;
    # otherwise use the verified Salesforce export for historical/future tabs.
    sfdc_source = SFDC_ROWS if (SFDC_ROWS and any(r["close_year_quarter"] == quarter for r in SFDC_ROWS)) else SFDC_EXPORT_ROWS
    pipe = {"open_pipeline_total": 0, "open_pipeline_nb": 0, "open_pipeline_exp": 0,
            "open_pipeline_ai": 0, "open_deal_count": set(), "open_pipeline_nb_deal_count": set(),
            "open_pipeline_ai_deal_count": set()}
    book = {"bookings_total": 0, "bookings_nb": 0, "bookings_exp": 0,
            "bookings_ai": 0, "bookings_deal_count": set(), "bookings_nb_deal_count": set(),
            "bookings_ai_deal_count": set()}
    for r in ROWS:
        if scope_filter(r, q) is False:
            continue
        if (not r["opportunity_is_commissionable"] or r["close_year_quarter"] != quarter
                or (r.get("date_label") or "today").strip().lower() != "today"
                or r["product_arr_usd"] <= 0):
            continue
        # pipeline (open)
        if r["opportunity_status"] == "Open" and is_pipeline_stage(r["stage_name"]):
            if r["product"] == "Total Booking":
                pipe["open_pipeline_total"] += r["product_arr_usd"]
                pipe["open_deal_count"].add(r["crm_opportunity_id"])
                if r["opportunity_type"] == "New Business":
                    pipe["open_pipeline_nb"] += r["product_arr_usd"]
                    pipe["open_pipeline_nb_deal_count"].add(r["crm_opportunity_id"])
                elif r["opportunity_type"] == "Expansion":
                    pipe["open_pipeline_exp"] += r["product_arr_usd"]
            if r["product"] in AI_PRODUCTS:
                pipe["open_pipeline_ai"] += r["product_arr_usd"]
                pipe["open_pipeline_ai_deal_count"].add(r["crm_opportunity_id"])
        # bookings (won)
        if r["stage_name"] in WON_STAGES:
            if r["product"] == "Total Booking":
                book["bookings_total"] += r["product_booking_arr_usd"]
                book["bookings_deal_count"].add(r["crm_opportunity_id"])
                if r["opportunity_type"] == "New Business" and r["product_booking_arr_usd"] > 0:
                    book["bookings_nb"] += r["product_booking_arr_usd"]
                    book["bookings_nb_deal_count"].add(r["crm_opportunity_id"])
                elif r["opportunity_type"] == "Expansion":
                    book["bookings_exp"] += r["product_booking_arr_usd"]
            if r["product"] in AI_PRODUCTS and r["product_booking_arr_usd"] > 0:
                book["bookings_ai"] += r["product_booking_arr_usd"]
                book["bookings_ai_deal_count"].add(r["crm_opportunity_id"])

    # Salesforce is the source of truth for the main Pipeline total and
    # Signed total. GTMI remains available for product-specific AI/NB
    # breakdowns. With no SFDC export yet, Salesforce-backed totals stay
    # empty rather than showing the wrong source.
    if sfdc_source:
        pipe["open_pipeline_total"] = 0
        pipe["open_pipeline_nb"] = 0
        pipe["open_pipeline_exp"] = 0
        pipe["open_deal_count"] = set()
        pipe["open_pipeline_nb_deal_count"] = set()
        for r in sfdc_source:
            if not is_pipeline_stage(r["stage_name"]) or r["close_year_quarter"] != quarter or scope_filter(r, q) is False:
                continue
            amount = r["product_arr_usd"]
            pipe["open_pipeline_total"] += amount
            pipe["open_deal_count"].add(r["crm_opportunity_id"])
            if r["opportunity_type"].strip().casefold() == "new business":
                pipe["open_pipeline_nb"] += amount
                pipe["open_pipeline_nb_deal_count"].add(r["crm_opportunity_id"])
            elif r["opportunity_type"].strip().casefold() == "expansion":
                pipe["open_pipeline_exp"] += amount
    else:
        pipe["open_pipeline_total"] = 0
        pipe["open_pipeline_exp"] = 0
        pipe["open_deal_count"] = set()

    # GTMI owns New Business Pipeline; calculate it independently of the
    # Salesforce total-pipeline source. New Business is restricted to the
    # Total Booking product so product-level rows cannot inflate the metric.
    pipe["open_pipeline_nb"] = 0
    pipe["open_pipeline_nb_deal_count"] = set()
    for r in ROWS:
        if (scope_filter(r, q) is False or r["close_year_quarter"] != quarter
                or (r.get("date_label") or "today").strip().lower() != "today"
                or not r["opportunity_is_commissionable"] or r["product"] != "Total Booking"
                or r["product"] != "Total Booking" or not is_pipeline_stage(r["stage_name"]) or r["product_arr_usd"] <= 0
                or r["opportunity_type"].strip().casefold() != "new business"):
            continue
        pipe["open_pipeline_nb"] += r["product_arr_usd"]
        pipe["open_pipeline_nb_deal_count"].add(r["crm_opportunity_id"])

    if sfdc_source:
        book = {"bookings_total": 0, "bookings_nb": 0, "bookings_exp": 0,
                "bookings_ai": 0, "bookings_deal_count": set(), "bookings_nb_deal_count": set(),
                "bookings_ai_deal_count": set()}
        for r in sfdc_source:
            if r["stage_name"] not in WON_STAGES or r["close_year_quarter"] != quarter or scope_filter(r, q) is False:
                continue
            amount = r["product_booking_arr_usd"]
            book["bookings_total"] += amount
            book["bookings_deal_count"].add(r["crm_opportunity_id"])
            if r["opportunity_type"].strip().casefold() == "new business":
                book["bookings_nb"] += amount
                book["bookings_nb_deal_count"].add(r["crm_opportunity_id"])
            elif r["opportunity_type"].strip().casefold() == "expansion":
                book["bookings_exp"] += amount
            if r["product"] in AI_PRODUCTS:
                book["bookings_ai"] += amount
                book["bookings_ai_deal_count"].add(r["crm_opportunity_id"])
    else:
        book = {"bookings_total": 0, "bookings_nb": 0, "bookings_exp": 0,
                "bookings_ai": 0, "bookings_deal_count": set(), "bookings_nb_deal_count": set(),
                "bookings_ai_deal_count": set()}

    # GTMI owns the product-qualified AI/NB metrics. Keep these separate from
    # the SFDC totals above so a Salesforce report cannot overwrite them.
    book["bookings_nb"] = 0
    book["bookings_nb_deal_count"] = set()
    book["bookings_ai"] = 0
    book["bookings_ai_deal_count"] = set()
    for r in ROWS:
        if (scope_filter(r, q) is False or r["close_year_quarter"] != quarter
                or (r.get("date_label") or "today").strip().lower() != "today"
                or not r["opportunity_is_commissionable"]):
            continue
        if r["product"] == "Total Booking" and r["opportunity_type"].strip().casefold() == "new business" and r["product_booking_arr_usd"] > 0 and r["stage_name"] in WON_STAGES:
            book["bookings_nb"] += r["product_booking_arr_usd"]
            book["bookings_nb_deal_count"].add(r["crm_opportunity_id"])
        if r["product"] in AI_PRODUCTS and r["product_booking_arr_usd"] > 0 and r["stage_name"] in WON_STAGES:
            book["bookings_ai"] += r["product_booking_arr_usd"]
            book["bookings_ai_deal_count"].add(r["crm_opportunity_id"])
    pipe["open_deal_count"] = len(pipe["open_deal_count"])
    pipe["open_pipeline_nb_deal_count"] = len(pipe["open_pipeline_nb_deal_count"])
    pipe["open_pipeline_ai_deal_count"] = len(pipe["open_pipeline_ai_deal_count"])
    book["bookings_deal_count"] = len(book["bookings_deal_count"])
    book["bookings_nb_deal_count"] = len(book["bookings_nb_deal_count"])
    book["bookings_ai_deal_count"] = len(book["bookings_ai_deal_count"])
    return {**{k: round(v, 2) if isinstance(v, float) else v for k, v in pipe.items()},
            **{k: round(v, 2) if isinstance(v, float) else v for k, v in book.items()},
            "data_as_of": source_data_as_of()}


def get_pipeline_by_product(q):
    quarter = q.get("quarter")
    agg = {}
    for r in ROWS:
        if scope_filter(r, q) is False:
            continue
        if not (r["opportunity_is_commissionable"] and r["product"] != "Total Booking" and is_pipeline_stage(r["stage_name"]) and r["product_arr_usd"] > 0
                and r["opportunity_status"] == "Open"):
            continue
        if quarter and r["close_year_quarter"] != quarter:
            continue
        a = agg.setdefault(r["product"], {"product": r["product"], "total_arr": 0.0, "opps": set()})
        a["total_arr"] += r["product_arr_usd"]
        a["opps"].add(r["crm_opportunity_id"])
    out = [{"product": v["product"], "total_arr": round(v["total_arr"], 2), "opp_count": len(v["opps"])}
           for v in agg.values()]
    out.sort(key=lambda x: x["total_arr"], reverse=True)
    return out


def get_gtmi_pipeline_summary(q):
    """Return the GTMI open-pipeline totals for a selected quarter.

    This is intentionally separate from the Salesforce-backed main pipeline
    summary. Next Quarter uses GTMI product ARR, while This Quarter keeps its
    existing Salesforce source of truth.
    """
    quarter = q.get("quarter")
    total = 0.0
    ai = 0.0
    nb = 0.0
    deals = set()
    ai_deals = set()
    nb_deals = set()
    for r in ROWS:
        if (scope_filter(r, q) is False or
                (quarter and r["close_year_quarter"] != quarter) or
                (r["date_label"] or "today").strip().lower() != "today" or
                not r["opportunity_is_commissionable"] or
                r["opportunity_status"] != "Open" or
                not is_pipeline_stage(r["stage_name"]) or
                r["product_arr_usd"] <= 0):
            continue
        amount = r["product_arr_usd"]
        opp_id = r["crm_opportunity_id"]
        total += amount
        deals.add(opp_id)
        if r["product"] in AI_PRODUCTS:
            ai += amount
            ai_deals.add(opp_id)
        if r["opportunity_type"] == "New Business":
            nb += amount
            nb_deals.add(opp_id)
    return {
        "total": round(total, 2), "ai": round(ai, 2), "nb": round(nb, 2),
        "deal_count": len(deals), "ai_deal_count": len(ai_deals),
        "nb_deal_count": len(nb_deals), "quarter": quarter,
    }


def get_stage_distribution(q):
    owner_id = q.get("owner_id")
    quarter = q.get("quarter", "FY2027Q3")
    agg = {}
    for r in ROWS:
        if not (r["product"] == "Total Booking" and r["product_arr_usd"] > 0
                and r["opportunity_status"] == "Open"
                and r["ownerid"] == owner_id and r["close_year_quarter"] == quarter):
            continue
        a = agg.setdefault(r["stage_name"], {"stage_name": r["stage_name"], "deal_count": set(), "total_arr": 0.0})
        a["deal_count"].add(r["crm_opportunity_id"])
        a["total_arr"] += r["product_arr_usd"]
    out = [{"stage_name": v["stage_name"], "deal_count": len(v["deal_count"]),
            "total_arr": round(v["total_arr"], 2)} for v in agg.values()]
    out.sort(key=lambda x: x["stage_name"])
    return out


def get_historical(q):
    agg = {}
    for r in ROWS:
        if scope_filter(r, q) is False:
            continue
        if r["stage_name"] not in WON_STAGES:
            continue
        if r["close_year_quarter"] not in QUARTERS:
            continue
        a = agg.setdefault(r["close_year_quarter"], {
            "quarter": r["close_year_quarter"], "bookings_total": 0.0, "bookings_nb": 0.0,
            "bookings_exp": 0.0, "bookings_ai": 0.0, "deal_count": set()})
        if r["product"] == "Total Booking":
            a["bookings_total"] += r["product_booking_arr_usd"]
            a["deal_count"].add(r["crm_opportunity_id"])
            if r["opportunity_type"] == "New Business":
                a["bookings_nb"] += r["product_booking_arr_usd"]
            elif r["opportunity_type"] == "Expansion":
                a["bookings_exp"] += r["product_booking_arr_usd"]
        if r["product"] in AI_PRODUCTS and r["product_booking_arr_usd"] > 0:
            a["bookings_ai"] += r["product_booking_arr_usd"]
    out = []
    for qk in QUARTERS:
        if qk in agg:
            v = agg[qk]
            out.append({"quarter": v["quarter"], "bookings_total": round(v["bookings_total"], 2),
                        "bookings_nb": round(v["bookings_nb"], 2), "bookings_exp": round(v["bookings_exp"], 2),
                        "bookings_ai": round(v["bookings_ai"], 2), "deal_count": len(v["deal_count"])})
    return out


def get_bookings(q):
    quarter = q.get("quarter", "FY2027Q3")
    out = []
    source_rows = SFDC_ROWS
    for r in source_rows:
        if not (r["stage_name"] in WON_STAGES
                and r["product_booking_arr_usd"] > 0
                and r["opportunity_is_commissionable"]
                and r["close_year_quarter"] == quarter):
            continue
        if scope_filter(r, q) is False:
            continue
        out.append({
            "crm_opportunity_id": r["crm_opportunity_id"], "opportunity_name": r["opportunity_name"],
            "crm_account_name": r["crm_account_name"], "opportunity_owner_name": r["opportunity_owner_name"],
            "opportunity_owner_id": r["ownerid"], "stage_name": r["stage_name"],
            "opportunity_type": r["opportunity_type"], "product_booking_arr_usd": r["product_booking_arr_usd"],
            "closedate": r["closedate"], "gtm_team": r["gtm_team"], "product": r["product"],
        })
    out.sort(key=lambda x: x["product_booking_arr_usd"], reverse=True)
    return out


def get_linearity(q):
    if not has_scope(q):
        return []
    quarter = q.get("quarter", "FY2027Q3")
    agg = {}
    for r in ROWS:
        if scope_filter(r, q) is False:
            continue
        if not (r["product"] == "Total Booking"
                and r["stage_name"] in WON_STAGES
                and r["close_year_quarter"] == quarter):
            continue
        month = r["closedate"][:7]
        a = agg.setdefault(month, {"close_month": month, "deals": set(), "bookings": 0.0})
        a["deals"].add(r["crm_opportunity_id"])
        a["bookings"] += r["product_booking_arr_usd"]
    out = [{"close_month": v["close_month"], "deals": len(v["deals"]), "bookings": round(v["bookings"], 2)}
           for v in agg.values()]
    out.sort(key=lambda x: x["close_month"])
    return out


def get_pipe_creation(q):
    if not has_scope(q):
        return []
    quarter = q.get("quarter", "FY2027Q3")
    cadence = q.get("cadence", "month")
    date_range = FQ_MAP.get(quarter)
    if not date_range:
        return []
    lo, hi = date_range
    agg = {}
    for r in ROWS:
        if scope_filter(r, q) is False:
            continue
        if not (r["product"] == "Total Booking" and r["product_arr_usd"] > 0):
            continue
        s2 = r["stage_2_plus_date_c"]
        if not (lo <= s2 <= hi):
            continue
        if cadence == "week":
            try:
                created = datetime.date.fromisoformat(s2[:10])
                period = (created - datetime.timedelta(days=created.weekday())).isoformat()
            except ValueError:
                period = s2[:10]
        else:
            period = s2[:7]
        a = agg.setdefault(period, {"created_period": period, "opps": set(), "arr": 0.0})
        a["opps"].add(r["crm_opportunity_id"])
        a["arr"] += r["product_arr_usd"]
    out = [{"created_period": v["created_period"], "opps": len(v["opps"]), "arr": round(v["arr"], 2)}
           for v in agg.values()]
    out.sort(key=lambda x: x["created_period"])
    return out


def get_team_quota(q):
    quarter = q.get("quarter", "FY2027Q3")
    # owner ids in scope
    owners = set()
    for r in ROWS:
        if r["product"] != "Total Booking":
            continue
        if scope_filter(r, q) is False:
            continue
        owners.add(r["ownerid"])
    total = 0.0
    qmap = STATE["quotas"]
    for oid in owners:
        total += qmap.get(f"{oid}|{quarter}", 0)
    return {"quota": total}


# ─── HTTP HANDLER ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Password")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def _multipart_upload(self):
        """Read a multipart upload and return its file plus the selected dataset."""
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")})
        file_field = form["file"] if "file" in form else None
        # FieldStorage does not support truth-value testing; `if not
        # file_field` raises "Cannot be converted to bool" before we can
        # process an otherwise valid upload.
        if file_field is None or not getattr(file_field, "filename", None):
            raise ValueError("Choose a file before uploading.")
        filename = Path(file_field.filename).name
        content = file_field.file.read()
        dataset = form.getfirst("dataset", "Pipeline & bookings")
        return filename, content, dataset
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self._send({}, 200)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}

        if path == "/api/health":
            return self._send({"status": "ok"})
        if path == "/api/auth/me":
            return self._send(auth_identity(self))
        if path == "/api/profile":
            email = (q.get("email") or "").strip().lower()
            for user in WORKDAY_USERS:
                if (user.get("EMAIL") or "").strip().lower() != email:
                    continue
                role = workday_access_type(user)
                is_admin = email == "justine.mendez@zendesk.com"
                return self._send({
                    "authenticated": True,
                    "email": email,
                    "name": (user.get("FULL_NAME") or "").strip(),
                    "subject_id": str(user.get("EMPLOYEE_ID") or ""),
                    "role": "Admin" if is_admin else role,
                    "access_level": "full" if is_admin else ("hierarchy" if role != "AE" else "own profile"),
                    "scope_value": "all" if is_admin else (user.get("FULL_NAME") or "").strip(),
                    "source": "local-development-fallback",
                })
            return self._send({"authenticated": False, "email": email, "name": None}, 404)
        if path == "/api/admin/uploads":
            return self._send(STATE.get("uploads", []))
        if path == "/api/roster":
            return self._send(get_roster())
        if path == "/api/directory":
            return self._send(get_directory())
        if path == "/api/pipeline":
            return self._send(get_pipeline(q))
        if path == "/api/bookings":
            return self._send(get_bookings(q))
        if path == "/api/pipeline_by_product":
            if not has_scope(q):
                return self._send({"error": "scope required"}, 400)
            return self._send(get_pipeline_by_product(q))
        if path == "/api/gtmi_pipeline_summary":
            if not has_scope(q):
                return self._send({"error": "scope required"}, 400)
            return self._send(get_gtmi_pipeline_summary(q))
        if path == "/api/metrics/summary":
            if not has_scope(q):
                return self._send({"error": "scope required"}, 400)
            return self._send(get_metrics_summary(q))
        if path == "/api/stage_distribution":
            if not q.get("owner_id"):
                return self._send({"error": "owner_id required"}, 400)
            return self._send(get_stage_distribution(q))
        if path == "/api/historical":
            if not has_scope(q):
                return self._send({"error": "scope required"}, 400)
            return self._send(get_historical(q))
        if path == "/api/linearity":
            return self._send(get_linearity(q))
        if path == "/api/pipe_creation":
            return self._send(get_pipe_creation(q))
        if path == "/api/quota/team":
            return self._send(get_team_quota(q))
        if path == "/api/forecast":
            return self._send(get_forecast(q))
        if path == "/api/forecast/team":
            return self._send(get_team_forecast(q))
        if path == "/api/gong":
            raw_ids = q.get("opportunity_ids", "")
            ids = [value for value in raw_ids.split("|") if value]
            return self._send(fetch_gong_signals(ids))

        m = re.match(r"^/api/quota/([^/]+)$", path)
        if m:
            quarter = q.get("quarter", "FY2027Q3")
            key = f"{m.group(1)}|{quarter}"
            return self._send({"quota": STATE["quotas"].get(key, 0)})

        m = re.match(r"^/api/notes/([^/]+)$", path)
        if m:
            return self._send(STATE["notes"].get(m.group(1), []))

        m = re.match(r"^/api/actions/([^/]+)$", path)
        if m:
            return self._send(STATE["actions"].get(m.group(1), []))

        m = re.match(r"^/api/competencies/([^/]+)$", path)
        if m:
            return self._send(STATE["competencies"].get(m.group(1), [3, 3, 3, 3, 3]))

        m = re.match(r"^/api/weekly-tracker/([^/]+)$", path)
        if m:
            return self._send(STATE["weekly"].get(m.group(1)))

        m = re.match(r"^/api/deal-maps/([^/]+)$", path)
        if m:
            return self._send(STATE["dealmaps"].get(m.group(1), []))

        return self._send({"error": "not found", "path": path}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        data = self._body()

        if path == "/api/admin/verify":
            return self._send({"valid": True})
        if path == "/api/admin/upload":
            try:
                filename, content, dataset = self._multipart_upload()
                if not filename.lower().endswith((".csv", ".tsv")):
                    return self._send({"error": "Please upload a CSV or TSV file."}, 400)
                UPLOAD_DIR.mkdir(exist_ok=True)
                stored_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{re.sub(r'[^A-Za-z0-9._-]', '_', filename)}"
                (UPLOAD_DIR / stored_name).write_bytes(content)
                text = content.decode("utf-8-sig", errors="replace")
                lines = [line for line in text.splitlines() if line.strip()]
                headers = [item.strip() for item in (lines[0].split('\t' if filename.lower().endswith('.tsv') else ',') if lines else [])]
                entry = {"id": stored_name, "filename": filename, "stored_name": stored_name, "dataset": dataset, "row_count": max(len(lines) - 1, 0), "headers": headers, "size_bytes": len(content), "uploaded_at": datetime.datetime.now().isoformat()}
                # An SFDC Opportunity export becomes the signed source as
                # soon as it is uploaded; GTMI uploads continue to feed open
                # pipeline only. Detection is based on the actual fields,
                # never on a user-selected label.
                global SFDC_ROWS, ROWS
                parsed_sfdc = load_sfdc_signed_export(content=content, filename=filename)
                header_keys = {h.strip().lower() for h in headers}
                if {"booking_arr__c", "booking_arr_c"} & header_keys:
                    SFDC_ROWS = parsed_sfdc or []
                STATE["uploads"].insert(0, entry)
                save_state()
                return self._send({"status": "uploaded", "rows": entry["row_count"], "filename": filename, "dataset": dataset})
            except Exception as exc:
                return self._send({"error": str(exc) or "Upload failed."}, 400)

        if path == "/api/ask":
            question = str(data.get("question") or "").strip()
            viewer = str(data.get("owner_name") or "").strip()
            quarter = str(data.get("quarter") or "FY2027Q3").strip()
            if not question:
                return self._send({"answer": "Ask me about a deal, pipeline, AI, New Business, or what to do next.", "evidence": [], "source": "AE Compass data"})
            rows = get_pipeline({"owner_name": viewer, "quarter": quarter}) if viewer else []
            if not rows:
                return self._send({"answer": "I could not find current-quarter opportunities matched to this profile yet.", "evidence": [], "source": "Workday + GTMI/Salesforce"})
            try:
                return self._send(answer_question(question, viewer, quarter, rows, data.get("history", [])))
            except AssistantUnavailable as exc:
                return self._send({"error": "assistant_unavailable", "message": str(exc)}, 503)
            except Exception:
                return self._send({"error": "assistant_unavailable", "message": "Ask Compass could not complete a response. Please try again."}, 503)

        m = re.match(r"^/api/notes/([^/]+)$", path)
        if m:
            ae = m.group(1)
            note = {"id": data.get("id"), "ae_user_id": ae, "category": data.get("category"),
                    "content": data.get("content"), "timestamp": datetime.datetime.now().isoformat()}
            STATE["notes"].setdefault(ae, []).insert(0, note)
            save_state()
            return self._send({"status": "created", "id": note["id"]}, 201)

        m = re.match(r"^/api/actions/([^/]+)$", path)
        if m:
            ae = m.group(1)
            item = {"id": data.get("id"), "ae_user_id": ae, "title": data.get("title"),
                    "status": data.get("status", "Not Started"), "quarter": data.get("quarter"),
                    "category": data.get("category", "General")}
            STATE["actions"].setdefault(ae, []).append(item)
            save_state()
            return self._send({"status": "created", "id": item["id"]}, 201)

        return self._send({"error": "not found"}, 404)

    def do_PUT(self):
        u = urlparse(self.path)
        path = u.path
        data = self._body()

        m = re.match(r"^/api/quota/([^/]+)$", path)
        if m:
            quarter = data.get("quarter", "FY2027Q3")
            STATE["quotas"][f"{m.group(1)}|{quarter}"] = float(data.get("quota", 0))
            save_state()
            return self._send({"status": "ok"})

        m = re.match(r"^/api/competencies/([^/]+)$", path)
        if m:
            STATE["competencies"][m.group(1)] = data.get("scores", [3, 3, 3, 3, 3])
            save_state()
            return self._send({"status": "ok"})

        m = re.match(r"^/api/weekly-tracker/([^/]+)$", path)
        if m:
            STATE["weekly"][m.group(1)] = data.get("rows")
            save_state()
            return self._send({"status": "ok"})

        m = re.match(r"^/api/deal-maps/([^/]+)$", path)
        if m:
            STATE["dealmaps"][m.group(1)] = data.get("plans", [])
            save_state()
            return self._send({"status": "ok"})

        return self._send({"error": "not found"}, 404)

    def do_PATCH(self):
        u = urlparse(self.path)
        data = self._body()
        m = re.match(r"^/api/actions/([^/]+)/([^/]+)$", u.path)
        if m:
            ae, item_id = m.group(1), m.group(2)
            for it in STATE["actions"].get(ae, []):
                if it["id"] == item_id:
                    it["status"] = data.get("status", it["status"])
            save_state()
            return self._send({"status": "updated"})
        return self._send({"error": "not found"}, 404)


def main():
    port = int(os.environ.get("PORT", "8080"))
    print(f"AE Compass local data server → http://localhost:{port}")
    print(f"  {len(ROSTER)} Workday AEs loaded, {len(ROWS)} pipeline rows")
    print(f"  User edits persist to {STATE_FILE.name}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
