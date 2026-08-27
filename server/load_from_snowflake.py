"""
Pull live pipeline data from Snowflake (GTMSI table) and load into local PostgreSQL.
Triggers Okta SSO browser login on first run.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'gtm-ops-claude'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', 'gtm-ops-claude', '.env'))

import snowflake.connector
import pandas as pd
from quarter_utils import canonical_quarter
import psycopg2

SNOWFLAKE_QUERY = """
select
    ownerid,
    opportunity_owner_name,
    crm_opportunity_id,
    opportunity_name,
    crm_account_name,
    stage_name,
    opportunity_type,
    opportunity_status,
    product,
    product_arr_usd,
    product_booking_arr_usd,
    closedate,
    stage_2_plus_date_c,
    gtm_team,
    vp_deal_forecast__c,
    manager_forecast__c,
    close_year_quarter,
    d_score_latest__c,
    date_label,
    opportunity_is_commissionable,
    current_vp_team,
    current_dir_team,
    current_mgr_team,
    pro_forma_market_segment,
    svp_name,
    svpm1_name,
    svpm2_name,
    svpm3_name,
    svpm4_name
from functional.gtm_sales_ops.gtmsi_consolidated_pipeline_bookings
where date_label = 'today'
    and opportunity_is_commissionable = true
    and closedate >= '2025-08-01'
    and product_arr_usd > 0
"""

QUOTA_QUERY_TEMPLATE = """
select
    crm_user_id as user_id,
    name as user_name,
    quarter_quota as quota
from functional.gtm_sales_ops.clari_curated_forecasts_by_deal_owner
where year_quarter = '{clari_quarter}'
    and run_date = (
        select max(run_date)
        from functional.gtm_sales_ops.clari_curated_forecasts_by_deal_owner
        where year_quarter = '{clari_quarter}'
    )
    and quarter_quota > 0
"""


def resolve_hierarchy(row):
    """Resolve GTMSI svpm1-4 into Clari hierarchy: SVP > RVP > Director > Manager.

    GTMSI stores a variable-depth chain from SVP downward:
      svp_name > svpm1_name > svpm2_name > svpm3_name > svpm4_name > AE

    The levels above the AE represent (from bottom up):
      - svpm4_name = frontline manager (if exists)
      - svpm3_name = director or manager (depends on depth)
      - svpm2_name = director or RVP
      - svpm1_name = RVP (SVP-1)

    Clari hierarchy for Sales:
      SVP > RVP (SVP-1) > Director (optional) > Manager (optional) > AE

    RVP is always svpm1_name.
    Levels below depend on chain depth for each AE.
    """
    svp = row.get("svp_name") or ""
    m1 = row.get("svpm1_name") or ""
    m2 = row.get("svpm2_name") or ""
    m3 = row.get("svpm3_name") or ""
    m4 = row.get("svpm4_name") or ""

    rvp = m1
    director = ""
    manager = ""

    # Count non-TBH levels between RVP and AE
    levels = [l for l in [m2, m3, m4] if l and l != "TBH"]

    if len(levels) == 0:
        # RVP manages AEs directly
        pass
    elif len(levels) == 1:
        # One level between RVP and AE = Manager (no director)
        manager = levels[0]
    elif len(levels) == 2:
        # Two levels = Director > Manager
        director = levels[0]
        manager = levels[1]
    elif len(levels) >= 3:
        # Three levels = Director > Sr Manager > Manager (rare)
        director = levels[0]
        manager = levels[-1]

    return rvp, director, manager


def connect_snowflake():
    print("Connecting to Snowflake (Okta SSO — check your browser)...")
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        authenticator=os.getenv("SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
    )
    print("Snowflake connected.")
    return conn


def pull_data(sf_conn):
    print("Pulling pipeline data from GTMSI table...")
    cur = sf_conn.cursor()
    cur.execute(SNOWFLAKE_QUERY)
    columns = [desc[0].lower() for desc in cur.description]
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=columns)
    print(f"Pulled {len(df)} rows from Snowflake.")
    return df


def pull_quotas(sf_conn, clari_quarter):
    """Pull quota from Clari curated forecasts table.
    clari_quarter format: '2027_Q2' (matches Clari's YEAR_QUARTER column).
    """
    print(f"Pulling quota data from Clari (quarter: {clari_quarter})...")
    query = QUOTA_QUERY_TEMPLATE.format(clari_quarter=clari_quarter)
    cur = sf_conn.cursor()
    cur.execute(query)
    columns = [desc[0].lower() for desc in cur.description]
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=columns)
    print(f"Pulled {len(df)} quota records from Clari.")
    return df


def load_into_postgres(df):
    upload_id = str(uuid.uuid4())

    pg_conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "salespilot"),
        user=os.environ.get("DB_USER", "salespilot"),
        password=os.environ.get("DB_PASS", ""),
    )
    pg_conn.autocommit = False
    cur = pg_conn.cursor()

    # Clear existing data
    cur.execute("DELETE FROM pipeline_data")
    cur.execute("UPDATE data_uploads SET is_active = FALSE")

    print("Loading into PostgreSQL...")
    count = 0
    for _, row in df.iterrows():
        is_comm = row.get("opportunity_is_commissionable", True)
        if isinstance(is_comm, str):
            is_comm = is_comm.lower() in ("true", "1", "yes", "t")

        closedate = row.get("closedate", "")
        close_year_quarter = canonical_quarter(row.get("close_year_quarter"), closedate)
        product_arr = float(row.get("product_arr_usd", 0) or 0)
        booking_arr = float(row.get("product_booking_arr_usd", 0) or 0)

        rvp, director, manager = resolve_hierarchy(row)

        cur.execute("""
            INSERT INTO pipeline_data (
                upload_id, ownerid, opportunity_owner_name, crm_opportunity_id,
                opportunity_name, crm_account_name, stage_name, opportunity_type,
                opportunity_status, product, product_arr_usd, product_booking_arr_usd,
                closedate, stage_2_plus_date_c, gtm_team, vp_deal_forecast__c,
                manager_forecast__c, close_year_quarter, d_score_latest__c,
                date_label, opportunity_is_commissionable,
                current_vp_team, current_dir_team, current_mgr_team,
                pro_forma_market_segment, manager_name, director_name, rvp_name, svp_name,
                svpm1_name, svpm2_name, svpm3_name, svpm4_name
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            upload_id,
            str(row.get("ownerid", "")),
            str(row.get("opportunity_owner_name", "")),
            str(row.get("crm_opportunity_id", "")),
            str(row.get("opportunity_name", "")),
            str(row.get("crm_account_name", "")),
            str(row.get("stage_name", "")),
            str(row.get("opportunity_type", "")),
            str(row.get("opportunity_status", "")),
            str(row.get("product", "")),
            product_arr,
            booking_arr,
            str(closedate),
            str(row.get("stage_2_plus_date_c", "")),
            str(row.get("gtm_team", "")),
            str(row.get("vp_deal_forecast__c", "")),
            str(row.get("manager_forecast__c", "")),
            str(close_year_quarter),
            str(row.get("d_score_latest__c", "")),
            str(row.get("date_label", "today")),
            is_comm,
            str(row.get("current_vp_team", "")),
            str(row.get("current_dir_team", "")),
            str(row.get("current_mgr_team", "")),
            str(row.get("pro_forma_market_segment", "")),
            manager,
            director,
            rvp,
            str(row.get("svp_name", "") or ""),
            str(row.get("svpm1_name", "") or ""),
            str(row.get("svpm2_name", "") or ""),
            str(row.get("svpm3_name", "") or ""),
            str(row.get("svpm4_name", "") or ""),
        ))
        count += 1

    cur.execute("""
        INSERT INTO data_uploads (id, filename, row_count, is_active)
        VALUES (%s, %s, %s, TRUE)
    """, (upload_id, 'snowflake_live_pull', count))

    pg_conn.commit()
    pg_conn.close()
    print(f"Loaded {count} rows into PostgreSQL. Done!")


