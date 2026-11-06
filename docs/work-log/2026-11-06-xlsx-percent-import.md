# 2026-11-06 · XLSX percentage import

## Confirmed defect

Excel stores a cell displayed as `50%` as the numeric value `0.5` plus a percentage number format. The commercial importer read only the numeric value, so an uploaded 50% gross margin became 0.5% and distorted EBITDA and payback.

## Change

- detect built-in and custom percentage number formats in the XLSX style table;
- convert only numeric cells using those styles to percentage points;
- keep CSV values and non-percentage XLSX cells unchanged;
- cover both Excel built-in `0.00%` and custom percentage formats with a synthetic workbook.

## Safety and next step

Tests use generated files and isolated Streamlit state. No user project, Supabase row, permission, key, tariff or deployment is changed. Review the draft PR and CI; do not merge or deploy automatically. After the pending project-import, currency-comparison and catchment PRs are resolved, rebase this branch and repeat the full suite.

## Verification

- Python 3.14: `104 passed`;
- focused synthetic XLSX checks: `2 passed`;
- `uv lock --check --offline`, Python compilation and `git diff --check`: passed;
- Supabase availability at 2026-11-06 13:29 UTC: project `ACTIVE_HEALTHY`, read-only `SELECT 1` succeeded;
- existing publishable Data API path with `limit=0`: HTTP 401, with no project rows requested or returned. No app-user session was available and no key or permission was changed.

A successful SQL health query does not guarantee that automatic pausing is disabled.
