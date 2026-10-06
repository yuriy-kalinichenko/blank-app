"""User workflows with deterministic provider responses and isolated project storage."""

from pathlib import Path
import json

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app_test(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from project_library import default_project_library
    projects = default_project_library()
    projects["QA Second"] = {**next(iter(projects.values())), "location": "Tirana"}
    (tmp_path / "projects.json").write_text(json.dumps(projects))
    source = (ROOT / "streamlit_app.py").read_text()
    providers = '''
def geocode_location(query):
    if query == "Missing site":
        return None
    lat, lon = (41.328, 19.818) if query == "Tirana" else (50.5, 30.45)
    return {"lat": lat, "lon": lon, "display_name": query}

def fetch_retail_with_fallback(lat, lon, radius=3000):
    if lat < 45 or st.session_state.get("qa_retail_outage"):
        raise RuntimeError("Test retail provider unavailable")
    return [
        {"name": "Kyiv toy store", "lat": lat, "lon": lon, "shop": "toys"},
        {"name": "Kyiv parking", "lat": lat, "lon": lon, "amenity": "parking"},
    ], "Test retail provider", []

def fetch_access_with_fallback(lat, lon, radius=1500):
    if lat < 45 or st.session_state.get("qa_access_outage"):
        raise RuntimeError("Test access provider unavailable")
    return [{"name": "Kyiv road", "lat": lat, "lon": lon, "highway": "primary"}], "Test access provider", []

def fetch_drive_time_isochrones(*args, **kwargs):
    raise RuntimeError("Test routing provider unavailable")

def worldpop_population_geojson(*args, **kwargs):
    raise RuntimeError("Test population provider unavailable")

def worldpop_children_geojson(*args, **kwargs):
    raise RuntimeError("Test age provider unavailable")
'''
    marker = "for state_key, state_value in BASE_ECON_STATE.items():"
    source = source.replace(marker, providers + "\nSCENARIO_FILE = " + repr(str(tmp_path / "projects.json")) + "\n\n" + marker, 1)
    at = AppTest.from_string(source, default_timeout=15).run()
    assert not at.exception
    return at


def click(at, label):
    next(button for button in at.button if button.label == label).click().run()
    assert not at.exception


def analyze(at, query):
    at.text_input(key="location_query").set_value(query)
    click(at, "Analyze location")
    return at.session_state["analysis"]


def test_provider_failure_does_not_reuse_another_city(app_test):
    at = app_test
    assert analyze(at, "Kyiv")["retail"]
    result = analyze(at, "Tirana")
    assert result["geo"]["lat"] < 45
    assert result["retail"] == []
    assert result["access"] == []
    assert result["retail_error"]
    assert result["access_error"]


def test_provider_outage_is_not_reported_as_live(app_test):
    at = app_test
    analyze(at, "Kyiv")
    at.session_state["qa_retail_outage"] = True
    at.session_state["qa_access_outage"] = True
    result = analyze(at, "Kyiv")
    assert result["retail_error"]
    assert result["access_error"]


def test_failed_geocoding_clears_previous_analysis(app_test):
    at = app_test
    analyze(at, "Kyiv")
    at.text_input(key="location_query").set_value("Missing site")
    click(at, "Analyze location")
    assert any("Location not found" in error.value for error in at.error)
    assert "analysis" not in at.session_state or at.session_state["analysis"] is None


def test_selected_project_pipeline_save_preserves_economics(app_test):
    at = app_test
    name = "Karavan Mall, Kyiv - Base"
    at.selectbox(key="project_selector").select(name).run()
    before = dict(at.session_state["project_library"][name])
    click(at, "Save")
    assert at.session_state["project_library"][name]["annual_sales"] == before["annual_sales"]


def test_economics_matches_independent_baseline_and_fallbacks_are_labelled(app_test):
    at = app_test
    at.selectbox(key="project_selector").select("Karavan Mall, Kyiv - Base").run()
    analyze(at, "Karavan Mall, Kyiv")
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Annual rent"] == "€270,000"
    assert metrics["Estimated EBITDA"] == "€1,740,000"
    assert metrics["CAPEX payback"] == "1.4 years"
    assert metrics["15-min drive zone"] == "Proxy"
    assert metrics["15-min population"] == "—"
    assert len(at.tabs) == 6


def test_create_save_load_and_rename_project(app_test):
    at = app_test
    click(at, "＋ New project")
    at.text_input(key="project_name_input").set_value("QA Test Site")
    at.text_input(key="location_query").set_value("Kyiv")
    click(at, "Create project")
    assert at.session_state["active_project_name"] == "QA Test Site"
    at.text_input(key="project_next_action").set_value("Verify lease")
    click(at, "Save changes")
    at.text_input(key="project_name_input").set_value("QA Renamed Site")
    click(at, "Rename")
    click(at, "＋ New project")
    at.selectbox(key="project_selector").select("QA Renamed Site").run()
    assert not at.exception
    assert at.text_input(key="location_query").value == "Kyiv"
    assert at.text_input(key="project_next_action").value == "Verify lease"


def test_access_score_is_unknown_when_parking_source_is_missing(app_test):
    at = app_test
    at.session_state["qa_retail_outage"] = True
    analyze(at, "Kyiv")
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Access proxy score"] == "No data"
