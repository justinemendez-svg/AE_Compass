"""Build a compact, AppFoundry-ready AE Compass data bundle.

The normal workflow is intentionally manual:

    python3 server/refresh_appfoundry_data.py

Use ``--pull-live`` when the local Salesforce/Snowflake credentials are ready.
That refreshes the source exports first, then writes a small ZIP package to
the shared AE Compass folder.  Raw Gong calls/transcripts are never copied.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(
    "/Users/justine.mendez/Library/CloudStorage/GoogleDrive-"
    "justine.mendez@zendesk.com/Shared drives/GTM Ops/APAC/AE Compass"
)
DATA_DIR = Path(os.environ.get("AE_COMPASS_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser()
PACKAGE_NAME = "AE_Compass_AppFoundry_Data.zip"

SOURCE_FILES = {
    "workday": "workday_hierarchy_chris_donato.csv",
    "gtmi": "gtmsi_pipeline_current_quarter.csv",
    "sfdc": "salesforce_opportunities_current_quarter.csv",
    "clari": "clari_forecast_current_quarter.csv",
}

WORKDAY_COLUMNS = [
    "C_STAFF", "C_STAFF_1", "C_STAFF_2", "C_STAFF_3", "C_STAFF_4",
    "EMPLOYEE_ID", "FULL_NAME", "EMAIL", "WORKER_MANAGER",
    "BUSINESS_TITLE", "JOB_TITLE", "MANAGEMENT_LEVEL", "WORKER_STATUS",
    "REGION", "COUNTRY",
]
GTMI_COLUMNS = [
    "OWNERID", "OPPORTUNITY_OWNER_NAME", "CRM_OPPORTUNITY_ID",
    "OPPORTUNITY_NAME", "CRM_ACCOUNT_NAME", "STAGE_NAME", "OPPORTUNITY_TYPE",
    "OPPORTUNITY_STATUS", "PRODUCT", "PRODUCT_ARR_USD",
    "PRODUCT_BOOKING_ARR_USD", "CLOSEDATE", "STAGE_2_PLUS_DATE_C",
    "GTM_TEAM", "VP_DEAL_FORECAST__C", "MANAGER_FORECAST__C",
    "CLOSE_YEAR_QUARTER", "D_SCORE_LATEST__C", "DATE_LABEL",
    "OPPORTUNITY_IS_COMMISSIONABLE", "CURRENT_VP_TEAM", "CURRENT_DIR_TEAM",
    "CURRENT_MGR_TEAM", "PRO_FORMA_MARKET_SEGMENT", "SVP_NAME",
]
SFDC_COLUMNS = [
    "CRM_OPPORTUNITY_ID", "OPPORTUNITY_NAME", "OWNERID",
    "OPPORTUNITY_OWNER_NAME", "STAGE_NAME", "OPPORTUNITY_TYPE", "CLOSEDATE",
    "BOOKING_ARR__C", "NON_COMMISSIONABLE", "TOTAL_COMMISSIONABLE_ARR_C",
    "CLOSE_YEAR_QUARTER", "OPPORTUNITY_STATUS",
]
CLARI_COLUMNS = [
    "YEAR_QUARTER", "CRM_USER_ID", "USER_ROLE_LABEL", "USER_EMAIL",
    "USER_FUNCTION", "IS_ACTIVE_CRM_USER", "MARKET_SEGMENT", "VP_TEAM",
    "DIRECTOR_TEAM", "MANAGER_TEAM", "NAME", "USER_TYPE", "QUARTER_FORECAST",
    "QUARTER_BESTCASE", "QUARTER_WORSTCASE", "QUARTER_MONTH1_FORECAST",
    "QUARTER_MONTH2_FORECAST", "QUARTER_MONTH3_FORECAST", "QUARTER_QUOTA",
    "PIPELINE", "SIGNED", "DEAL_BACKED_WORST_CASE", "DEAL_BACKED_FORECAST",
    "NB_QUARTER_QUOTA", "NB_SIGNED", "NB_QUARTER_FORECAST", "NB_PIPELINE",
    "AI_QUARTER_QUOTA", "AI_SIGNED", "AI_QUARTER_FORECAST", "AI_PIPELINE",
    "RUN_DATE",
]


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def number(value: object) -> float:
    try:
        return float(text(value).replace(",", "") or 0)
    except (TypeError, ValueError):
        return 0.0


def truthy(value: object, default: bool = False) -> bool:
    raw = text(value).lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "y", "t"}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing source export: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def current_quarter() -> tuple[str, str]:
    today = dt.date.today()
    fiscal_year = today.year + 1 if today.month >= 2 else today.year
    quarter = ((today.month - 2) % 12) // 3 + 1
    return f"FY{fiscal_year}Q{quarter}", f"{fiscal_year}_Q{quarter}"


def run_live_pulls() -> list[str]:
    """Refresh sources using existing AE Compass pullers where available."""
    messages: list[str] = []
    sfdc_script = PROJECT_ROOT / "server" / "pull_sfdc_current.py"
    clari_script = PROJECT_ROOT / "server" / "export_clari_forecast_for_appfoundry.py"
    for script in (sfdc_script, clari_script):
        result = subprocess.run([sys.executable, str(script)], cwd=PROJECT_ROOT, text=True)
        if result.returncode:
            raise RuntimeError(f"Live pull failed: {script.name}")
        messages.append(f"refreshed {script.name}")

    # GTMI does not have a separate exporter in this repo, so pull its compact
    # source directly.  This remains opt-in because Snowflake SSO is interactive.
    try:
        import snowflake.connector  # type: ignore
        from dotenv import load_dotenv  # type: ignore
    except ImportError as exc:
        raise RuntimeError("--pull-live requires snowflake-connector-python and python-dotenv") from exc

    gtm_env = PROJECT_ROOT.parent / "gtm-ops-claude" / ".env"
    load_dotenv(gtm_env)
    query = """
        SELECT OWNERID, OPPORTUNITY_OWNER_NAME, CRM_OPPORTUNITY_ID,
               OPPORTUNITY_NAME, CRM_ACCOUNT_NAME, STAGE_NAME, OPPORTUNITY_TYPE,
               OPPORTUNITY_STATUS, PRODUCT, PRODUCT_ARR_USD,
               PRODUCT_BOOKING_ARR_USD, CLOSEDATE, STAGE_2_PLUS_DATE_C,
               GTM_TEAM, VP_DEAL_FORECAST__C, MANAGER_FORECAST__C,
               CLOSE_YEAR_QUARTER, D_SCORE_LATEST__C, DATE_LABEL,
               OPPORTUNITY_IS_COMMISSIONABLE, CURRENT_VP_TEAM, CURRENT_DIR_TEAM,
               CURRENT_MGR_TEAM, PRO_FORMA_MARKET_SEGMENT, SVP_NAME
        FROM FUNCTIONAL.GTM_SALES_OPS.GTMSI_CONSOLIDATED_PIPELINE_BOOKINGS
        WHERE DATE_LABEL = 'today'
          AND OPPORTUNITY_IS_COMMISSIONABLE = TRUE
          AND (PRODUCT_ARR_USD > 0 OR PRODUCT_BOOKING_ARR_USD > 0)
    """
    connection = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        authenticator=os.getenv("SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        client_store_temporary_credential=True,
    )
    try:
        cursor = connection.cursor()
        cursor.execute(query)
        columns = [description[0] for description in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()
    write_rows(DATA_DIR / SOURCE_FILES["gtmi"], rows, GTMI_COLUMNS)
    messages.append(f"refreshed GTMI ({len(rows):,} rows)")
    return messages


def build_bundle() -> tuple[Path, dict[str, object]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fy_label, clari_label = current_quarter()
    temp_dir = Path(tempfile.mkdtemp(prefix="ae-compass-bundle-"))
    try:
        manifest: dict[str, object] = {
            "bundle_version": 1,
            "generated_at": dt.datetime.now().astimezone().isoformat(),
            "zendesk_fiscal_quarter": fy_label,
            "clari_year_quarter": clari_label,
            "source_directory": str(DATA_DIR),
            "filters": {
                "workday": "C_STAFF = Chris Donato; active workers; _FIVETRAN_DELETED is false when present",
                "gtmi": "DATE_LABEL = today; commissionable = true; PRODUCT_ARR_USD or PRODUCT_BOOKING_ARR_USD > 0",
                "sfdc": "Booking/commissionable ARR > 0; non-commissionable = false in source pull",
                "clari": f"YEAR_QUARTER = {clari_label}; current snapshot export",
                "gong": "not included; raw calls/transcripts are intentionally excluded from AppFoundry bundle",
            },
            "files": {},
        }

        workday = read_rows(DATA_DIR / SOURCE_FILES["workday"])
        workday = [
            row for row in workday
            if text(row.get("C_STAFF")) == "Chris Donato"
            and text(row.get("WORKER_STATUS") or "active").lower() in {"1", "true", "active", "yes", "y"}
            and text(row.get("_FIVETRAN_DELETED") or "false").lower() in {"", "0", "false", "no", "n"}
        ]

        gtmi = [
            row for row in read_rows(DATA_DIR / SOURCE_FILES["gtmi"])
            if truthy(row.get("OPPORTUNITY_IS_COMMISSIONABLE"))
            and (number(row.get("PRODUCT_ARR_USD")) > 0 or number(row.get("PRODUCT_BOOKING_ARR_USD")) > 0)
        ]
        sfdc = [
            row for row in read_rows(DATA_DIR / SOURCE_FILES["sfdc"])
            if number(row.get("BOOKING_ARR__C")) > 0
            and not truthy(row.get("NON_COMMISSIONABLE"), default=False)
        ]
        clari = [row for row in read_rows(DATA_DIR / SOURCE_FILES["clari"]) if text(row.get("YEAR_QUARTER")) == clari_label]

        datasets = {
            "workday_roster.csv": (workday, WORKDAY_COLUMNS),
            "gtmi_pipeline.csv": (gtmi, GTMI_COLUMNS),
            "sfdc_opportunities.csv": (sfdc, SFDC_COLUMNS),
            "clari_forecast.csv": (clari, CLARI_COLUMNS),
        }
        for filename, (rows, columns) in datasets.items():
            destination = temp_dir / filename
            write_rows(destination, rows, columns)
            manifest["files"][filename] = {"rows": len(rows), "columns": columns}

        (temp_dir / "README.txt").write_text(
            "AE Compass AppFoundry data bundle\n"
            "Generated manually by server/refresh_appfoundry_data.py\n"
            "The CSVs are intentionally slimmed for AppFoundry. Re-run the refresh when new exports are ready.\n",
            encoding="utf-8",
        )
        (temp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        output = DATA_DIR / PACKAGE_NAME
        staged = DATA_DIR / f".{PACKAGE_NAME}.tmp"
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for item in sorted(temp_dir.iterdir()):
                archive.write(item, arcname=item.name)
        staged.replace(output)
        return output, manifest
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull-live", action="store_true", help="refresh SFDC, Clari and GTMI before packaging")
    args = parser.parse_args()
    if args.pull_live:
        for message in run_live_pulls():
            print(message)
    output, manifest = build_bundle()
    print(f"wrote {output}")
    print(f"size: {output.stat().st_size / 1024 / 1024:.2f} MB")
    for filename, info in manifest["files"].items():
        print(f"{filename}: {info['rows']:,} rows")


if __name__ == "__main__":
    main()
