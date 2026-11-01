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


@pytest.mark.parametrize("payload", [{"elements": []}, {"elements": None},
                                     {"elements": [{"type": "way", "id": 1}]}])
def test_empty_or_unusable_overpass_context_uses_map_fallback(app, city, monkeypatch, payload):
    monkeypatch.setattr(app, "run_overpass_query", lambda _: payload)
    candidates = [{"name": "Tirana mall", "lat": city["lat"], "lon": city["lon"]}]
    expected = [{"name": "Nearby parking", "lat": city["lat"], "lon": city["lon"],
                 "amenity": "parking"}]
    calls = []
    def fallback(sites, loader):
        calls.append(sites)
        return expected
    monkeypatch.setattr(app, "map_context", fallback)
    assert app.fetch_golden_context(city["lat"], city["lon"], candidates) == expected
    assert calls == [candidates]


def test_empty_context_from_both_providers_is_not_success(app, city, monkeypatch):
    monkeypatch.setattr(app, "run_overpass_query", lambda _: {"elements": []})
    monkeypatch.setattr(app, "map_context", lambda *args: [])
    with pytest.raises(RuntimeError, match="no usable surrounding-map objects"):
        app.fetch_golden_context(city["lat"], city["lon"], [{"name": "Mall"}])


def test_screening_tries_healthy_mirror_before_retrying_slow_host(app, monkeypatch):
    calls = []
    elapsed = [0.0]
    monkeypatch.setattr(app.time, "monotonic", lambda: elapsed[0])

    def response(request, timeout):
        calls.append((urlparse(request.full_url).netloc, request.method, timeout))
        if len(calls) <= 2:
            elapsed[0] += timeout
            raise TimeoutError("provider timed out")
        return io.BytesIO(b'{"elements": [{"type": "node", "id": 1}]}')

    monkeypatch.setattr(app.urllib.request, "urlopen", response)
    token = app._SCREENING_NETWORK.set({"overpass": 30.0, "map": 90.0, "limited": set()})
    try:
        assert app.run_overpass_query("test query")["elements"][0]["id"] == 1
    finally:
        app._SCREENING_NETWORK.reset(token)
    assert len({host for host, _, _ in calls}) == 3
    assert all(method == "GET" and timeout == 10 for _, method, timeout in calls)


def test_context_failure_diagnostics_keep_both_provider_errors(app, monkeypatch):
    def overpass(_):
        raise RuntimeError("HTTP 503 upstream unavailable")
    def fallback(*args):
        raise TimeoutError("Screening map time budget exhausted")
    monkeypatch.setattr(app, "run_overpass_query", overpass)
    monkeypatch.setattr(app, "map_context", fallback)
    with pytest.raises(RuntimeError) as error:
        app.fetch_golden_context(50.25, 28.66, [])
    assert "HTTP 503 upstream unavailable" in str(error.value)
    assert "Screening map time budget exhausted" in str(error.value)


def test_failed_surroundings_preserve_discovery_without_ranking(app, monkeypatch):
    city = {"lat": 50.25, "lon": 28.66, "display_name": "Test city"}
    # Synthetic names are regression fixtures, not recommended real sites.
    anchors = [{**city, "name": name, "kind": "mall"} for name in ["Zeta", "Alpha"]]
    monkeypatch.setattr(app, "geocode_location", lambda _: city)
    monkeypatch.setattr(app, "search_large_retail_destinations", lambda _: anchors)
    monkeypatch.setattr(app, "search_retail_anchors", lambda *a, **kw: [])
    def fail(*args):
        raise RuntimeError("surrounding service unavailable")
    monkeypatch.setattr(app, "fetch_golden_context", fail)
    shortlist, meta = app.build_golden_spot_candidates("Test city")
    assert shortlist == []
    assert not meta["ranking_available"] and not meta["context_available"]
    assert [r["name"] for r in meta["candidate_sites"]] == ["Alpha", "Zeta"]
    assert meta["context_error"] == "surrounding service unavailable"


def test_overpass_partial_response_remains_failure_with_provider_reason(app, monkeypatch):
    monkeypatch.setattr(app, "OVERPASS_URLS", ["https://example.test/interpreter"])
    payload = {"elements": [{"type": "node", "id": 1}],
               "remark": "runtime error: Query timed out"}
    monkeypatch.setattr(app.urllib.request, "urlopen",
                        lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(RuntimeError, match="Query timed out"):
        app.run_overpass_query("test query")


@pytest.mark.parametrize("mode", ["empty", "failed", "ineligible"])
def test_no_eligible_discovery_reproduces_exact_fallback_branch(app, monkeypatch, mode):
    city = {"lat": 50.25, "lon": 28.66, "display_name": "Test city"}
    monkeypatch.setattr(app, "geocode_location", lambda _: city)
    def search(*args, **kwargs):
        if mode == "failed":
            raise TimeoutError("discovery provider timed out")
        rows = [] if mode == "empty" else [
            {"name": "Synthetic supermarket", "lat": "50.25", "lon": "28.66",
             "type": "supermarket", "category": "shop"}]
        return io.BytesIO(json.dumps(rows).encode())
    monkeypatch.setattr(app.urllib.request, "urlopen", search)
    monkeypatch.setattr(app, "run_overpass_query", lambda _: {"elements": []})
    tiles = []
    monkeypatch.setattr(app, "fetch_golden_map_tile", lambda bbox: tiles.append(bbox))
    shortlist, meta = app.build_golden_spot_candidates("Test city")
    assert shortlist == [] and meta["candidate_sites"] == []
    assert not meta["ranking_available"]
    assert "No eligible premises available for surrounding-map coverage" in meta["context_error"]
    assert tiles == []  # The fallback makes no requests when it has no premises.
    assert meta["discovery_summary"]["eligible_before_context"] == 0
    requests = meta["discovery_requests"]
    assert len(requests) == 8
    if mode == "failed":
        assert all(r["error"] == "discovery provider timed out" for r in requests)
        assert all(r["returned_objects"] is None for r in requests)
    else:
        assert all(r["error"] is None for r in requests)
        assert all(r["returned_objects"] == (0 if mode == "empty" else 1) for r in requests)
    if mode == "ineligible":
        assert meta["discovery_summary"]["ineligible_objects"]
        assert meta["traffic_generators"]
