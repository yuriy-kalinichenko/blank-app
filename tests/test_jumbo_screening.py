"""Behavioural gates: tenants never become premises, even under dense traffic."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from golden_spot import classify_object, score_candidate, rank_candidates, traffic_score
from test_golden_discovery import app, city, malls


def obj(name, kind, lat=41.328, lon=19.818, **extra):
    return {"name": name, "kind": kind, "lat": lat, "lon": lon, **extra}


@pytest.mark.parametrize("row,role", [
    (obj("Real Mall", "mall"), "candidate"),
    (obj("Retail Park", "retail_park"), "candidate"),
    (obj("Retail premises", "retail", building="retail", osm_type="way"), "background"),
    (obj("Unverified point", "retail"), "background"),
    (obj("Nail salon", "retail", building="retail", osm_type="way"), "background"),
    (obj("Auto repair shop", "retail", building="retail", osm_type="way"), "background"),
    (obj("Mall cafe", "retail", building="retail", amenity="cafe", osm_type="way"), "traffic"),
    (obj("Mall pharmacy", "retail", building="retail", shop="pharmacy", osm_type="way"), "traffic"),
    (obj("Supermarket", "supermarket", building="retail", osm_type="way"), "traffic"),
    (obj("Department store", "department_store"), "traffic"),
    (obj("Unnamed", "mall"), "background"),
    (obj("Closed mall", "mall", tags={"disused:shop": "mall"}), "background"),
    (obj("Car park", "parking", amenity="parking"), "background"),
    (obj("Road", "primary", highway="primary"), "background"),
    (obj("Unnamed", "pharmacy", amenity="pharmacy"), "traffic"),
])
def test_classification_is_based_on_premises_evidence(row, role):
    assert classify_object(row)[0] == role


def setup_search(app, city, monkeypatch, destinations, context):
    monkeypatch.setattr(app, "geocode_location", lambda _: city)
    monkeypatch.setattr(app, "search_large_retail_destinations", lambda _: destinations)
    monkeypatch.setattr(app, "search_retail_anchors", lambda *a, **kw: [])
    monkeypatch.setattr(app, "fetch_golden_context", lambda *a: context)


def test_tenants_and_dense_poi_clusters_never_enter_shortlist(app, city, monkeypatch):
    venues = [obj("Mall A", "mall"), obj("Mall B", "mall", lon=19.8181)]
    traffic = [obj(f"Cafe {i}", "cafe", lat=41.35+i/100000, amenity="cafe", building="retail", osm_type="way", osm_id=i+10) for i in range(30)]
    traffic += [obj("Pharmacy", "retail", shop="pharmacy", building="retail"), obj("Supermarket", "supermarket")]
    setup_search(app, city, monkeypatch, venues + traffic, traffic)
    result, meta = app.build_golden_spot_candidates("Tirana")
    assert {r["label"] for r in result} == {"Mall A", "Mall B"}
    assert len(meta["candidate_sites"]) == 2
    assert len(meta["traffic_generators"]) == 32
    assert all(r["role"] == "candidate" for r in result)
    # No venue is fabricated from a POI cluster, even if all providers return POIs.
    setup_search(app, city, monkeypatch, traffic, traffic)
    result, meta = app.build_golden_spot_candidates("Tirana")
    assert result == [] and meta["candidate_sites"] == []


def test_missing_context_is_unknown_and_no_fringe_penalty(app, city, monkeypatch):
    venues = [obj("Centre Mall", "mall"), obj("Fringe Mall", "mall", lat=41.28, lon=19.86)]
    setup_search(app, city, monkeypatch, venues, [])
    def unavailable(*args):
        raise TimeoutError("provider failed")
    monkeypatch.setattr(app, "fetch_golden_context", unavailable)
    result, meta = app.build_golden_spot_candidates("Tirana")
    assert not meta["context_available"]
    assert [r["score"] for r in result] == [40, 40]
    assert all(r["components"]["Nearby parking"] is None for r in result)
    assert all(r["retail_count"] is None for r in result)


def test_three_tirana_runs_are_order_independent_and_keep_all_malls(app, city, malls, monkeypatch):
    venues = [obj(r["name"], "mall", float(r["lat"]), float(r["lon"]), osm_id=r["osm_id"], osm_type=r["osm_type"]) for r in malls if r["name"]]
    setup_search(app, city, monkeypatch, venues, [])
    snapshots = []
    for _ in range(3):
        result, meta = app.build_golden_spot_candidates("Tirana")
        snapshots.append(([(r["candidate_id"], r["score"]) for r in result], [r["name"] for r in meta["candidate_sites"]]))
        venues.reverse()
    assert snapshots[0] == snapshots[1] == snapshots[2]
    assert len(snapshots[0][1]) == 16
    assert any("TEG" in n for n in snapshots[0][1])
    assert any("QTU" in n for n in snapshots[0][1])


def test_more_small_pois_cannot_substitute_for_shopping_anchors():
    assert traffic_score([obj(str(i), "cafe") for i in range(100)]) == 1
    assert traffic_score([obj("Supermarket", "supermarket")]) == 3
    with pytest.raises(ValueError):
        score_candidate(obj("Pharmacy", "pharmacy"), [], True)


def test_richer_osm_tenant_tags_override_geocoder_venue_claim(app, city, monkeypatch):
    mall = obj("Wrong mall tag", "mall", osm_type="way", osm_id=123)
    cafe = obj("Wrong mall tag", "cafe", amenity="cafe", building="retail", osm_type="way", osm_id=123)
    setup_search(app, city, monkeypatch, [mall], [cafe])
    result, meta = app.build_golden_spot_candidates("Tirana")
    assert not result
    assert len(meta["traffic_generators"]) == 1


def test_result_ui_keeps_roles_separate_and_unknowns_visible(app, city, monkeypatch):
    from streamlit.testing.v1 import AppTest
    setup_search(app, city, monkeypatch, [obj("Real Mall", "mall")], [obj("Cafe", "cafe", amenity="cafe")])
    result, meta = app.build_golden_spot_candidates("Tirana")
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / 'streamlit_app.py')
    at.session_state['golden_spot_results'] = result
    at.session_state['golden_spot_meta'] = meta
    at.session_state['golden_spot_city'] = 'Tirana'
    at.run(timeout=15)
    assert len(at.exception) == 0
    labels = [e.label for e in at.expander]
    assert 'Jumbo candidate sites · 1' in labels
    assert 'Traffic generators · 1' in labels
    assert 'Background context · 0' in labels
    assert sum(b.label == 'Create project from this spot' for b in at.button) == 1
