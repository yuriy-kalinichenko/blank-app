# Development work log

## 2026-10-30 — 10/20/30-minute catchment contract

- Base: `main` at `f8fb3862c23e7b0a680c8a6f1ed6a8069521b19d`.
- Branch: `fix/catchment-10-20-30-20261027` (the existing remote branch was identical to `main` and had no open pull request).
- Coordination: open draft PR #29 covers portfolio currency comparison; this change does not modify that area.
- Confirmed defect: the agreed catchment intervals are 10/20/30 minutes, while the application, fallback geometry, map colours, tests and documentation still used 15/30/40.
- Change: request and display 10/20/30-minute Valhalla contours; use clearly labelled 4/8/12 km fallback circles; keep population and children calculations on the displayed geometry; invalidate legacy analysis stored in a long-lived browser session; update regression coverage and release metadata.
- Data safety: no user projects, database rows, permissions, keys, tariffs or deployment settings were modified. Provider tests use deterministic isolated data.
- Supabase availability check at 2026-10-30 13:26 UTC:
  - project `rixvdctqqbmobfvazxay`: `ACTIVE_HEALTHY`;
  - read-only SQL `SELECT 1`: succeeded;
  - current application Data API path, using the configured publishable key and `limit=0`: HTTP 401 Unauthorized; no project contents were returned;
  - no authenticated app user session was available for a second Data API read check. This is a configuration/access blocker and no key or permission was changed. A successful SQL health query does not guarantee that automatic pausing is disabled.
- Verification: local Python compilation, static catchment-contract checks and `git diff --check` passed. GitHub Actions run 41063523010 then passed the Python 3.14 dependency-lock check, compilation and full test suite. The local runtime does not contain Python 3.14 or a cached Streamlit dependency, so CI is the authoritative full-suite result for this run.
- Next: perform human browser validation of live routing and fallback labels before merge or deployment. Investigate the Data API 401 through the authorized project configuration path without rotating keys or changing permissions in this branch.
