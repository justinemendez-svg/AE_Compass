from pathlib import Path
import sys

sys.path.insert(0, "/Users/justine.mendez/Desktop/northstar2026/gtm-ops-claude")
from connections.snowflake import query


SQL = """
SELECT
    o.ID AS crm_opportunity_id,
    o.NAME AS opportunity_name,
    o.OWNER_ID AS ownerid,
    u.NAME AS opportunity_owner_name,
    o.STAGE_NAME AS stage_name,
    o.TYPE AS opportunity_type,
    o.CLOSE_DATE AS closedate,
    f.BOOKING_ARR_C AS BOOKING_ARR__C,
    o.NON_COMMISSIONABLE_C AS NON_COMMISSIONABLE,
    COALESCE(ds.TOTAL_COMMISSIONABLE_ARR_C, 0) AS TOTAL_COMMISSIONABLE_ARR_C,
    d.FISCAL_YEAR_QUARTER AS close_year_quarter,
    CASE WHEN REGEXP_LIKE(o.STAGE_NAME, '^0[78]') THEN 'Closed' ELSE 'Open' END AS opportunity_status
FROM CLEANSED.SALESFORCE.SALESFORCE_OPPORTUNITY_SCD2 o
JOIN CLEANSED.SALESFORCE.SALESFORCE_OPPORTUNITY_FORMULA_BCV f
    ON f.OPPORTUNITY_18_DIGIT_ID_C = o.ID
LEFT JOIN (
    SELECT OPPORTUNITY_18_DIGIT_ID_C, TOTAL_COMMISSIONABLE_ARR_C
    FROM CLEANSED.SALESFORCE.SALESFORCE_OPPORTUNITY_FORMULA_DAILY_SNAPSHOT
    QUALIFY ROW_NUMBER() OVER (PARTITION BY OPPORTUNITY_18_DIGIT_ID_C ORDER BY SOURCE_SNAPSHOT_DATE DESC, RUN_DATE DESC) = 1
) ds ON ds.OPPORTUNITY_18_DIGIT_ID_C = o.ID
LEFT JOIN CLEANSED.SALESFORCE.SALESFORCE_USER_BCV u
    ON u.ID = o.OWNER_ID
LEFT JOIN FOUNDATIONAL.FINANCE.DIM_DATE d
    ON d.THE_DATE = o.CLOSE_DATE
WHERE o.VALID_TO_TIMESTAMP = '9999-12-31'
  AND TRY_TO_NUMBER(REGEXP_SUBSTR(TRIM(o.STAGE_NAME), '[0-9]+')) BETWEEN 2 AND 8
  AND COALESCE(o.NON_COMMISSIONABLE_C, FALSE) = FALSE
  AND COALESCE(f.BOOKING_ARR_C, 0) > 0
  AND COALESCE(ds.TOTAL_COMMISSIONABLE_ARR_C, 0) > 0
ORDER BY o.CLOSE_DATE, o.NAME
"""

df = query(SQL)
out = Path("/Users/justine.mendez/Library/CloudStorage/GoogleDrive-justine.mendez@zendesk.com/Shared drives/GTM Ops/APAC/AE Compass/salesforce_opportunities_current_quarter.csv")
df.to_csv(out, index=False)
print(f"wrote {out}: {len(df)} rows; total={float(df['BOOKING_ARR__C'].sum())}", flush=True)
