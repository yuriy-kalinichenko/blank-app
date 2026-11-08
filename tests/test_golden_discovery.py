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
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
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
    assert len(found) == 18
    assert sum(not item["name"].startswith("Unnamed mapped ") for item in found) == 16
    assert {item["osm_id"] for item in found if item["name"].startswith("Unnamed mapped ")} == {
        item["osm_id"] for item in malls if not item.get("name")
    }
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
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
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
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
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
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
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
    requests = [r for r in meta["discovery_requests"] if r["query"] != "Overpass premises discovery"]
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


@pytest.fixture
def zhytomyr_reference():
    return json.loads((ROOT / "tests/fixtures/zhytomyr_global_reference.json").read_text())


def test_real_zhytomyr_reference_is_not_excluded_by_geography_or_unicode(app, zhytomyr_reference):
    # Source-backed name/location; reference coordinates are NOT a live city geocode.
    # A shop=mall tag is hypothetical here, since raw provider tags were inaccessible.
    row = zhytomyr_reference
    assert app.distance_km(50.25, 28.66, row["lat"], row["lon"]) < 3
    assert app.classify_object({**row, "shop": "mall"})[0] == "candidate"
    # The name alone must not invent a venue type when that tag is absent.
    assert app.classify_object(row)[0] != "candidate"


def test_focused_discovery_recovers_premises_without_inventing_context(app, monkeypatch):
    # Entire provider payload is synthetic; this tests orchestration, not live OSM.
    city = {"lat": 50.25, "lon": 28.66, "display_name": "Test city"}
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
    monkeypatch.setattr(app, "search_large_retail_destinations", lambda _: [])
    monkeypatch.setattr(app, "search_retail_anchors", lambda *a, **kw: [])
    queries = []
    def overpass(query):
        queries.append(query)
        if '["shop"~' in query:
            return {"elements": [{"type": "way", "id": 123,
                "center": {"lat": 50.26, "lon": 28.68},
                "tags": {"name": "Synthetic Mall", "shop": "mall"}}]}
        raise TimeoutError("full surroundings query unavailable")
    monkeypatch.setattr(app, "run_overpass_query", overpass)
    received = []
    def map_fallback(candidates, loader):
        received.extend(candidates)
        raise TimeoutError("map service unavailable")
    monkeypatch.setattr(app, "map_context", map_fallback)
    shortlist, meta = app.build_golden_spot_candidates("Test city")
    assert len(queries) == 2
    assert '["amenity"' not in queries[0] and '["highway"' not in queries[0]
    assert '[timeout:8]' in queries[0] and 'around:20000,' in queries[0]
    assert received[0]["name"] == "Synthetic Mall"
    assert [r["name"] for r in meta["candidate_sites"]] == ["Synthetic Mall"]
    assert meta["discovery_summary"]["eligible_before_context"] == 1
    assert shortlist == [] and not meta["ranking_available"]
    assert meta["candidate_sites"][0]["components"]["Nearby parking"] is None


def test_focused_discovery_preserves_classification_and_rejects_invalid_geometry(app, monkeypatch):
    def way(ident, tags, center):
        return {"type": "way", "id": ident, "tags": tags, "center": center}
    point = {"lat": 50.25, "lon": 28.66}
    elements = [way(1, {"name": "Mapped Mall", "shop": "mall"}, point),
                way(2, {"name": "Inactive Mall", "shop": "mall", "disused": "yes"}, point),
                way(3, {"name": "Tenant", "shop": "supermarket"}, point),
                way(4, {"name": "Unknown location", "shop": "mall"}, {}),
                way(5, {"name": "Invalid", "shop": "mall"}, {"lat": "nan", "lon": 28}),
                way(6, {"name": "Distant", "shop": "mall"}, {"lat": 51, "lon": 28})]
    monkeypatch.setattr(app, "run_overpass_query", lambda _: {"elements": elements})
    rows = app.fetch_golden_premises(50.25, 28.66)
    assert {r["osm_id"] for r in rows} == {1, 2, 3}
    assert [r["osm_id"] for r in rows if app.classify_object(r)[0] == "candidate"] == [1]


def test_focused_discovery_not_requested_when_geocoder_found_premises(app, city, monkeypatch):
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
    monkeypatch.setattr(app, "search_large_retail_destinations", lambda _: [{**city, "name": "Synthetic Mall", "kind": "mall"}])
    monkeypatch.setattr(app, "search_retail_anchors", lambda *a, **kw: [])
    monkeypatch.setattr(app, "fetch_golden_context", lambda *args: [])
    def unexpected(*args):
        pytest.fail("Unnecessary focused discovery request")
    monkeypatch.setattr(app, "fetch_golden_premises", unexpected)
    app.build_golden_spot_candidates("Test city")


