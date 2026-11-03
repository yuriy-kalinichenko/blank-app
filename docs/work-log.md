# Jumbo Location Analyzer — development log

## 2026-10-17 — currency-safe portfolio comparison

Base: current GitHub `main`, `f8fb3862c23e7b0a680c8a6f1ed6a8069521b19d`.
Working branch: `fix/portfolio-currency-comparison-20261017`.

Coordination: read current main code, README, recent commit messages, open PRs
and branch heads. The only open PR at inspection was dependency update #18.
Reviewed `backup/tbilisi-evidence-2026-10-16` and its validation log; its evidence,
demographics and logistics work is preserved and not duplicated. The old
`portfolio-comparison` branch has no open PR and its commits date to October 5;
its comparison feature is already present in main. No active same-task change
was identified from these remote sources.

Confirmed defect: portfolio priority used nominal sales density as a tie-breaker
across currencies, and the EBITDA chart plotted their amounts on one unlabeled
scale. A synthetic EUR/UAH equivalent-return test failed on main: changing only
nominal money units changed the leading project.

Implemented:
- Exclude nominal sales density from priority when saved currencies differ.
  Positive EBITDA, payback and EBITDA margin remain in use; ties stay stable.
- Preserve the existing density tie-breaker for a single currency.
- Split EBITDA chart data by currency, label each scale and explicitly disclose
  that amounts are not FX-converted. No exchange rate is fetched or invented.
- Keep project assumptions and original currency amounts unchanged.

Verified locally on isolated test data:
- `uv run --offline --with pytest python -m pytest -q tests`: 85 passed,
  including seven new portfolio checks and Streamlit AppTest rendering for both
  one-currency and mixed-currency portfolios.
- `uv lock --check --offline`: passed.
- Python compilation and `git diff --check`: passed.
- Test fixtures disable cloud storage and use temporary directories; no real
  project library, account, database, policy, tariff or deployment is changed.

Remaining: obtain human review of the draft PR and GitHub CI. No merge or
deployment is requested by this change. Keep the prior publication safeguard:
confirm a durable Tirana backup/authenticated transfer before any restart or
deployment. The Tbilisi branch is a separate change requiring separate review.
Future catchment interval work (10/20/30 minutes) is not implemented here;
current main's 15/30/40-minute model and evidence remain unchanged.
