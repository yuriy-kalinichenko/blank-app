# Karavan first-run utilities baseline — 2026-11-10

Base: `main` at `0857bca5b139cccbb7395ea6b55ab6be735bca57`.

## Confirmed defect

The first-run commercial state used 12,000 EUR/year for utilities, while the
saved Karavan baseline, recovery baseline and verified economics example all
use 120,000 EUR/year. Before a project was loaded, this understated annual
fixed OPEX by 108,000 EUR and overstated the displayed EBITDA by the same
amount.

## Change

The initial Karavan state now uses the same 120,000 EUR/year utilities value as
the saved baseline. Existing projects, uploaded files and cloud rows are not
rewritten; user-entered assumptions remain unchanged.

The regression runs the isolated Streamlit app and compares the first-run
utilities value with the saved synthetic Karavan project. It fails on `main`
with `12000.0 != 120000.0` and passes after the fix.

Verification on Python 3.14.10: the focused regression passed, the complete
suite passed (`103 passed`), `uv lock --check --offline`, Python compilation
and `git diff --check` passed. The `anyio` warning about the future pytest 10
alias appeared on both unchanged `main` and the branch; this change adds no new
test warning.

Open PRs #29–35 were reviewed before selecting this task. They cover currency
comparison, catchment intervals, backup collisions, XLSX percentage formats,
backup validation, Golden Spot names and duplicate project creation; this
change does not duplicate those tasks.

## Supabase read-only check

At 2026-11-10 15:54 Europe/Kyiv, project `rixvdctqqbmobfvazxay` reported
`ACTIVE_HEALTHY` and `SELECT 1` succeeded. The existing publishable Data API
path was called with `limit=0` and returned HTTP 401; no project rows were
requested or returned, and no authenticated app-user session was available.
No data, permissions, keys, billing settings or schedules were changed. A
successful SQL check does not guarantee that automatic pausing is disabled.

## Next

Review this focused draft PR alongside the existing commercial PRs before
choosing a merge order. Do not merge or deploy automatically.