def test_focused_discovery_failure_does_not_skip_full_context_discovery(app, city, monkeypatch):
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
    monkeypatch.setattr(app, "search_large_retail_destinations", lambda _: [])
    monkeypatch.setattr(app, "search_retail_anchors", lambda *a, **kw: [])
    def fail(*args):
        raise TimeoutError("focused discovery unavailable")
    monkeypatch.setattr(app, "fetch_golden_premises", fail)
    monkeypatch.setattr(app, "fetch_golden_context", lambda *args: [
        {**city, "name": "Synthetic Context Mall", "shop": "mall"}])
    shortlist, meta = app.build_golden_spot_candidates("Test city")
    assert shortlist[0]["name"] == "Synthetic Context Mall"
    assert meta["discovery_requests"][-1]["error"] == "focused discovery unavailable"


@pytest.mark.parametrize("search_name", ["search_large_retail_destinations", "search_retail_anchors"])
def test_discovery_rejections_explain_filters_without_changing_results(app, city, monkeypatch, search_name):
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
    good = {"name": "Synthetic Mall", "lat": str(city["lat"]), "lon": str(city["lon"]),
            "type": "mall", "category": "shop", "osm_type": "way", "osm_id": 123}
    rows = [
        {**good, "lat": "invalid", "name": "Bad coordinates"},
        {**good, "lat": "45", "name": "Distant Mall"},
        {**good, "name": "", "type": "retail", "namedetails": {"name:uk": "Тестовий центр"}},
        {**good, "name": "shopping mall"},
        good, good,
    ]
    calls = []
    def response(*args, **kwargs):
        calls.append(1)
        return io.BytesIO(json.dumps(rows if len(calls) == 1 else []).encode())
    monkeypatch.setattr(app.urllib.request, "urlopen", response)
    budget = {"overpass": 30., "map": 90., "limited": set()}
    token = app._SCREENING_NETWORK.set(budget)
    try:
        search = getattr(app, search_name)
        found = search("Test city", **({"include_overpass": False} if search_name == "search_retail_anchors" else {}))
    finally:
        app._SCREENING_NETWORK.reset(token)
    assert [r["name"] for r in found] == ["Synthetic Mall"]
    rejected = budget["discovery_rejections"]
    assert [r["reason"] for r in rejected] == ["invalid_coordinates", "outside_search_radius",
                                             "missing_name", "generic_name", "duplicate_destination"]
    assert rejected[0]["lat"] == "invalid" and rejected[0]["distance_km"] is None
    assert rejected[1]["distance_km"] > 20
    assert rejected[2]["alternative_names"] == {"name:uk": "Тестовий центр"}
    assert rejected[-1]["distance_km"] == 0
    assert rejected[-1]["search_center"] == {"lat": city["lat"], "lon": city["lon"]}
    assert rejected[-1]["osm_id"] == "123"
    assert budget["overpass"] == 30 and budget["map"] == 90


def test_rejection_diagnostics_are_bounded_and_exclude_unselected_payload_fields(app):
    budget = {"overpass": 30., "map": 90., "limited": set()}
    token = app._SCREENING_NETWORK.set(budget)
    try:
        for i in range(25):
            app.record_discovery_rejection("q", {"name": "x" * 500, "lat": "50", "lon": "28",
                "extratags": {"private_test_field": "NOT_RETAINED"},
                "email": "NOT_RETAINED", "display_name": "NOT_RETAINED"}, "generic_name", 50., 28., 0.)
    finally:
        app._SCREENING_NETWORK.reset(token)
    assert len(budget["discovery_rejections"]) == 20
    assert budget["discovery_rejection_count"] == 25
    assert len(budget["discovery_rejections"][0]["name"]) == 160
    assert "NOT_RETAINED" not in json.dumps(budget["discovery_rejections"])
    assert app._SCREENING_NETWORK.get() is None


def test_provider_stages_show_exhaustion_without_changing_recovery(app, city, monkeypatch):
    monkeypatch.setattr(app, "geocode_location", lambda _, **kwargs: city)
    monkeypatch.setattr(app, "search_large_retail_destinations", lambda _: [])
    monkeypatch.setattr(app, "search_retail_anchors", lambda *a, **kw: [])
    def premises(*args):
        budget = app._SCREENING_NETWORK.get()
        budget["overpass"] = 0.
        budget["limited"].add("overpass")
        raise TimeoutError("budget exhausted")
    monkeypatch.setattr(app, "fetch_golden_premises", premises)
    def context(*args):
        raise TimeoutError("no context")
    monkeypatch.setattr(app, "fetch_golden_context", context)
    shortlist, meta = app.build_golden_spot_candidates("Test city")
    assert shortlist == [] and not meta["ranking_available"]
    stages = meta["discovery_stages"]
    assert [s["stage"] for s in stages] == ["after_nominatim_discovery", "before_surroundings", "after_surroundings"]
    assert stages[0]["remaining_seconds"] == {"overpass": 30., "map": 90.}
    assert stages[1]["remaining_seconds"] == {"overpass": 0., "map": 90.}
    assert stages[1]["limited_pools"] == ["overpass"]
    assert stages[2]["remaining_seconds"] == stages[1]["remaining_seconds"]


