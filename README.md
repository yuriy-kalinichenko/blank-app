# Jumbo Location Analyzer

Streamlit application for screening, comparing and managing potential Jumbo retail locations.

## Current build

**2026-10-04-v11.0**

## What the app does

- geocodes candidate locations;
- calculates real **15 / 30 / 40 minute car drive-time isochrones** with Valhalla routing;
- falls back to clearly labelled distance proxies when the routing provider is unavailable;
- analyzes nearby retail, competition, parking and access context from OpenStreetMap;
- estimates catchment population with explicit source/method transparency;
- uses multiple provider fallbacks for better resilience;
- manages complete site projects through a compact Project Workspace;
- tracks project lifecycle stage from screening through approval/rejection;
- compares saved projects on commercial assumptions such as sales, EBITDA margin and payback;
- supports commercial scenario analysis and methodology diagnostics.

## Product workflow

1. Create or select a project.
2. Enter the candidate site and run live location analysis.
3. Review the 15/30/40-minute drive-time catchments.
4. Review demand, access and competitive context.
5. Enter commercial assumptions.
6. Save the project and compare it with other candidate sites.
7. Move the project through the appropriate decision stage.

## Drive-time methodology

The live drive-time layer uses the Valhalla road-network isochrone service with OpenStreetMap routing data. The public FOSSGIS Valhalla service is used under fair-use and the app sends an identifying client header.

If the live routing service is unavailable, the app shows an explicit fallback proxy instead of presenting a circular radius as a real drive-time zone.

The current WorldPop population layer remains a separate provisional radius-based proxy. A later build should calculate population directly inside the live drive-time polygons.

## Run locally

Prerequisite: install `uv`.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run streamlit run streamlit_app.py
```

## Quality checks

The repository includes:
- a Streamlit smoke test;
- Python compile validation;
- `uv.lock` consistency validation;
- GitHub Actions checks on pull requests and pushes to `main`.

## Deployment

1. Deploy this GitHub repository to Streamlit.
2. Set the entrypoint to `streamlit_app.py`.
3. Keep credentials and API secrets in deployment secrets/environment variables rather than source control.
4. Validate live geocoding, drive-time routing, retail/access providers, project save/load, comparison and economics before sharing the public app link.

## Sharing

For end users, share the deployed Streamlit application URL rather than the GitHub repository URL.
