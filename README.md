# Jumbo Location Analyzer

Streamlit application for screening, comparing and managing potential Jumbo retail locations.

## Current build

**2026-10-04-v10.2**

## What the app does

- geocodes candidate locations;
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
3. Review demand, access and competitive context.
4. Enter commercial assumptions.
5. Save the project and compare it with other candidate sites.
6. Move the project through the appropriate decision stage.

## Run locally

Prerequisite: install `uv`.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run streamlit run streamlit_app.py
```

## Quality checks

The repository includes a Streamlit smoke test and a GitHub Actions check that compiles the application and verifies that the core Project Workspace renders successfully.

## Deployment

1. Deploy this GitHub repository to Streamlit.
2. Set the entrypoint to `streamlit_app.py`.
3. Keep credentials and API secrets in deployment secrets/environment variables rather than source control.
4. Validate live geocoding, retail/access providers, project save/load, comparison and economics before sharing the public app link.

## Sharing

For end users, share the deployed Streamlit application URL rather than the GitHub repository URL.
