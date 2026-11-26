# Work log — atomic local project save — 2026-11-26

## Confirmed defect

When Supabase is disabled, `persist_saved_scenarios` wrote directly to
`saved_scenarios.json`. An interrupted or failed write could therefore replace a
valid project library with a partial JSON document.

## Change

- Write the local fallback library to a temporary file in the destination
  directory.
- Flush and sync the complete JSON document before replacing the destination
  atomically.
- Remove the temporary file after any serialization or write failure.
- Keep the existing project library untouched when serialization does not
  complete.

## Verification

- `uv run pytest -q tests/test_local_storage.py`: 2 passed.
- `uv run pytest -q`: 104 passed.
- `uv lock --check`: passed.
- `python -m py_compile streamlit_app.py local_storage.py tests/test_local_storage.py`:
  passed.
- Headless Streamlit startup reached `Uvicorn server started` and was stopped
  after the smoke-test timeout.
- Supabase project `rixvdctqqbmobfvazxay` was `ACTIVE_HEALTHY` at
  2026-11-26 15:52 EET. Read-only `SELECT 1` succeeded. The public Data API
  check used `select=revision&limit=0` and returned HTTP 401 without a user
  session; no project rows were read or shown. This accessibility check is not
  a guarantee against automatic pausing.

## Next small task

Review the remaining save paths after the existing open persistence PRs are
resolved, avoiding overlap with their project import, creation, and deletion
work.
