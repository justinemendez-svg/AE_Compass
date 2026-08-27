"""Quarter-label normalization for the different Compass data sources.

Compass uses Zendesk's fiscal calendar internally: fiscal years start in
February, so FY2027Q1 is Feb-Apr 2026 and FY2027Q3 is Aug-Oct 2026.
"""

import datetime
import re


def fiscal_quarter_from_date(value) -> str:
    """Convert a Salesforce Closed Date into the Compass FY label."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    parsed = None
    # Salesforce exports are commonly ISO dates, timestamps, or US dates.
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.date.fromisoformat(candidate)
            break
        except ValueError:
            pass
    if parsed is None:
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%Y/%m/%d"):
            try:
                parsed = datetime.datetime.strptime(text, fmt).date()
                break
            except ValueError:
                pass
    if parsed is None:
        return ""
    fiscal_year = parsed.year + 1 if parsed.month >= 2 else parsed.year
    quarter = ((parsed.month - 2) % 12) // 3 + 1
    return f"FY{fiscal_year}Q{quarter}"


def normalize_fiscal_quarter(value) -> str:
    """Normalize Clari, GTMSI, or Salesforce quarter text to FYyyyyQn."""
    if value is None:
        return ""
    text = str(value).strip().upper().replace(" ", "").replace("-", "")
    if not text:
        return ""
    match = re.search(r"(?:FY)?(20\d{2})[_]?Q([1-4])", text)
    if match:
        return f"FY{match.group(1)}Q{match.group(2)}"
    return ""


def canonical_quarter(value=None, closed_date=None) -> str:
    """Prefer an explicit source quarter, otherwise derive it from Closed Date."""
    return normalize_fiscal_quarter(value) or fiscal_quarter_from_date(closed_date)