def load_quotas_into_postgres(df, fiscal_quarter):
    """Load Clari quota data into the local quotas table."""
    pg_conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "salespilot"),
        user=os.environ.get("DB_USER", "salespilot"),
        password=os.environ.get("DB_PASS", ""),
    )
    pg_conn.autocommit = False
    cur = pg_conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS quotas (
            ae_user_id TEXT NOT NULL,
            quarter TEXT NOT NULL,
            quota_amount NUMERIC NOT NULL DEFAULT 0,
            source TEXT DEFAULT 'snowflake',
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (ae_user_id, quarter)
        )
    """)

    count = 0
    for _, row in df.iterrows():
        # Clari's NAME is the canonical key used by the UI to match the
        # selected Workday FULL_NAME. Keep the CRM ID only as fallback.
        user_id = str(row.get("user_name") or row.get("user_id", ""))
        quota = float(row.get("quota", 0) or 0)
        if not user_id or quota <= 0:
            continue

        cur.execute("""
            INSERT INTO quotas (ae_user_id, quarter, quota_amount, source, updated_at)
            VALUES (%s, %s, %s, 'clari', NOW())
            ON CONFLICT (ae_user_id, quarter) DO UPDATE
                SET quota_amount = EXCLUDED.quota_amount,
                    source = 'clari',
                    updated_at = NOW()
        """, (user_id, fiscal_quarter, quota))
        count += 1

    pg_conn.commit()
    pg_conn.close()
    print(f"Loaded {count} Clari quotas for {fiscal_quarter} into PostgreSQL.")


def fiscal_to_clari_quarter(fq):
    """Convert FY2027Q2 -> 2027_Q2"""
    return fq.replace("FY", "").replace("Q", "_Q")


if __name__ == "__main__":
    sf_conn = connect_snowflake()
    df = pull_data(sf_conn)
    load_into_postgres(df)

    # Load Clari quotas for current and next quarter
    quarters_to_load = ["FY2027Q2", "FY2027Q3"]
    for fq in quarters_to_load:
        clari_q = fiscal_to_clari_quarter(fq)
        quota_df = pull_quotas(sf_conn, clari_q)
        load_quotas_into_postgres(quota_df, fq)

    sf_conn.close()
