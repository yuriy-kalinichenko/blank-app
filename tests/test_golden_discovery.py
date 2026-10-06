"""Regression coverage for real suburban malls omitted by city-name searches.

Fixture: Nominatim [mall], bounded 20 km around Tirana, retrieved 2026-10-06.
Data (c) OpenStreetMap contributors, ODbL; each fixture row retains its licence.
"""

import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def app():
    spec = importlib.util.spec_from_file_location("golden_app_test", ROOT / "streamlit_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def city():
    return {
        "lat": 41.3281482, "lon": 19.8184435, "display_name": "Tirana",
        "bbox": {"south": 41.2955352, "north": 41.3658530,
                 "west": 19.7547343, "east": 19.8764380},
    }


@pytest.fixture
def malls():
    return json.loads((ROOT / "tests/fixtures/tirana_malls.json").read_text())


def test_geographic_discovery_includes_suburban_malls_and_dedupes(app, city, malls, monkeypatch):
    monkeypatch.setattr(app, "geocode_location", lambda _: city)
    requests = []

    def search(request, timeout):
        params = parse_qs(urlparse(request.full_url).query)
        requests.append(params)
        west, north, east, south = map(float, params["viewbox"][0].split(","))
        assert params["bounded"] == ["1"]
        assert int(params["limit"][0]) <= 40
        # The requested area must contain both malls outside the city bbox.
        assert west < 19.7492368 < east
        assert south < 41.2831318 < north
        rows = malls if params["q"] == ["[mall]"] else []
        # A square bbox can also contain places beyond the circular radius.
        rows = rows + [{"name": "Far away mall", "lat": "41.49", "lon": "20.04", "type": "mall"}]
        return io.BytesIO(json.dumps(rows).encode())

    monkeypatch.setattr(app.urllib.request, "urlopen", search)
    found = app.search_large_retail_destinations("Tirana")
    names = [item["name"] for item in found]
    assert "TEG - Tirana East Gate" in names
    assert sum("QTU" in name for name in names) == 1
    assert sum("Ring Center" in name for name in names) == 1
    assert "Toptani Shopping Center" in names
    assert "Citypark" in names
    assert "Far away mall" not in names
    assert not any(name.startswith("Rruga ") for name in names)
    assert len(found) == 16
    assert all(item["kind"] == "mall" for item in found)
    # A new run must fetch discovery again, so transient misses are retryable.
    assert app.search_large_retail_destinations("Tirana") == found
    assert len(requests) == 4


def test_distinct_nearby_destinations_survive_deduplication(app):
    first = {"name": "Alpha Mall", "lat": 41.3, "lon": 19.8}
    second = {"name": "Beta Mall", "lat": 41.30001, "lon": 19.80001}
    assert not app.same_retail_destination(first, second)
    assert app.same_retail_destination(first, {**second, "name": "Alpha Shopping Centre"})
    assert not app.same_retail_destination(first, {**first, "lat": 41.4})


def test_discovery_inventory_survives_top_five_limit(app, city, malls, monkeypatch):
    monkeypatch.setattr(app, "geocode_location", lambda _: city)
    anchors = [{"name": item["name"], "lat": float(item["lat"]),
                "lon": float(item["lon"]), "kind": "mall"}
               for item in malls if item["name"]]
    monkeypatch.setattr(app, "search_large_retail_destinations", lambda _: anchors)
    monkeypatch.setattr(app, "search_retail_anchors", lambda *args, **kwargs: [])
    for name in ["fetch_golden_context", "fetch_nearby_retail", "fetch_access_context", "fetch_city_gravity_context"]:
        monkeypatch.setattr(app, name, lambda *args, **kwargs: [])
    shortlist, metadata = app.build_golden_spot_candidates("Tirana")
    assert len(shortlist) == 5
    inventory = metadata["discovered_anchors"]
    assert len(inventory) == 16
    assert any("TEG" in item["name"] for item in inventory)
    assert any("QTU" in item["name"] for item in inventory)
    assert "discovered_anchors" not in city  # Never mutate cached geocoding.
    assert app._SCREENING_NETWORK.get() is None


def test_network_budget_stops_repeated_enrichment_and_is_scoped(app, monkeypatch):
    calls = []
    clock = iter([0.0, 3.0, 4.0, 5.0])
    monkeypatch.setattr(app.time, "monotonic", lambda: next(clock))

    def response(request, timeout):
        calls.append(timeout)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(app.urllib.request, "urlopen", response)
    budget = {"overpass": 2.0, "map": 25.0, "limited": set()}
    token = app._SCREENING_NETWORK.set(budget)
    try:
        with app.screening_response("request", 10, "overpass") as result:
            assert result.read() == b"{}"
        with pytest.raises(TimeoutError):
            with app.screening_response("request", 10, "overpass"):
                pass
        assert calls == [2.0]
        assert budget["limited"] == {"overpass"}
    finally:
        app._SCREENING_NETWORK.reset(token)
    with app.screening_response("request", 10, "overpass"):
        pass
    assert calls == [2.0, 10]  # Full location analysis keeps its normal timeout.


def test_screening_context_resets_after_error(app, monkeypatch):
    def fail(*args):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(app, "_build_golden_spot_candidates", fail)
    with pytest.raises(RuntimeError):
        app.build_golden_spot_candidates("Tirana")
    assert app._SCREENING_NETWORK.get() is None
