# Work log · reject incomplete project backups

Date: 2026-11-18

## Confirmed defect

`validate_project_library` silently skipped a project whose backup record was not
a JSON object. A file containing one valid project and one damaged project was
therefore reported as a successful partial import, which is unsafe for project
recovery.

## Change

- Reject the entire backup when any project has an empty name or a non-object
  record.
- Include the affected project name in the non-object validation error.
- Keep the current all-or-nothing import flow: validation finishes before the
  session library or cloud library is changed.

## Verification

- Reproduced on unchanged `main`: the regression test failed because the damaged
  record was silently skipped.
- Targeted and full automated checks are recorded in the pull request.
- No real project library, database row, permission, key, plan, or schedule was
  changed.

## Supabase availability check

Checked at 2026-11-18 13:48 EET:

- project `rixvdctqqbmobfvazxay`: `ACTIVE_HEALTHY`;
- read-only `SELECT 1`: successful;
- existing publishable Data API request using `select=revision&limit=0`: HTTP 401;
  no project rows or response body were read, and no authenticated app session
  was available in this test process.

The successful SQL health check does not guarantee that automatic pausing is
disabled.

## Next step

Review the draft pull request and reconcile it with the other open import PRs
before merge. Do not publish automatically.
