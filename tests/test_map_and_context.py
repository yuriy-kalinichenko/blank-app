import json
import math
import re
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from map_view import map_html
from golden_context import context_tiles, map_context


def test_map_preserves_positions_without_executing_provider_labels():
    hostile = '</script><img src=x onerror=alert(1)>'
    page = map_html([{'lat':41.3,'lon':19.8,'name':hostile}, {'lat':float('nan'),'lon':20}], center=(41.3,19.8))
    payload = re.search(r'<script id="map-data" type="application/json">(.*?)</script>', page, re.S).group(1)
    assert '</script>' not in payload
    assert json.loads(payload)['points'] == [{'lat':41.3,'lon':19.8,'name':hostile}]
    assert hostile not in page


def test_shared_tiles_cover_each_candidate_full_evidence_radius():
    sites=[{'lat':41.328,'lon':19.818},{'lat':41.28,'lon':19.86}]
    tiles=context_tiles(sites)
    assert len(tiles)==len(set(tiles))
    assert tiles==context_tiles(sites+sites)
    for site in sites:
        for degree in range(0,360,5):
            lat=site['lat']+2.2/110.574*math.sin(math.radians(degree))
            lon=site['lon']+2.2/(111.32*math.cos(math.radians(site['lat'])))*math.cos(math.radians(degree))
            assert any(w<=lon<=e and s<=lat<=n for w,s,e,n in tiles)


def test_map_context_dedupes_osm_ids_but_keeps_distinct_same_name_branches():
    elements=[{'type':'node','id':1,'lat':41.328,'lon':19.818,'tags':{'name':'Same brand','shop':'supermarket'}},
              {'type':'node','id':2,'lat':41.329,'lon':19.819,'tags':{'name':'Same brand','shop':'supermarket'}},
              {'type':'node','id':3,'lat':42.5,'lon':19.818,'tags':{'shop':'supermarket'}},
              {'type':'node','id':4,'lat':41.328,'lon':19.818,'tags':{'building':'apartments'}}]
    rows=map_context([{'lat':41.328,'lon':19.818}],lambda _:elements)
    assert {r['osm_id'] for r in rows}=={1,2}


def test_incomplete_map_tiles_cannot_be_used_as_complete_context():
    count=0
    def load(_):
        nonlocal count
        count+=1
        if count==2:raise TimeoutError('budget exhausted')
        return [{'type':'node','id':1,'lat':41.328,'lon':19.818,'tags':{'amenity':'parking'}}]
    with pytest.raises(RuntimeError,match='coverage incomplete'):
        map_context([{'lat':41.328,'lon':19.818}],load)
    assert count==2


def test_overpass_failure_uses_shared_map_coverage(monkeypatch):
    # Import only the provider definitions, keeping the test independent of UI state.
    source=(Path(__file__).resolve().parents[1]/'streamlit_app.py').read_text().split('for state_key, state_value in BASE_ECON_STATE.items():')[0]
    ns={};exec(compile(source,'streamlit_app.py','exec'),ns)
    def fail(_):raise TimeoutError('overpass down')
    ns['run_overpass_query']=fail
    ns['fetch_golden_map_tile']=lambda _:[{'type':'node','id':5,'lat':41.328,'lon':19.818,'tags':{'amenity':'parking'}}]
    rows=ns['fetch_golden_context'](41.328,19.818,[{'lat':41.328,'lon':19.818}])
    assert len(rows)==1 and rows[0]['amenity']=='parking'
    assert rows[0]['discovery_source'].startswith('OpenStreetMap Map API')