def test_city_geocoding_rejects_region_first_and_preserves_address_geocoding(app, monkeypatch):
    # Synthetic API envelopes around the observed wrong centre and UN city reference.
    evidence = json.loads((ROOT / "tests/fixtures/zhytomyr_observed_rejection.json").read_text())
    region = {**evidence["search_center"], "addresstype": "state", "type": "administrative",
              "display_name": "Zhytomyr Oblast, Ukraine"}
    city = {**evidence["city_reference"], "addresstype": "city", "type": "administrative",
            "display_name": "Zhytomyr, Ukraine"}
    calls = []
    def response(request, **kwargs):
        calls.append(parse_qs(urlparse(request.full_url).query))
        return io.BytesIO(json.dumps([region, city]).encode())
    monkeypatch.setattr(app.urllib.request, "urlopen", response)
    app.geocode_location.clear()
    try:
        for query in ["Zhytomyr", "Житомир, Ukraine"]:
            actual = app.geocode_location(query, feature_type="city")
            assert actual["lat"] == city["lat"] and actual["lon"] == city["lon"]
            assert actual["resolution_type"] == "city"
        assert all(c["featureType"] == ["city"] and c["limit"] == ["5"] for c in calls)
        ordinary = app.geocode_location("An existing project address")
        assert ordinary["lat"] == region["lat"]  # Ordinary address resolution unchanged.
        assert "featureType" not in calls[-1] and calls[-1]["limit"] == ["1"]
    finally:
        app.geocode_location.clear()


@pytest.mark.parametrize("rows", [[], [
    {"lat": "50.9080532", "lon": "28.3867504", "addresstype": "state", "type": "administrative"}
]])
def test_city_geocoding_never_falls_back_to_region(app, monkeypatch, rows):
    monkeypatch.setattr(app.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(rows).encode()))
    app.geocode_location.clear()
    try:
        with pytest.raises(ValueError, match="No city-level location"):
            app.geocode_location("Zhytomyr", feature_type="city")
    finally:
        app.geocode_location.clear()


@pytest.mark.parametrize("search_name", ["search_large_retail_destinations", "search_retail_anchors"])
def test_observed_unnamed_mall_is_kept_honestly_only_inside_resolved_area(app, monkeypatch, search_name):
    evidence = json.loads((ROOT / "tests/fixtures/zhytomyr_observed_rejection.json").read_text())
    # Reconstruct only the public fields present in the real diagnostic.
    row = {k: evidence[k] for k in ["name", "lat", "lon", "osm_type", "osm_id", "category", "type"]}
    monkeypatch.setattr(app.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps([row]).encode()))
    resolved = []
    center = dict(evidence["search_center"])
    def geocode(query, **kwargs):
        resolved.append(kwargs)
        return center
    monkeypatch.setattr(app, "geocode_location", geocode)
    search = getattr(app, search_name)
    kwargs = {"include_overpass": False} if search_name == "search_retail_anchors" else {}
    old_area = search("Zhytomyr", **kwargs)
    assert len(old_area) == 1
    assert old_area[0]["name"] == "Unnamed mapped mall (OSM way/1429557871)"
    assert app.classify_object(old_area[0])[0] == "candidate"
    center = dict(evidence["city_reference"])
    correct_area = search("Zhytomyr", **kwargs)
    assert correct_area == []  # The observed object is not in Zhytomyr city's radius.
    assert all(r == {"feature_type": "city"} for r in resolved)
    assert app.distance_km(center["lat"], center["lon"], float(row["lat"]), float(row["lon"])) > 70


def test_explicit_unnamed_labels_do_not_merge_distinct_osm_venues(app):
    def venue(ident):
        return {"name": app.mapped_venue_name("", "mall", "way", ident),
                "lat": 50.25, "lon": 28.66, "kind": "mall", "osm_type": "way", "osm_id": ident}
    assert not app.same_retail_destination(venue(1), venue(2))
    assert app.mapped_venue_name("", "retail", "way", 1) == ""
    assert app.mapped_venue_name("", "mall", None, None) == ""


def test_mapped_venue_name_normalizes_provider_whitespace(app):
    assert app.mapped_venue_name("  Central Mall  ", "mall", "way", 7) == "Central Mall"
    assert (
        app.mapped_venue_name("   ", "mall", "way", 7)
        == "Unnamed mapped mall (OSM way/7)"
    )
    assert app.mapped_venue_name("\t", "retail", "way", 7) == ""
