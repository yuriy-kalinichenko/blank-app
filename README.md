# Jumbo Location Analyzer

Retail location intelligence, site-selection and investment-screening application for Jumbo expansion projects.

## Release candidate

**2026-10-04-v1.0-rc1**

This release candidate freezes the core product workflow. New large feature layers should be added only after the release-candidate workflow passes real-site validation.

## Core workflow

1. Create or select a project.
2. Enter a candidate site and run live location analysis.
3. Review real 15/30/40-minute drive-time catchments.
4. Review total population and children 0-18 inside the displayed catchments.
5. Review access, nearby retail and competitive context.
6. Enter commercial assumptions and review economics.
7. Save the project and compare it with other candidate sites.
8. Move the project through Screening, Due diligence, Negotiation, Approved, On hold or Rejected.

## Project Library

The Project Workspace supports New, Load and Save as the main workflow.

For durable portability, the **Project library · backup & transfer** section can:

- export all projects to a JSON backup;
- import that backup on another computer or after an app restart;
- merge imported projects into the current library;
- delete a selected project.

The local `saved_scenarios.json` file remains a convenience cache for the current app instance. The exported JSON library is the portable backup and recovery format and avoids relying on ephemeral cloud filesystem persistence.

## Location intelligence

- OpenStreetMap geocoding for candidate sites.
- Valhalla/OpenStreetMap road-network isochrones for **15 / 30 / 40 minute** car catchments.
- Clearly labelled 6/12/16 km fallback proxies if routing is unavailable.
- WorldPop 2025 total population inside the displayed catchment polygons.
- WorldPop age/sex population age 0-18 inside the same catchments.
- OpenStreetMap retail, competition, parking, roads and public-transport context.
- Provider fallbacks and diagnostics instead of fabricated values.

## Commercial screening

The economics module uses explicit user assumptions for area, rent, CAPEX, sales, gross margin, payroll, utilities, logistics and other OPEX. It calculates annual rent, gross profit, EBITDA, sales density, occupancy cost, EBITDA margin and payback.

Saved-project comparison uses only the assumptions stored in each project. The app does not create a hidden overall ranking.

## Methodology safeguards

- Real routing polygons are distinguished from fallback proxies.
- Population and children-demand figures use the same displayed catchment geometry.
- Missing provider data is shown as unavailable or needing retry rather than invented.
- Children 0-18 is a demographic demand indicator, not a family or household count.
- Commercial results are assumption-driven and are not presented as market forecasts.

## Quality gates

Every pull request and push to `main` checks:

- dependency-lock consistency with `uv lock --check`;
- Python compilation;
- Streamlit smoke-test startup;
- presence of the core Project Workspace workflow.

## Run locally

Prerequisite: install `uv`.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run streamlit run streamlit_app.py
```

## Deployment

1. Deploy the GitHub repository to Streamlit.
2. Use `streamlit_app.py` as the entrypoint.
3. Keep future credentials/API secrets in deployment secrets or environment variables.
4. Run the release checklist on multiple real candidate sites before external presentation.
5. Export the Project Library as a backup after important project updates.

## v1.0 release checklist

Before calling the release final:

- CI on the release candidate is green.
- New / Load / Save works for multiple projects.
- Project Library export/import round-trips successfully.
- At least three real candidate sites complete analysis without a crash.
- Live-routing and fallback states are both clearly labelled.
- Catchment population and children-demand values are shown for available zones.
- Economics and saved-project comparison remain consistent after save/load.
- The deployed Streamlit app opens cleanly from a fresh browser session.


## Golden Spot: Jumbo premises screening (v3)

Golden Spot separates **candidate sites**, **traffic generators**, and **background context** before ranking. Only named, mapped shopping centres / retail parks and explicitly typed shopping destinations can enter the shortlist. A generic retail building / land tag is insufficient: it may describe an occupied small business. Existing tenant businesses (including supermarkets, cafes and pharmacies) are factors, never candidate premises. A dense POI cluster does not create a synthetic site. Distinct nearby venues stay separate.

The transparent evidence score uses venue type (40), shopping / family traffic (20), road / transit proximity (25), and nearby parking (15). Small food/service POIs have capped influence. A single city map snapshot gives candidates the same context coverage. Distance from the city centre is descriptive, not a penalty for suburban destination malls. Equal scores use name and object identity for deterministic ordering.

These weights are screening heuristics, not calibrated sales or investment forecasts. Missing context remains unknown; it is never presented as zero demand. Mapped premises do not establish vacancy, leasable area, loading rights, rent, CAPEX, logistics cost or network cannibalisation. Those remain explicit due-diligence checks before opening a Jumbo. Search coverage is limited by public-map completeness.

Regression checks cover tenant/building tag conflicts, no-site searches, adjacent distinct malls, missing context, deterministic ordering and the TEG/QTU discovery fixture.
