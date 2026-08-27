"""
SalesPilot Data Server — serves AE performance data from CSV uploads stored in PostgreSQL.
Admin screen (password-protected) allows uploading pipeline/bookings CSV data.
User-generated content (coaching notes, action items, etc.) persisted in PostgreSQL.

Runs on PORT env var (default 8080 for Cloud Run).
"""

import os
import sys
import csv
import io
import json
import uuid
import datetime
import decimal
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from quarter_utils import canonical_quarter

load_dotenv(Path(__file__).parent / ".env")

AI_PRODUCTS = ('AI_Expert', 'Copilot', 'Ultimate', 'Ultimate_AR', 'Zendesk_AR', 'QA', 'WEM', 'Forethought_AI_Agents')

WORKDAY_HIERARCHY_FILE = Path(os.environ.get(
    "WORKDAY_HIERARCHY_FILE",
    "/Users/justine.mendez/Library/CloudStorage/GoogleDrive-justine.mendez@zendesk.com/Shared drives/GTM Ops/APAC/AE Compass/workday_hierarchy_chris_donato.csv",
))
CLARI_FORECAST_FILE = Path(os.environ.get("CLARI_FORECAST_FILE", str(WORKDAY_HIERARCHY_FILE.parent / "clari_forecast_current_quarter.csv")))


def load_workday_users():
    if not WORKDAY_HIERARCHY_FILE.exists():
        return []
    with WORKDAY_HIERARCHY_FILE.open(newline="", encoding="utf-8-sig") as handle:
        users = list(csv.DictReader(handle))
    return [
        user for user in users
        if (user.get("C_STAFF") or "").strip() == "Chris Donato"
        and (user.get("WORKER_STATUS") or "1").strip().lower() in {"1", "true", "active"}
        and (user.get("_FIVETRAN_DELETED") or "false").strip().lower() in {"false", "0", "no", ""}
    ]


WORKDAY_USERS = load_workday_users()


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
    return "GTM"


MANAGED_SVP_HIERARCHIES = {
    "Adrian Fallow", "Andy Lawson", "Andrew Lawson", "Eduardo Lugo",
    "Jamie O'Dyer", "Jamie O'Dwyer", "Jim Priestley", "Mitch Young",
}
INCLUDED_SVP_NAMES = {
    "Adrian Fallow", "Andrew Lawson", "Eduardo Lugo", "Jamie O'Dwyer",
    "Jim Priestley", "Mitch Young",
}


def is_admin_search_user(user):
    name = (user.get("FULL_NAME") or "").strip()
    svp = (user.get("C_STAFF_1") or "").strip()
    return svp not in MANAGED_SVP_HIERARCHIES or name in INCLUDED_SVP_NAMES


def current_workday_identity():
    email = (request.headers.get("X-Forwarded-Email") or "").strip().lower()
    if not email:
        return {"authenticated": False, "email": None, "name": None, "subject_id": None, "role": None, "access_level": None, "source": "appfoundry"}
    for user in WORKDAY_USERS:
        if (user.get("EMAIL") or "").strip().lower() != email:
            continue
        role = workday_access_type(user)
        is_admin = email == "justine.mendez@zendesk.com"
        return {
            "authenticated": True,
            "email": email,
            "name": (user.get("FULL_NAME") or "").strip(),
            "subject_id": (user.get("EMPLOYEE_ID") or "").strip(),
            "role": "Admin" if is_admin else role,
            "access_level": "full" if is_admin else ("hierarchy" if role != "AE" else "own profile"),
            "scope_value": "all" if is_admin else (user.get("FULL_NAME") or "").strip(),
            "source": "appfoundry",
        }
    return {"authenticated": False, "email": email, "name": None, "subject_id": None, "role": None, "access_level": None, "source": "appfoundry"}


class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


app = Flask(__name__)
app.json_provider_class = CustomJSONProvider
app.json = CustomJSONProvider(app)
CORS(app)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'dist', 'renderer')


# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "salespilot"),
        user=os.environ.get("DB_USER", "salespilot"),
        password=os.environ.get("DB_PASS", ""),
    )
    conn.autocommit = False
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_data (
        id SERIAL PRIMARY KEY,
        upload_id UUID NOT NULL,
        uploaded_at TIMESTAMPTZ DEFAULT NOW(),
        ownerid TEXT,
        opportunity_owner_name TEXT,
        crm_opportunity_id TEXT,
        opportunity_name TEXT,
        crm_account_name TEXT,
        stage_name TEXT,
        opportunity_type TEXT,
        opportunity_status TEXT,
        product TEXT,
        product_arr_usd NUMERIC,
        product_booking_arr_usd NUMERIC,
        closedate TEXT,
        stage_2_plus_date_c TEXT,
        gtm_team TEXT,
        vp_deal_forecast__c TEXT,
        manager_forecast__c TEXT,
        close_year_quarter TEXT,
        d_score_latest__c TEXT,
        date_label TEXT,
        opportunity_is_commissionable BOOLEAN DEFAULT TRUE,
        current_vp_team TEXT,
        current_dir_team TEXT,
        current_mgr_team TEXT,
        pro_forma_market_segment TEXT,
        manager_name TEXT,
        director_name TEXT,
        rvp_name TEXT,
        svp_name TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_pipeline_upload ON pipeline_data(upload_id);
    CREATE INDEX IF NOT EXISTS idx_pipeline_owner ON pipeline_data(ownerid);
    CREATE INDEX IF NOT EXISTS idx_pipeline_product ON pipeline_data(product);
    CREATE INDEX IF NOT EXISTS idx_pipeline_status ON pipeline_data(opportunity_status);
    CREATE INDEX IF NOT EXISTS idx_pipeline_quarter ON pipeline_data(close_year_quarter);

    CREATE TABLE IF NOT EXISTS data_uploads (
        id UUID PRIMARY KEY,
        filename TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        uploaded_at TIMESTAMPTZ DEFAULT NOW(),
        is_active BOOLEAN DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS coaching_notes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ae_user_id TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_notes_ae ON coaching_notes(ae_user_id);

    CREATE TABLE IF NOT EXISTS action_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ae_user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'Not Started',
        quarter TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_actions_ae ON action_items(ae_user_id);

    CREATE TABLE IF NOT EXISTS competency_scores (
        id SERIAL PRIMARY KEY,
        ae_user_id TEXT NOT NULL UNIQUE,
        scores JSONB NOT NULL DEFAULT '[3,3,3,3,3]',
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS weekly_tracker (
        id SERIAL PRIMARY KEY,
        ae_user_id TEXT NOT NULL UNIQUE,
        rows JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS deal_maps (
        id SERIAL PRIMARY KEY,
        ae_user_id TEXT NOT NULL UNIQUE,
        plans JSONB NOT NULL DEFAULT '[]',
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS quotas (
        ae_user_id TEXT NOT NULL,
        quarter TEXT NOT NULL,
        quota_amount NUMERIC NOT NULL DEFAULT 0,
        source TEXT DEFAULT 'manual',
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (ae_user_id, quarter)
    );
    """)
    conn.commit()
    conn.close()


# ─── AUTH ────────────────────────────────────────────────────────────────────

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# Clari-aligned Sales SVP hierarchy
VALID_SVPS = {'Adrian Fallow', 'Jim Priestley', 'Mitch Young', 'Eduardo Lugo'}
EMEA_SVPS = {'Michaël Chaouat', 'Tanja Hilpert', 'Thor Newman Andersen'}
EMEA_SVP_LABEL = 'TBH - EMEA - SVP'


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("X-Admin-Password", "")
        if not ADMIN_PASSWORD or auth != ADMIN_PASSWORD:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ─── FRONTEND SERVING ────────────────────────────────────────────────────────

@app.route('/')
@app.route('/<path:path>')
def serve_frontend(path='index.html'):
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(file_path):
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, 'index.html')


# ─── HEALTH ──────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ─── ADMIN: CSV UPLOAD ───────────────────────────────────────────────────────

@app.route("/api/admin/upload", methods=["POST"])
@require_admin
def upload_csv():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.endswith(".csv"):
        return jsonify({"error": "File must be a .csv"}), 400

    upload_id = uuid.uuid4()
    content = file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    conn = get_db()
    cur = conn.cursor()

    # Deactivate previous uploads
    cur.execute("UPDATE data_uploads SET is_active = FALSE")
    cur.execute("DELETE FROM pipeline_data")

    row_count = 0
    for row in reader:
        # Normalize column names to lowercase
        row = {k.lower().strip(): v for k, v in row.items()}

        # SFDC Opportunity exports use Non-Commissionable (False means include)
        # and Booking_ARR__c. GTMSI exports keep their normalized equivalents.
        is_sfdc_opportunity = "booking_arr__c" in row or "booking_arr_c" in row
        non_commissionable = (
            row.get("non_commissionable__c")
            or row.get("non_commissionable_c")
            or row.get("non-commissionable__c")
            or row.get("non-commissionable")
            or row.get("non_commissionable")
        )
        if is_sfdc_opportunity:
            non_commissionable_value = str(non_commissionable).strip().lower() in ("true", "1", "yes", "t") if non_commissionable is not None else None
            if non_commissionable_value is not False:
                continue

        is_commissionable = row.get("opportunity_is_commissionable", "true")
        if isinstance(is_commissionable, str):
            is_commissionable = is_commissionable.lower() in ("true", "1", "yes", "t")

        closedate = row.get("closedate") or row.get("closed_date") or row.get("close_date") or row.get("closed date") or ""
        close_year_quarter = canonical_quarter(
            row.get("close_year_quarter") or row.get("close_year_quarter_c") or row.get("close_year_quarter__c"),
            closedate,
        )
        product_arr = row.get("product_arr_usd", "0") or "0"
        # Salesforce Opportunity exports expose signed value as Booking_ARR__c;
        # GTMSI exports use product_booking_arr_usd. Prefer the Salesforce field
        # when present, while retaining the GTMSI alias for existing uploads.
        booking_arr = (
            row.get("booking_arr__c")
            or row.get("booking_arr_c")
            or row.get("product_booking_arr_usd", "0")
            or "0"
        )
        try:
            product_arr = float(str(product_arr).replace(",", ""))
        except (ValueError, TypeError):
            product_arr = 0
        try:
            booking_arr = float(str(booking_arr).replace(",", ""))
        except (ValueError, TypeError):
            booking_arr = 0

        if is_sfdc_opportunity and booking_arr <= 0:
            continue

        cur.execute("""
            INSERT INTO pipeline_data (
                upload_id, ownerid, opportunity_owner_name, crm_opportunity_id,
                opportunity_name, crm_account_name, stage_name, opportunity_type,
                opportunity_status, product, product_arr_usd, product_booking_arr_usd,
                closedate, stage_2_plus_date_c, gtm_team, vp_deal_forecast__c,
                manager_forecast__c, close_year_quarter, d_score_latest__c,
                date_label, opportunity_is_commissionable,
                current_vp_team, current_dir_team, current_mgr_team,
                pro_forma_market_segment, manager_name, director_name, rvp_name, svp_name
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            str(upload_id),
            row.get("ownerid", ""),
            row.get("opportunity_owner_name", ""),
            row.get("crm_opportunity_id", ""),
            row.get("opportunity_name", ""),
            row.get("crm_account_name", ""),
            row.get("stage_name", ""),
            row.get("opportunity_type", ""),
            row.get("opportunity_status", ""),
            row.get("product", ""),
            product_arr,
            booking_arr,
            closedate,
            row.get("stage_2_plus_date_c", ""),
            row.get("gtm_team", ""),
            row.get("vp_deal_forecast__c", ""),
            row.get("manager_forecast__c", ""),
            close_year_quarter,
            row.get("d_score_latest__c", ""),
            row.get("date_label", "today"),
            is_commissionable,
            row.get("current_vp_team", ""),
            row.get("current_dir_team", ""),
            row.get("current_mgr_team", ""),
            row.get("pro_forma_market_segment", ""),
            row.get("manager_name", ""),
            row.get("director_name", ""),
            row.get("rvp_name", ""),
            row.get("svp_name", ""),
        ))
        row_count += 1

    cur.execute(
        "INSERT INTO data_uploads (id, filename, row_count) VALUES (%s, %s, %s)",
        (str(upload_id), file.filename, row_count)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "upload_id": str(upload_id), "rows": row_count})


@app.route("/api/admin/uploads", methods=["GET"])
@require_admin
def list_uploads():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM data_uploads ORDER BY uploaded_at DESC LIMIT 20")
    uploads = cur.fetchall()
    conn.close()
    return jsonify(uploads)


@app.route("/api/admin/verify", methods=["POST"])
def verify_admin():
    auth = request.json.get("password", "") if request.is_json else ""
    if not ADMIN_PASSWORD or auth != ADMIN_PASSWORD:
        return jsonify({"valid": False}), 401
    return jsonify({"valid": True})


# ─── DATA ENDPOINTS ──────────────────────────────────────────────────────────

@app.route("/api/roster")
def get_roster():
    if WORKDAY_USERS:
        results = []
        for user in WORKDAY_USERS:
            title = (user.get("JOB_TITLE") or user.get("BUSINESS_TITLE") or "").strip()
            if not ("account executive" in title.lower() or "sales representative" in title.lower()):
                continue
            results.append({
                "user_id": (user.get("EMPLOYEE_ID") or "").strip(),
                "ae_name": (user.get("FULL_NAME") or "").strip(),
                "email": (user.get("EMAIL") or "").strip().lower(),
                "vp_team_c": (user.get("C_STAFF_2") or "").strip(),
                "dir_team_c": (user.get("C_STAFF_3") or "").strip(),
                "mgr_team_c": (user.get("C_STAFF_4") or "").strip(),
                "market_segment_c": (user.get("REGION") or "").strip(),
                "manager_name": (user.get("C_STAFF_4") or "").strip() or None,
                "director_name": (user.get("C_STAFF_3") or "").strip() or None,
                "rvp_name": (user.get("C_STAFF_2") or "").strip() or None,
                "svp_name": (user.get("C_STAFF_1") or "").strip() or None,
            })
        return jsonify(results)
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT DISTINCT ON (ownerid)
            ownerid AS user_id,
            opportunity_owner_name AS ae_name,
            current_vp_team AS vp_team_c,
            current_dir_team AS dir_team_c,
            current_mgr_team AS mgr_team_c,
            pro_forma_market_segment AS market_segment_c,
            manager_name,
            director_name,
            rvp_name,
            svp_name
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product = 'Total Booking'
            AND product_arr_usd > 0
            AND current_vp_team IS NOT NULL
            AND current_vp_team != ''
            AND opportunity_owner_name IS NOT NULL
            AND opportunity_owner_name != ''
        ORDER BY ownerid, opportunity_owner_name
    """)
    results = cur.fetchall()
    conn.close()

    filtered = []
    for row in results:
        svp = row.get("svp_name", "")
        if svp not in VALID_SVPS and svp not in EMEA_SVPS:
            continue
        if svp in EMEA_SVPS:
            row["svp_name"] = EMEA_SVP_LABEL

        # Clari hierarchy: filter out TBH placeholders
        if row.get("rvp_name") in ("TBH", "", None):
            continue
        if row.get("director_name") in ("TBH", "", None):
            row["director_name"] = None
        if row.get("manager_name") in ("TBH", "", None):
            row["manager_name"] = None

        filtered.append(row)

    return jsonify(filtered)


@app.route("/api/pipeline")
def get_pipeline():
    owner_id = request.args.get("owner_id")
    owner_name = request.args.get("owner_name")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")
    vp_team = request.args.get("vp_team")
    quarter = request.args.get("quarter")

    sql = """
        SELECT
            crm_opportunity_id,
            opportunity_name,
            crm_account_name,
            opportunity_owner_name,
            ownerid AS opportunity_owner_id,
            stage_name,
            opportunity_type,
            opportunity_status,
            product_arr_usd,
            product_booking_arr_usd,
            closedate,
            stage_2_plus_date_c,
            gtm_team,
            vp_deal_forecast__c,
            manager_forecast__c,
            close_year_quarter AS close_fiscal_quarter,
            d_score_latest__c
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product = 'Total Booking'
            AND product_arr_usd > 0
            AND opportunity_status = 'Open'
            AND stage_name ~ '^(02|03|04|05|06)'
    """
    params = []

    if owner_name:
        sql += " AND LOWER(TRIM(opportunity_owner_name)) = LOWER(TRIM(%s))"
        params.append(owner_name)
    elif owner_id:
        sql += " AND ownerid = %s"
        params.append(owner_id)
    elif mgr_team:
        sql += " AND current_mgr_team = %s"
        params.append(mgr_team)
    elif dir_team:
        sql += " AND current_dir_team = %s"
        params.append(dir_team)
    elif vp_team:
        sql += " AND current_vp_team = %s"
        params.append(vp_team)

    if quarter:
        sql += " AND close_year_quarter = %s"
        params.append(quarter)

    sql += " ORDER BY product_arr_usd DESC LIMIT 200"

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()
    return jsonify(results)


@app.route("/api/directory")
def get_directory():
    return jsonify([
        {
            "id": (user.get("EMPLOYEE_ID") or "").strip(),
            "name": (user.get("FULL_NAME") or "").strip(),
            "email": (user.get("EMAIL") or "").strip().lower(),
            "source": "SVP" if (user.get("FULL_NAME") or "").strip() in INCLUDED_SVP_NAMES else workday_access_type(user),
        }
        for user in WORKDAY_USERS
        if is_admin_search_user(user)
        if (user.get("EMPLOYEE_ID") or "").strip() and (user.get("FULL_NAME") or "").strip()
    ])


@app.route("/api/auth/me")
def auth_me():
    return jsonify(current_workday_identity())


@app.route("/api/bookings")
def get_bookings():
    owner_id = request.args.get("owner_id")
    owner_name = request.args.get("owner_name")
    quarter = request.args.get("quarter", "FY2027Q3")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")

    sql = """
        SELECT
            crm_opportunity_id,
            opportunity_name,
            crm_account_name,
            opportunity_owner_name,
            ownerid AS opportunity_owner_id,
            stage_name,
            opportunity_type,
            product_booking_arr_usd,
            closedate,
            gtm_team,
            product
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product IN ('Total Booking','AI_Expert','Copilot','Ultimate','Ultimate_AR','Zendesk_AR','QA','WEM','Forethought_AI_Agents')
            AND stage_name IN ('07 - Signed', '08 - Closed')
            AND product_booking_arr_usd > 0
            AND close_year_quarter = %s
    """
    params = [quarter]

    if owner_name:
        sql += " AND LOWER(TRIM(opportunity_owner_name)) = LOWER(TRIM(%s))"
        params.append(owner_name)
    elif owner_id:
        sql += " AND ownerid = %s"
        params.append(owner_id)
    elif mgr_team:
        sql += " AND current_mgr_team = %s"
        params.append(mgr_team)
    elif dir_team:
        sql += " AND current_dir_team = %s"
        params.append(dir_team)

    sql += " ORDER BY product_booking_arr_usd DESC"

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()
    return jsonify(results)


@app.route("/api/pipeline_by_product")
def get_pipeline_by_product():
    owner_id = request.args.get("owner_id")
    owner_name = request.args.get("owner_name")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")
    vp_team = request.args.get("vp_team")
    quarter = request.args.get("quarter")

    sql = """
        SELECT
            product,
            SUM(product_arr_usd) AS total_arr,
            COUNT(DISTINCT crm_opportunity_id) AS opp_count
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product_arr_usd > 0
            AND opportunity_status = 'Open'
            AND product != 'Total Booking'
    """
    params = []

    if owner_name:
        sql += " AND LOWER(TRIM(opportunity_owner_name)) = LOWER(TRIM(%s))"
        params.append(owner_name)
    elif owner_id:
        sql += " AND ownerid = %s"
        params.append(owner_id)
    elif mgr_team:
        sql += " AND current_mgr_team = %s"
        params.append(mgr_team)
    elif dir_team:
        sql += " AND current_dir_team = %s"
        params.append(dir_team)
    elif vp_team:
        sql += " AND current_vp_team = %s"
        params.append(vp_team)
    else:
        return jsonify({"error": "owner_id, mgr_team, dir_team, or vp_team required"}), 400

    if quarter:
        sql += " AND close_year_quarter = %s"
        params.append(quarter)

    sql += " GROUP BY product ORDER BY total_arr DESC"

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()
    return jsonify(results)


@app.route("/api/metrics/summary")
def get_metrics_summary():
    owner_id = request.args.get("owner_id")
    owner_name = request.args.get("owner_name")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")
    vp_team = request.args.get("vp_team")
    quarter = request.args.get("quarter", "FY2027Q3")

    params = [quarter]
    if owner_name:
        owner_filter = "AND LOWER(TRIM(opportunity_owner_name)) = LOWER(TRIM(%s))"
        params.append(owner_name)
    elif owner_id:
        owner_filter = "AND ownerid = %s"
        params.append(owner_id)
    elif mgr_team:
        owner_filter = "AND current_mgr_team = %s"
        params.append(mgr_team)
    elif dir_team:
        owner_filter = "AND current_dir_team = %s"
        params.append(dir_team)
    elif vp_team:
        owner_filter = "AND current_vp_team = %s"
        params.append(vp_team)
    else:
        return jsonify({"error": "owner_id, mgr_team, dir_team, or vp_team required"}), 400

    pipeline_sql = f"""
        SELECT
            COALESCE(SUM(CASE WHEN product = 'Total Booking' THEN product_arr_usd END), 0) AS open_pipeline_total,
            COALESCE(SUM(CASE WHEN product = 'Total Booking' AND opportunity_type = 'New Business' THEN product_arr_usd END), 0) AS open_pipeline_nb,
            COALESCE(SUM(CASE WHEN product = 'Total Booking' AND opportunity_type = 'Expansion' THEN product_arr_usd END), 0) AS open_pipeline_exp,
            COALESCE(SUM(CASE WHEN product IN ('AI_Expert','Copilot','Ultimate','Ultimate_AR','Zendesk_AR','QA','WEM','Forethought_AI_Agents') THEN product_arr_usd END), 0) AS open_pipeline_ai,
            COUNT(DISTINCT CASE WHEN product = 'Total Booking' THEN crm_opportunity_id END) AS open_deal_count,
            COUNT(DISTINCT CASE WHEN product = 'Total Booking' AND opportunity_type = 'New Business' THEN crm_opportunity_id END) AS open_pipeline_nb_deal_count,
            COUNT(DISTINCT CASE WHEN product IN ('AI_Expert','Copilot','Ultimate','Ultimate_AR','Zendesk_AR','QA','WEM','Forethought_AI_Agents') THEN crm_opportunity_id END) AS open_pipeline_ai_deal_count
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product_arr_usd > 0
            AND opportunity_status = 'Open'
            AND stage_name ~ '^(02|03|04|05|06)'
            AND close_year_quarter = %s
            {owner_filter}
    """

    bookings_sql = f"""
        SELECT
            COALESCE(SUM(CASE WHEN product = 'Total Booking' THEN product_booking_arr_usd END), 0) AS bookings_total,
            COALESCE(SUM(CASE WHEN product = 'Total Booking' AND opportunity_type = 'New Business' AND product_booking_arr_usd > 0 THEN product_booking_arr_usd END), 0) AS bookings_nb,
            COALESCE(SUM(CASE WHEN product = 'Total Booking' AND opportunity_type = 'Expansion' THEN product_booking_arr_usd END), 0) AS bookings_exp,
            COALESCE(SUM(CASE WHEN product IN ('AI_Expert','Copilot','Ultimate','Ultimate_AR','Zendesk_AR','QA','WEM','Forethought_AI_Agents') AND product_booking_arr_usd > 0 THEN product_booking_arr_usd END), 0) AS bookings_ai,
            COUNT(DISTINCT CASE WHEN product = 'Total Booking' THEN crm_opportunity_id END) AS bookings_deal_count,
            COUNT(DISTINCT CASE WHEN product = 'Total Booking' AND opportunity_type = 'New Business' AND product_booking_arr_usd > 0 THEN crm_opportunity_id END) AS bookings_nb_deal_count,
            COUNT(DISTINCT CASE WHEN product IN ('AI_Expert','Copilot','Ultimate','Ultimate_AR','Zendesk_AR','QA','WEM','Forethought_AI_Agents') AND product_booking_arr_usd > 0 THEN crm_opportunity_id END) AS bookings_ai_deal_count
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND stage_name IN ('07 - Signed', '08 - Closed')
            AND close_year_quarter = %s
            {owner_filter}
    """

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(pipeline_sql, params)
    pipeline = cur.fetchone() or {}

    cur.execute(bookings_sql, params)
    bookings = cur.fetchone() or {}

    conn.close()
    return jsonify({**pipeline, **bookings})


@app.route("/api/stage_distribution")
def get_stage_distribution():
    owner_id = request.args.get("owner_id")
    quarter = request.args.get("quarter", "FY2027Q3")
    if not owner_id:
        return jsonify({"error": "owner_id required"}), 400

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT
            stage_name,
            COUNT(DISTINCT crm_opportunity_id) AS deal_count,
            SUM(product_arr_usd) AS total_arr
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product = 'Total Booking'
            AND product_arr_usd > 0
            AND opportunity_status = 'Open'
            AND ownerid = %s
            AND close_year_quarter = %s
        GROUP BY stage_name
        ORDER BY stage_name
    """, (owner_id, quarter))
    results = cur.fetchall()
    conn.close()
    return jsonify(results)


@app.route("/api/historical")
def get_historical():
    owner_id = request.args.get("owner_id")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")
    vp_team = request.args.get("vp_team")

    params = []
    if owner_id:
        owner_filter = "AND ownerid = %s"
        params.append(owner_id)
    elif mgr_team:
        owner_filter = "AND current_mgr_team = %s"
        params.append(mgr_team)
    elif dir_team:
        owner_filter = "AND current_dir_team = %s"
        params.append(dir_team)
    elif vp_team:
        owner_filter = "AND current_vp_team = %s"
        params.append(vp_team)
    else:
        return jsonify({"error": "owner_id, mgr_team, dir_team, or vp_team required"}), 400

    sql = f"""
        SELECT
            close_year_quarter AS quarter,
            COALESCE(SUM(CASE WHEN product = 'Total Booking' THEN product_booking_arr_usd END), 0) AS bookings_total,
            COALESCE(SUM(CASE WHEN product = 'Total Booking' AND opportunity_type = 'New Business' THEN product_booking_arr_usd END), 0) AS bookings_nb,
            COALESCE(SUM(CASE WHEN product = 'Total Booking' AND opportunity_type = 'Expansion' THEN product_booking_arr_usd END), 0) AS bookings_exp,
            COALESCE(SUM(CASE WHEN product IN ('AI_Expert','Copilot','Ultimate','Ultimate_AR','Zendesk_AR','QA','WEM','Forethought_AI_Agents') AND product_booking_arr_usd > 0 THEN product_booking_arr_usd END), 0) AS bookings_ai,
            COUNT(DISTINCT CASE WHEN product = 'Total Booking' THEN crm_opportunity_id END) AS deal_count
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND stage_name IN ('07 - Signed', '08 - Closed')
            {owner_filter}
            AND close_year_quarter IN ('FY2027Q1','FY2027Q2','FY2027Q3','FY2027Q4')
        GROUP BY close_year_quarter
        ORDER BY close_year_quarter
    """

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()
    return jsonify(results)


# ─── COACHING NOTES ──────────────────────────────────────────────────────────

@app.route("/api/notes/<ae_id>", methods=["GET"])
def get_notes(ae_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, ae_user_id, category, content, created_at AS timestamp FROM coaching_notes WHERE ae_user_id = %s ORDER BY created_at DESC",
        (ae_id,)
    )
    notes = cur.fetchall()
    conn.close()
    return jsonify(notes)


@app.route("/api/notes/<ae_id>", methods=["POST"])
def add_note(ae_id):
    data = request.json
    note_id = data.get("id", str(uuid.uuid4()))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO coaching_notes (id, ae_user_id, category, content) VALUES (%s, %s, %s, %s)",
        (note_id, ae_id, data["category"], data["content"])
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "created", "id": note_id}), 201


