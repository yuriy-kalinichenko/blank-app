# Pipeline save rollback — 2026-11-27

## Coordination

- Started from fresh `main` commit `0857bca5b139cccbb7395ea6b55ab6be735bca57`.
- Reviewed the current source, remote branches and open pull requests #18 and
  #29–#42 before changing code.
- This change does not duplicate #41: that draft protects project deletion,
  while this work protects the separate Portfolio → Project pipeline metadata
  save path.
- No merge or deployment was performed.

## Confirmed defect

The pipeline Save handler mutated the project dictionary and session library
before durable persistence. A local `OSError` was ignored and the UI continued
with a success message. A cloud `CloudError` could escape after the session
object was already changed. In either case the browser could show workflow
metadata that was not stored, which made the project appear saved until reload.

The new regression failed on unmodified `main`: after a synthetic storage
outage, stage, next action, owner and deadline were present in session state
even though persistence failed.

## Change

- Build an updated project and project library without mutating the active
  session object.
- Persist that candidate library first.
- Commit it to session state and show success only after persistence succeeds.
- On local or cloud failure, keep the existing project unchanged and show an
  explicit retry / backup error.

## Verification

All checks use temporary files, synthetic projects and a fake cloud client.
No real project library or database row was read or changed.

- targeted local and cloud persistence regressions: `2 passed`;
- full suite: `104 passed`;
- `uv lock --check`: passed;
- Python compilation of affected application and test modules: passed;
- `git diff --check`: passed;
- headless Streamlit startup: server started and stopped normally after the
  bounded timeout.

The existing `anyio` warning about the pytest 10 `CallSpec2` rename remains;
it is unrelated to this change.

## Supabase availability — 2026-11-27 15:50 EET

- project `rixvdctqqbmobfvazxay`: `ACTIVE_HEALTHY`;
- minimal read-only `SELECT 1`: succeeded;
- the existing publishable Data API path was checked with
  `select=revision&limit=0`; without an app-user session it returned HTTP 401;
- no project rows or response body were read or printed;
- no data, permissions, keys, tariff or schedule changed.

The successful SQL query confirms availability only at the check time and does
not guarantee that automatic pausing is disabled.

## Remaining

Review the draft pull request and coordinate it with the other open persistence
changes before merge. Rebase and rerun the complete suite if `main` changes.
Do not merge or deploy automatically.
