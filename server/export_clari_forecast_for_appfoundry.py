"""Export Clari forecast snapshots for AE Compass/AppFoundry.

This script is intentionally manual. It reads Snowflake only and writes the
filtered export into the AE Compass Shared Drive folder. It does not modify
any other repository or load data into a database.

Run from AE Compass:
    python3 server/export_clari_forecast_for_appfoundry.py

By default this keeps all four quarters in the current fiscal year in the
same compact file. Pass one or more Clari labels (for example ``2027_Q4``)
to pull specific quarters.
"""

import csv
import json
import os
import sys
from datetime import date
from pathlib import Path

import snowflake.connector
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GTM_ENV = PROJECT_ROOT.parent / "gtm-ops-claude" / ".env"
sys.path.insert(0, str(PROJECT_ROOT.parent / "gtm-ops-claude"))
load_dotenv(GTM_ENV)

DESTINATION = Path(
    "/Users/justine.mendez/Library/CloudStorage/GoogleDrive-"
    "justine.mendez@zendesk.com/Shared drives/GTM Ops/APAC/AE Compass"
)
CSV_NAME = "clari_forecast_current_quarter.csv"
METADATA_NAME = "clari_forecast_current_quarter.metadata.json"


def current_fiscal_quarter(today: date | None = None) -> tuple[str, str]:
    """Return (Zendesk FY label, Clari YEAR_QUARTER label).

    Zendesk fiscal years start in February: Q1 Feb-Apr, Q2 May-Jul,
    Q3 Aug-Oct, Q4 Nov-Jan.
    """
    today = today or date.today()
    fiscal_year = today.year + 1 if today.month >= 2 else today.year
    quarter = ((today.month - 2) % 12) // 3 + 1
    return f"FY{fiscal_year}Q{quarter}", f"{fiscal_year}_Q{quarter}"


def clari_quarter_label(fiscal_label: str) -> str:
    return fiscal_label.removeprefix("FY").replace("Q", "_Q")


def next_fiscal_quarter(today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    fiscal_label, _ = current_fiscal_quarter(today)
    fiscal_year = int(fiscal_label[2:6])
    quarter = int(fiscal_label[-1])
    if quarter == 4:
        fiscal_year += 1
        quarter = 1
    else:
        quarter += 1
    return f"FY{fiscal_year}Q{quarter}", f"{fiscal_year}_Q{quarter}"


def connect():
    # Reuse the existing GTM Ops file-based SSO token cache when available,
    # avoiding a second browser login for the manual AppFoundry pull.
    try:
        from connections.snowflake.auth import setup_file_keyring
        setup_file_keyring()
    except ImportError:
        pass
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        authenticator=os.getenv("SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        client_store_temporary_credential=True,
    )


def main():
    current_fiscal_label, current_clari_label = current_fiscal_quarter()
    fiscal_year = current_fiscal_label[2:6]
    requested = sys.argv[1:] or [f"{fiscal_year}_Q{quarter}" for quarter in range(1, 5)]
    clari_labels = [clari_quarter_label(value) if value.startswith("FY") else value for value in requested]
    fiscal_labels = [f"FY{label.split('_Q')[0]}Q{label.split('_Q')[1]}" for label in clari_labels]
    DESTINATION.mkdir(parents=True, exist_ok=True)
    output_csv = DESTINATION / CSV_NAME
    output_metadata = DESTINATION / METADATA_NAME

    placeholders = ", ".join(["%s"] * len(clari_labels))
    query = f"""
        SELECT *
        FROM FUNCTIONAL.GTM_SALES_OPS.CLARI_CURATED_FORECASTS_BY_DEAL_OWNER AS forecasts
        WHERE forecasts.YEAR_QUARTER IN ({placeholders})
          AND RUN_DATE = (
              SELECT MAX(RUN_DATE)
              FROM FUNCTIONAL.GTM_SALES_OPS.CLARI_CURATED_FORECASTS_BY_DEAL_OWNER
              WHERE YEAR_QUARTER = forecasts.YEAR_QUARTER
          )
    """

    print(f"Connecting to Snowflake for {', '.join(clari_labels)}…")
    connection = connect()
    try:
        cursor = connection.cursor()
        cursor.execute(query, tuple(clari_labels))
        headers = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
    finally:
        connection.close()

    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)

    metadata = {
        "source": "FUNCTIONAL.GTM_SALES_OPS.CLARI_CURATED_FORECASTS_BY_DEAL_OWNER",
        "year_quarters": clari_labels,
        "zendesk_fiscal_quarters": fiscal_labels,
        "run_date": str(rows[0][headers.index("RUN_DATE")]) if rows and "RUN_DATE" in headers else None,
        "row_count": len(rows),
        "columns": headers,
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
    }
    output_metadata.write_text(json.dumps(metadata, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows):,} rows to {output_csv}")
    print(f"Wrote metadata to {output_metadata}")


if __name__ == "__main__":
    main()
