# Golden Spot: provider whitespace names

Date: 2026-11-08

## Result

- Base: `main` at `0857bca5b139cccbb7395ea6b55ab6be735bca57`.
- Confirmed defect: a provider name containing only whitespace was treated as a real venue name. This could leave a Golden Spot candidate with an empty-looking label instead of the explicit unnamed OSM identity label.
- Fix: trim provider names before deciding whether they are present. A whitespace-only eligible mapped venue now receives the existing `Unnamed mapped … (OSM …)` label; non-venue rows remain rejected.
- Regression coverage includes padded real names, whitespace-only eligible venues, and whitespace-only non-venue rows.

## Coordination

Open pull requests were reviewed before starting. PRs #29–#33 cover currency-safe comparisons, 10/20/30-minute catchments, JSON import collisions, XLSX percentage import, and invalid commercial values. This change does not overlap those branches.

## Supabase availability check

Checked at `2026-11-08T13:18:03Z` for project `rixvdctqqbmobfvazxay` without modifying data, permissions, keys, billing, or schedules.

- Project status: `ACTIVE_HEALTHY`.
- Minimal SQL read: `SELECT 1 AS ok` succeeded.
- Existing Data API path: a zero-row request to `project_libraries` (`limit=0`) returned HTTP 401 and no project rows. The application-authorized Data API read path was therefore not available to this run.
- The successful SQL query only verifies current database reachability; it is not a guarantee that automatic pausing is disabled.

## Verification

- Reproduction test failed on the base behavior before the fix.
- Focused regression test passes after the fix.
- Full suite: `103 passed`.
- `uv lock --check --offline`, Python compilation, and `git diff --check` passed.

## Next step

Review and merge only after the draft PR checks are green. No deployment is part of this change.
