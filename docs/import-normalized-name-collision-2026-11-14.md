# 2026-11-14 — normalized backup names cannot overwrite each other

## Base and coordination

- Base: `main` at `0857bca5b139cccbb7395ea6b55ab6be735bca57`.
- Reviewed the current source, README, recent commits, remote branches and open
  draft PRs #29–36 before choosing the task.
- Existing PRs already cover currency comparison, 10/20/30-minute catchments,
  merging imports with the current library, XLSX percentages, commercial-value
  validation, Golden Spot names, duplicate interactive project creation and the
  Karavan utilities baseline. This change does not duplicate those tasks.

## Confirmed defect

A single JSON backup could contain both `Kyiv Site` and ` Kyiv Site `. Import
normalizes both keys with `strip()`, so the second record silently replaced the
first inside the validated dictionary. The regression reproduced this data loss
on unchanged `main`.

## Change

Validation now rejects a backup when two project names collide after trimming.
No project is selected, merged or written before this validation completes. The
user can rename the ambiguous entries in the backup and retry deliberately.

## Verification

Tests use only synthetic project dictionaries. Run before opening the draft PR:

- targeted regression;
- complete pytest suite;
- `uv lock --check --offline`;
- Python compilation;
- `git diff --check`.

No production database rows, user projects, access policies, keys, plans or
schedules were changed.

## Supabase availability — 2026-11-14 15:47 Europe/Kyiv

- Project `rixvdctqqbmobfvazxay`: `ACTIVE_HEALTHY`.
- Minimal read-only `SELECT 1`: succeeded.
- Existing publishable Data API path with `limit=0`: HTTP 401 without reading
  project rows; no authorized application user session is available in this
  test process.
- A successful SQL connectivity check does not guarantee that automatic pause
  will never occur.

## Next

Review and merge only after ordering this draft with the existing import PRs,
especially #31 and #33. Do not publish automatically.
