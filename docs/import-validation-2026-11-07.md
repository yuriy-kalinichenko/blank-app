# Jumbo development log — 2026-11-07

## Result

JSON project-library imports now validate every commercial number before the
library can be merged or loaded. Invalid text, booleans, non-finite numbers,
negative values and a gross margin above 100% are rejected with the project and
field named in the error. Valid numeric strings remain compatible and are
normalized to finite floats.

The defect was reproduced on `main` at
`0857bca5b139cccbb7395ea6b55ab6be735bca57`: an invalid commercial value passed
`validate_project_library` and later failed in project loading or portfolio
calculation when the app converted it with `float(...)`.

This task is separate from draft PR #31, which prevents same-name records from
overwriting each other. It does not change merge naming, cloud storage, real
projects, permissions, keys, tariffs or deployment.

## Verification

- Synthetic validator regressions cover invalid text, `NaN`, negative values,
  out-of-range margin and booleans.
- A compatibility regression covers valid numeric strings.
- The complete Python test suite, lock check, compilation and diff check are
  required before the draft PR is opened.

## Supabase availability

At `2026-11-07T13:53:49Z`, project `rixvdctqqbmobfvazxay` accepted a read-only
`SELECT 1`. The existing publishable Data API path was requested with
`limit=0` and returned HTTP 401 without returning project rows. No database
data, permission, key, tariff or schedule was changed. The successful SQL
query does not guarantee that automatic pausing is disabled.

## Next step

Review this draft independently from PR #31. After the outstanding import,
currency, catchment and XLSX PRs are resolved, rebase and rerun the complete
suite before any merge. Do not deploy automatically.
