# Location map fit — 2026-11-17

## Coordination

- Base: `main` at `0857bca5b139cccbb7395ea6b55ab6be735bca57`.
- Reviewed current source, README, recent commits, remote branches and open draft
  PRs #29–38 before editing.
- This change does not duplicate the open work on currencies, catchments,
  project import/save, commercial validation, Golden Spot names or the Karavan
  baseline.

## Confirmed defect

The site-and-nearby-retail map used a fixed initial zoom and did not ask the
existing map component to fit its collected points. A direct competitor or
retail anchor returned near the edge of the supported 3 km scan could therefore
start outside the visible viewport even though it was part of the map data.

## Change

The existing light Leaflet map now fits the target site and all scanned map
points after the component becomes visible. The target marker remains selected,
and the existing layer and maximum-zoom rules remain unchanged. No provider,
scoring, financial or persistence behavior changed.

## Verification

- The new AppTest failed on unchanged `main` because the location map call had
  no `fit` flag.
- Targeted regression: 1 passed.
- Full test suite: 103 passed.
- `uv lock --check --offline`: passed.
- Python compilation: passed.
- Streamlit headless smoke start: passed (server reached its local ready URL).
- `git diff --check`: passed.

The only test warning is the dependency warning from `anyio` about a future
pytest 10 compatibility change.

## Supabase availability — 2026-11-17 15:59 EET

- Project `rixvdctqqbmobfvazxay`: `ACTIVE_HEALTHY`.
- Minimal read-only `SELECT 1`: succeeded.
- Existing publishable Data API path with `select=revision&limit=0`: HTTP 401;
  no response body or project row was read. An authorized application user
  session was not available in this isolated test process.
- No database data, permissions, keys, plan, pricing or schedules were changed.

A successful SQL health check does not guarantee that automatic project pause
has been disabled.

## Next

Review and merge order remain owner decisions. Do not merge or deploy this
branch automatically.
