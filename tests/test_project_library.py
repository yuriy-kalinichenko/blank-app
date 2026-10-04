import json

from project_library import export_project_library, validate_project_library


def test_project_library_round_trip_preserves_projects():
    projects = {
        "Kyiv / Karavan - Base": {
            "location": "Karavan Mall, Kyiv",
            "currency": "EUR",
            "area": 4500.0,
            "rent": 5.0,
            "capex": 2500000.0,
            "annual_sales": 5000000.0,
            "gross_margin": 50.0,
            "payroll": 250000.0,
            "utilities": 12000.0,
            "logistics": 20000.0,
            "other_opex": 100000.0,
            "stage": "Due diligence",
            "schema_version": 2,
        },
        "Kyiv / River Mall": {
            "location": "River Mall, Kyiv",
            "currency": "EUR",
            "area": 3800.0,
            "rent": 7.5,
            "capex": 2200000.0,
            "annual_sales": 4600000.0,
            "gross_margin": 49.0,
            "payroll": 235000.0,
            "utilities": 110000.0,
            "logistics": 180000.0,
            "other_opex": 90000.0,
            "stage": "Screening",
            "schema_version": 2,
        },
    }

    exported = export_project_library(
        projects,
        build_version="2026-10-04-v1.0-rc1",
        exported_at="2026-10-04T13:45:00+00:00",
    )
    payload = json.loads(exported)
    imported = validate_project_library(payload)

    assert imported == projects
    assert payload["schema_version"] == 1
    assert payload["app"] == "Jumbo Location Analyzer"
    assert payload["build"] == "2026-10-04-v1.0-rc1"


def test_invalid_stage_is_safely_normalized():
    payload = {
        "projects": {
            "Test": {
                "location": "Kyiv",
                "stage": "Unknown stage",
            }
        }
    }

    imported = validate_project_library(payload)

    assert imported["Test"]["stage"] == "Screening"
    assert imported["Test"]["schema_version"] == 2
