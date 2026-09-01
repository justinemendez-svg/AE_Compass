# AE Compass — Local Playground

## AppFoundry data bundle

Run `python3 server/refresh_appfoundry_data.py` (or `npm run refresh-data`) to
create `AE_Compass_AppFoundry_Data.zip` in the shared AE Compass folder. This
is the lightweight upload package: it contains slim Workday, GTMI, Salesforce,
and Clari CSVs plus a manifest. Use `npm run refresh-data-live` when the live
Salesforce/Snowflake SSO pull is available. Raw Gong calls and transcripts are
not included in the bundle.

This is a **local, standalone copy** of the AE Compass dashboard. The UI runs
against a local, read-only cache of the verified Workday, Clari, GTMI, and
Salesforce extracts in the shared AE Compass folder. It does not write to
Salesforce, Snowflake, GitHub, or any other repository.

## What's different from the original

The local server (`server/mock_server.py`) reads the compact Workday and GTMI
exports plus the Salesforce opportunity export. Clari supplies quota/forecast;
Salesforce supplies total signed and total open pipeline; GTMI supplies the AI
and New Business product views. A deterministic sample generator remains only
as a fallback when the Workday/GTMI files are unavailable.

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

- Refresh the source files manually with `npm run refresh-data-live` when
  Snowflake access is available, or use `npm run refresh-data` to rebuild the
  compressed AppFoundry bundle from the current shared-folder exports.
- Your edits in the UI (coaching notes, action items, competency scores, weekly
  tracker, deal maps, quotas) persist to `server/mock_state.json`. Delete that
  file to reset to a clean slate.
- The Admin CSV upload screen stores local uploads for the prototype; production
  AppFoundry should use the generated ZIP bundle and its manifest.
