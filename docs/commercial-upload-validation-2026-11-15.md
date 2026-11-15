# Jumbo Location Analyzer — commercial upload validation

## 2026-11-15

Base: GitHub `main` at `0857bca5b139cccbb7395ea6b55ab6be735bca57`.
Working branch: `fix/commercial-upload-value-validation-20261115`.

### Coordination

Freshly cloned the repository and reviewed the current code, README, remote
branches and open pull requests. Draft PRs #29–37 already cover currency-safe
portfolio comparison, 10/20/30-minute catchments, backup collisions and
validation, XLSX percentages, Golden Spot names, duplicate project creation and
the Karavan utilities baseline. This change is limited to invalid values in the
separate commercial CSV/XLSX upload path.

### Confirmed defect

On unchanged `main`, synthetic commercial-file rows were accepted as:

- `Store area = NaN`;
- `CAPEX = -250000`;
- `Gross margin = 125`.

Invalid text in one recognized field could also be silently omitted while other
fields were applied. These values can make economics incorrect or break the
next numeric-input render.

### Change

Commercial CSV/XLSX parsing now rejects non-numeric/non-finite values, negative
financial inputs and gross margin outside 0–100 before anything is copied into
the current Streamlit session. Valid localized numbers and percentage text keep
their existing behavior. No saved project, cloud row or access rule is changed.

### Verification

- Regression on unchanged `main`: 4 expected failures, 1 valid-value check passed.
- Focused synthetic suite after the fix: 5 passed.
- Full Python 3.14.10 suite: 107 passed.
- `uv lock --check --offline`, Python compilation and `git diff --check`: passed.
- Streamlit headless smoke start reached the local server successfully.
- The suite emitted one dependency warning from `anyio` about future pytest 10
  compatibility; there were no test failures.

### Supabase availability — 2026-11-15 15:13 EET

- project `rixvdctqqbmobfvazxay`: `ACTIVE_HEALTHY`;
- minimal read-only `SELECT 1`: succeeded;
- existing publishable Data API request with `limit=0`: HTTP 401; no project rows
  were requested or read, and no authenticated app-user session was available;
- data, permissions, keys, tariff and schedules were not changed.

The successful SQL check confirms current reachability only; it does not
guarantee that automatic pausing is disabled.

### Next step

Complete local checks, publish this isolated branch and open one draft PR for
review. Do not merge or deploy automatically.
