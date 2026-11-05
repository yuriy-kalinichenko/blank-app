import json
from copy import deepcopy
from datetime import datetime, timezone


PROJECT_LIBRARY_SCHEMA = 1
ALLOWED_STAGES = {
    "Screening",
    "Due diligence",
    "Negotiation",
    "Approval",
    "Implementation",
    "Open",
    "On hold",
    "Cancelled",
}

LEGACY_STAGE_MAP = {
    "Approved": "Approval",
    "Rejected": "Cancelled",
}


def default_project_library():
    return {
        "Karavan Mall, Kyiv - Base": {
            "location": "Karavan Mall, Kyiv",
            "currency": "EUR",
            "area": 4500.0,
            "rent": 5.0,
            "capex": 2500000.0,
            "annual_sales": 5000000.0,
            "gross_margin": 50.0,
            "payroll": 250000.0,
            "utilities": 120000.0,
            "logistics": 20000.0,
            "other_opex": 100000.0,
            "stage": "Screening",
            "next_action": "",
            "owner": "",
            "deadline": "",
            "schema_version": 2,
        }
    }


def validate_project_library(payload):
    """Validate and normalize an imported project library."""
    if not isinstance(payload, dict):
        raise ValueError("Project library must be a JSON object.")

    raw_projects = payload.get("projects") if "projects" in payload else payload
    if not isinstance(raw_projects, dict):
        raise ValueError("The JSON file does not contain a valid projects object.")

    normalized = {}
    for raw_name, raw_project in raw_projects.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_project, dict):
            continue

        project = dict(raw_project)
        location = project.get("location")
        if location is not None and not isinstance(location, str):
            raise ValueError(f"Project '{name}' has an invalid location value.")

        stage = project.get("stage", "Screening")
        stage = LEGACY_STAGE_MAP.get(stage, stage)
        project["stage"] = stage if stage in ALLOWED_STAGES else "Screening"
        project["schema_version"] = int(project.get("schema_version") or 2)
        normalized[name] = project

    if not normalized:
        raise ValueError("No valid projects were found in the JSON file.")
    return normalized


def merge_project_libraries(existing, imported):
    """Merge a backup without overwriting an existing same-name project."""
    merged = deepcopy(existing)
    imported_names = []
    for name, project in imported.items():
        if name not in merged:
            target = name
        elif merged[name] == project:
            continue
        else:
            suffix = 1
            target = f"{name} (import {suffix})"
            while target in merged:
                suffix += 1
                target = f"{name} (import {suffix})"
        merged[target] = deepcopy(project)
        imported_names.append(target)
    return merged, imported_names


def export_project_library(data, build_version, exported_at=None):
    """Serialize the portable project-library backup format."""
    if exported_at is None:
        exported_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "schema_version": PROJECT_LIBRARY_SCHEMA,
        "app": "Jumbo Location Analyzer",
        "build": build_version,
        "exported_at": exported_at,
        "projects": data,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
