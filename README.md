# Jumbo Location Analyzer

Streamlit application for screening and comparing potential Jumbo retail locations.

## What the app does

- geocodes candidate locations;
- analyzes nearby retail, parking and access context from OpenStreetMap;
- uses multiple provider fallbacks for better resilience;
- supports location comparison and economic scenario analysis;
- exposes methodology and diagnostics inside the app.

Current app build: **2026-10-04-v10.0**

## Run locally

Prerequisite: install `uv`.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run streamlit run streamlit_app.py
```

## Main application file

`streamlit_app.py`

## Deployment checklist

1. Push the target branch to GitHub.
2. Create a Streamlit deployment using this repository.
3. Set the entrypoint to `streamlit_app.py`.
4. Add any required secrets in the deployment settings rather than committing them to GitHub.
5. Test geocoding, retail/access lookups, comparison views and economics before sharing the public link.

## Sharing

Once deployed, share the Streamlit app URL rather than the GitHub repository URL with end users.
