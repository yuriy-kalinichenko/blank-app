# Development work log

## 2026-11-05 — preserve same-name projects during JSON import

- Base: current GitHub `main` at `0857bca5b139cccbb7395ea6b55ab6be735bca57`.
- Branch: `fix/import-preserve-projects-20261105`.
- Coordination: draft PR #29 covers mixed-currency portfolio comparison and draft
  PR #30 covers 10/20/30-minute catchments. This change does not modify those
  calculations, map intervals or their branches.
- Confirmed defect: **Advanced · import / export** merged a JSON backup with
  `dict.update()`, so an imported project silently replaced an existing project
  with the same name. The guest-to-cloud transfer already preserved both records.
- Change: JSON import now uses the same deterministic merge rule. Identical records
  are skipped; a conflicting record is stored as `Name (import 1)`, then the next
  available suffix. Inputs are copied and are not mutated by the merge helper.
- Safety: tests use synthetic dictionaries and isolated Streamlit sessions. No real
  project library, database row, permission, key, tariff or deployment is changed.
- Supabase availability at 2026-11-05 13:49 UTC: project
  `rixvdctqqbmobfvazxay` reported `ACTIVE_HEALTHY`; read-only `SELECT 1` succeeded.
  The existing publishable Data API path requested zero rows and returned HTTP 401,
  so no user project content was returned. No authenticated app-user session was
  available and no key or permission was changed. SQL availability does not
  guarantee that automatic pausing is disabled.
- Next: review the draft PR and let CI run on the repository's required Python 3.14.
  Before any future deployment, retain the existing safeguard to confirm a durable
  Tirana backup or authenticated transfer.
