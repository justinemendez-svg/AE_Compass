# AE Compass — Local Playground

## AppFoundry data bundle

Run `python3 server/refresh_appfoundry_data.py` (or `npm run refresh-data`) to
create `AE_Compass_AppFoundry_Data.zip` in the shared AE Compass folder. This
is the lightweight upload package: it contains slim Workday, GTMI, Salesforce,
and Clari CSVs plus a manifest. Use `npm run refresh-data-live` when the live
Salesforce/Snowflake SSO pull is available. Raw Gong calls and transcripts are
not included in the bundle.

This is a **local, standalone copy** of the AE Compass dashboard for tinkering.
It is **not** connected to GitHub, the real PostgreSQL database, or Snowflake.

## What's different from the original

The real app needs Flask + PostgreSQL + Snowflake (over corporate Okta SSO).
This copy swaps that entire data layer for a **zero-dependency mock server**
(`server/mock_server.py`) that generates realistic **fake** data — 125 made-up
AEs, a full SVP→RVP→Director→Manager→AE hierarchy, and pipeline/bookings across
FY27 Q1–Q4. The React frontend is completely unchanged.

No Postgres install, no pip packages, no network, no SSO. Just Node + Python 3.

## Run it

```bash
./run-local.sh
```

Then open **http://localhost:5173**. Ctrl-C stops both servers.

Or start the two pieces manually in separate terminals:

```bash
# Terminal 1 — mock data server
PORT=8080 python3 server/mock_server.py

# Terminal 2 — frontend
npm run dev
```

## Notes

- **All numbers are fake and deterministic** (seeded), so they're stable across
  restarts. They mean nothing.
- Your edits in the UI (coaching notes, action items, competency scores, weekly
  tracker, deal maps, quotas) persist to `server/mock_state.json`. Delete that
  file to reset to a clean slate.
- The Admin CSV upload screen "succeeds" but is a no-op — the mock server ignores
  uploads and always serves its generated data.
- Want to change the data? Edit `make_generator()` in `server/mock_server.py`
  (org size, deal counts, amounts, products) and restart the server.
