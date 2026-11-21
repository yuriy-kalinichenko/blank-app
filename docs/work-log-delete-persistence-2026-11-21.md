# Work log · rollback a failed project deletion

Date: 2026-11-21

## Base and coordination

- fresh `main` checkout at `0857bca5b139cccbb7395ea6b55ab6be735bca57`;
- reviewed the current source, recent commits, remote branches and open draft
  pull requests #29–40;
- this change does not duplicate the pending import, currency, catchment,
  Golden Spot, map-fit, commercial-validation or create-name-collision work;
- implementation branch: `fix/delete-persistence-rollback-20261121`.

## Confirmed defect

When durable project-library storage rejected a deletion, the app had already
removed the project from the open session. It swallowed the storage error,
continued into the success path and attempted to reset widgets after they had
been instantiated. The synthetic cloud regression reproduced both the missing
session project and a Streamlit widget-state exception, while the remote test
library correctly remained unchanged.

## Change

- Snapshot the in-session library immediately before a confirmed deletion.
- If persistence fails, restore that exact library, keep the project active,
  show that it was not deleted and leave the confirmation available for retry.
- Enter the existing new-project reset path only after durable deletion
  succeeds, on the next rerun before widgets are created.
- No create, rename, import or ordinary save behavior changed.

## Verification

- The new regression fails on unchanged `main` and passes after the fix.
- It verifies that a failed deletion changes neither the synthetic remote
  library nor the session copy, then retries successfully after storage returns.
- Full suite: `103 passed` on Python 3.14.10.
- `uv lock --check --offline`, Python compilation, Streamlit headless startup
  and `git diff --check` passed.
- The only test warning is the existing `anyio` compatibility notice for a
  future pytest 10 release.
- No real project row, account, permission, key, tariff or schedule was changed.

## Supabase availability

Checked at 2026-11-21 16:01 EET:

- project `rixvdctqqbmobfvazxay`: `ACTIVE_HEALTHY`;
- minimal read-only `SELECT 1`: successful;
- the existing publishable Data API path was requested with
  `select=revision&limit=0` and returned HTTP 401; no authenticated application
  session was available and no project rows or response body were read.

The successful SQL health check confirms current reachability only; it does not
guarantee that automatic pausing is disabled.

## Next step

Review the draft pull request and choose a merge order with the other open
project-storage changes. Rebase and repeat the full suite before any merge.
Do not publish automatically.