# ─── ACTION ITEMS ────────────────────────────────────────────────────────────

@app.route("/api/actions/<ae_id>", methods=["GET"])
def get_actions(ae_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM action_items WHERE ae_user_id = %s ORDER BY created_at DESC",
        (ae_id,)
    )
    items = cur.fetchall()
    conn.close()
    return jsonify(items)


@app.route("/api/actions/<ae_id>", methods=["POST"])
def add_action(ae_id):
    data = request.json
    item_id = data.get("id", str(uuid.uuid4()))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO action_items (id, ae_user_id, title, status, quarter, category) VALUES (%s, %s, %s, %s, %s, %s)",
        (item_id, ae_id, data["title"], data.get("status", "Not Started"), data["quarter"], data.get("category", "General"))
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "created", "id": item_id}), 201


@app.route("/api/actions/<ae_id>/<item_id>", methods=["PATCH"])
def update_action(ae_id, item_id):
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE action_items SET status = %s, updated_at = NOW() WHERE id = %s AND ae_user_id = %s",
        (data["status"], item_id, ae_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})


# ─── COMPETENCY SCORES ───────────────────────────────────────────────────────

@app.route("/api/competencies/<ae_id>", methods=["GET"])
def get_competencies(ae_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT scores FROM competency_scores WHERE ae_user_id = %s", (ae_id,))
    row = cur.fetchone()
    conn.close()
    return jsonify(row["scores"] if row else [3, 3, 3, 3, 3])


@app.route("/api/competencies/<ae_id>", methods=["PUT"])
def set_competencies(ae_id):
    scores = request.json.get("scores", [3, 3, 3, 3, 3])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO competency_scores (ae_user_id, scores, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (ae_user_id) DO UPDATE SET scores = EXCLUDED.scores, updated_at = NOW()
    """, (ae_id, json.dumps(scores)))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ─── WEEKLY TRACKER ──────────────────────────────────────────────────────────

@app.route("/api/weekly-tracker/<ae_id>", methods=["GET"])
def get_weekly_tracker(ae_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rows FROM weekly_tracker WHERE ae_user_id = %s", (ae_id,))
    row = cur.fetchone()
    conn.close()
    return jsonify(row["rows"] if row else None)


@app.route("/api/weekly-tracker/<ae_id>", methods=["PUT"])
def set_weekly_tracker(ae_id):
    rows = request.json.get("rows")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO weekly_tracker (ae_user_id, rows, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (ae_user_id) DO UPDATE SET rows = EXCLUDED.rows, updated_at = NOW()
    """, (ae_id, json.dumps(rows)))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ─── DEAL MAPS ──────────────────────────────────────────────────────────────

@app.route("/api/deal-maps/<ae_id>", methods=["GET"])
def get_deal_maps(ae_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT plans FROM deal_maps WHERE ae_user_id = %s", (ae_id,))
    row = cur.fetchone()
    conn.close()
    return jsonify(row["plans"] if row else [])


@app.route("/api/deal-maps/<ae_id>", methods=["PUT"])
def set_deal_maps(ae_id):
    plans = request.json.get("plans", [])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO deal_maps (ae_user_id, plans, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (ae_user_id) DO UPDATE SET plans = EXCLUDED.plans, updated_at = NOW()
    """, (ae_id, json.dumps(plans)))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ─── QUOTAS ─────────────────────────────────────────────────────────────────

@app.route("/api/quota/<ae_id>", methods=["GET"])
def get_quota(ae_id):
    quarter = request.args.get("quarter", "FY2027Q3")
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT quota_amount FROM quotas WHERE (ae_user_id = %s OR LOWER(TRIM(ae_user_id)) = LOWER(TRIM(%s))) AND quarter = %s",
        (ae_id, ae_id, quarter)
    )
    row = cur.fetchone()
    conn.close()
    return jsonify({"quota": float(row["quota_amount"]) if row else 0})


@app.route("/api/forecast")
def get_forecast():
    name = request.args.get("name", "").strip()
    quarter = request.args.get("quarter", "FY2027Q3")
    empty = {"name": name, "quarter": quarter, "quota": 0, "forecast": 0, "bookings": 0, "ai_target": 0, "ai_bookings": 0, "nb_target": 0, "nb_bookings": 0, "pipeline": 0}
    if not name or not CLARI_FORECAST_FILE.exists():
        return jsonify(empty)
    with CLARI_FORECAST_FILE.open(newline="", encoding="utf-8-sig") as handle:
        rows = csv.DictReader(handle)
        target = next((row for row in rows if (row.get("NAME") or "").strip().casefold() == name.casefold() and (row.get("YEAR_QUARTER") or "") == quarter.replace("FY", "").replace("Q", "_Q")), None)
    if not target:
        return jsonify(empty)
    def number(key):
        try: return float(target.get(key) or 0)
        except (TypeError, ValueError): return 0
    return jsonify({"name": target.get("NAME", name), "quarter": quarter, "quota": number("QUARTER_QUOTA"), "forecast": number("QUARTER_FORECAST"), "bookings": number("SIGNED"), "ai_target": number("AI_QUARTER_QUOTA"), "ai_bookings": number("AI_SIGNED"), "nb_target": number("NB_QUARTER_QUOTA"), "nb_bookings": number("NB_SIGNED"), "pipeline": number("PIPELINE")})


@app.route("/api/forecast/team", methods=["GET"])
def get_team_forecast():
    quarter = request.args.get("quarter", "FY2027Q3")
    names = {(value or "").strip().casefold() for value in request.args.get("names", "").split("|") if value.strip()}
    totals = {"quota": 0, "forecast": 0, "bookings": 0, "ai_target": 0, "ai_bookings": 0, "nb_target": 0, "nb_bookings": 0, "pipeline": 0}
    if not names or not CLARI_FORECAST_FILE.exists():
        return jsonify({"name": "Team", "quarter": quarter, **totals})
    with CLARI_FORECAST_FILE.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if (row.get("NAME") or "").strip().casefold() not in names or canonical_quarter(row.get("YEAR_QUARTER")) != quarter:
                continue
            for output, source in (("quota", "QUARTER_QUOTA"), ("forecast", "QUARTER_FORECAST"), ("bookings", "SIGNED"), ("ai_target", "AI_QUARTER_QUOTA"), ("ai_bookings", "AI_SIGNED"), ("nb_target", "NB_QUARTER_QUOTA"), ("nb_bookings", "NB_SIGNED"), ("pipeline", "PIPELINE")):
                try: totals[output] += float(row.get(source) or 0)
                except (TypeError, ValueError): pass
    return jsonify({"name": "Team", "quarter": quarter, **totals})


@app.route("/api/quota/<ae_id>", methods=["PUT"])
def set_quota(ae_id):
    data = request.json
    quarter = data.get("quarter", "FY2027Q3")
    amount = float(data.get("quota", 0))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO quotas (ae_user_id, quarter, quota_amount, source, updated_at)
        VALUES (%s, %s, %s, 'manual', NOW())
        ON CONFLICT (ae_user_id, quarter) DO UPDATE SET quota_amount = EXCLUDED.quota_amount, source = 'manual', updated_at = NOW()
    """, (ae_id, quarter, amount))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/quota/team", methods=["GET"])
def get_team_quotas():
    quarter = request.args.get("quarter", "FY2027Q3")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")
    vp_team = request.args.get("vp_team")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    owner_filter = ""
    filter_params = []
    if mgr_team:
        owner_filter = "AND p.current_mgr_team = %s"
        filter_params.append(mgr_team)
    elif dir_team:
        owner_filter = "AND p.current_dir_team = %s"
        filter_params.append(dir_team)
    elif vp_team:
        owner_filter = "AND p.current_vp_team = %s"
        filter_params.append(vp_team)

    cur.execute(f"""
        SELECT COALESCE(SUM(q.quota_amount), 0) AS total_quota
        FROM quotas q
        JOIN (
            SELECT DISTINCT opportunity_owner_name
            FROM pipeline_data p
            WHERE p.opportunity_is_commissionable = TRUE
                AND p.product = 'Total Booking'
                {owner_filter}
        ) owners ON LOWER(TRIM(q.ae_user_id)) = LOWER(TRIM(owners.opportunity_owner_name))
        WHERE q.quarter = %s
    """, filter_params + [quarter])
    row = cur.fetchone()
    conn.close()
    return jsonify({"quota": float(row["total_quota"]) if row else 0})


# ─── LINEARITY (monthly bookings within a quarter) ──────────────────────────

@app.route("/api/linearity")
def get_linearity():
    owner_id = request.args.get("owner_id")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")
    vp_team = request.args.get("vp_team")
    quarter = request.args.get("quarter", "FY2027Q3")

    owner_filter = ""
    params = [quarter]
    if owner_id:
        owner_filter = "AND ownerid = %s"
        params.append(owner_id)
    elif mgr_team:
        owner_filter = "AND current_mgr_team = %s"
        params.append(mgr_team)
    elif dir_team:
        owner_filter = "AND current_dir_team = %s"
        params.append(dir_team)
    elif vp_team:
        owner_filter = "AND current_vp_team = %s"
        params.append(vp_team)
    else:
        return jsonify([])

    sql = f"""
        SELECT
            TO_CHAR(TO_DATE(closedate, 'YYYY-MM-DD'), 'YYYY-MM') AS close_month,
            COUNT(DISTINCT crm_opportunity_id) AS deals,
            COALESCE(SUM(product_booking_arr_usd), 0) AS bookings
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product = 'Total Booking'
            AND stage_name IN ('07 - Signed', '08 - Closed')
            AND close_year_quarter = %s
            {owner_filter}
        GROUP BY close_month
        ORDER BY close_month
    """

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()
    return jsonify(results)


# ─── PIPELINE CREATION (CiQ — opps entering stage 2+ in quarter) ───────────

@app.route("/api/pipe_creation")
def get_pipe_creation():
    owner_id = request.args.get("owner_id")
    mgr_team = request.args.get("mgr_team")
    dir_team = request.args.get("dir_team")
    vp_team = request.args.get("vp_team")
    quarter = request.args.get("quarter", "FY2027Q3")
    cadence = request.args.get("cadence", "month")

    # Map fiscal quarter to calendar date range
    FQ_MAP = {
        "FY2027Q1": ("2026-02-01", "2026-04-30"),
        "FY2027Q2": ("2026-05-01", "2026-07-31"),
        "FY2027Q3": ("2026-08-01", "2026-10-31"),
        "FY2027Q4": ("2026-11-01", "2027-01-31"),
        "FY2028Q1": ("2027-02-01", "2027-04-30"),
    }
    date_range = FQ_MAP.get(quarter)
    if not date_range:
        return jsonify([])

    owner_filter = ""
    params = [date_range[0], date_range[1]]
    if owner_id:
        owner_filter = "AND ownerid = %s"
        params.append(owner_id)
    elif mgr_team:
        owner_filter = "AND current_mgr_team = %s"
        params.append(mgr_team)
    elif dir_team:
        owner_filter = "AND current_dir_team = %s"
        params.append(dir_team)
    elif vp_team:
        owner_filter = "AND current_vp_team = %s"
        params.append(vp_team)
    else:
        return jsonify([])

    period_sql = "TO_CHAR(DATE_TRUNC('week', TO_DATE(stage_2_plus_date_c, 'YYYY-MM-DD')), 'YYYY-MM-DD')" if cadence == "week" else "TO_CHAR(TO_DATE(stage_2_plus_date_c, 'YYYY-MM-DD'), 'YYYY-MM')"
    sql = f"""
        SELECT
            {period_sql} AS created_period,
            COUNT(DISTINCT crm_opportunity_id) AS opps,
            COALESCE(SUM(product_arr_usd), 0) AS arr
        FROM pipeline_data
        WHERE opportunity_is_commissionable = TRUE
            AND product = 'Total Booking'
            AND product_arr_usd > 0
            AND stage_2_plus_date_c >= %s
            AND stage_2_plus_date_c <= %s
            {owner_filter}
        GROUP BY created_period
        ORDER BY created_period
    """

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params)
    results = cur.fetchall()
    conn.close()
    return jsonify(results)


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"Starting SalesPilot data server on http://localhost:{port}")
    print(f"Admin password: {'SET' if ADMIN_PASSWORD else 'NOT SET (admin disabled)'}")
    init_db()
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
