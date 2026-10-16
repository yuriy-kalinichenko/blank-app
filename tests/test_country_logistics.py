from country_logistics import load_georgia_review, logistics_links, straight_line_km
from streamlit.testing.v1 import AppTest
from pathlib import Path


def test_country_inventory_distinguishes_offices_properties_and_approximate_points():
    data = load_georgia_review()
    assert len(data['sites']) == 5
    office = next(f for f in data['facilities'] if 'office' in f['type'].lower())
    assert office['lat'] is None
    rental = next(f for f in data['facilities'] if f['operator'] == 'Tbilisi Warehouse')
    assert rental['lat'] is None  # Street centroid is not a resolved plot.
    for f in data['facilities']:
        assert f['address'] and f['checked_at'] and f['sources']
        assert all(k in data['sources'] for k in f['sources'])
    assert all(all(v is None for v in s['commercial'].values()) for s in data['sites'])
    links = logistics_links(data)
    assert len(links) == 5
    assert all('not road' in next(k for k in row if k.startswith('Straight')) for row in links)
    gw = next(f for f in data['facilities'] if f['operator'] == 'Gebrüder Weiss')
    east = next(s for s in data['sites'] if s['name'] == 'East Point')
    assert 4 < straight_line_km(gw, east) < 6


def test_review_renders_as_an_independent_block_inside_single_city_discovery():
    root = Path(__file__).parents[1]
    at = AppTest.from_file(root / 'streamlit_app.py').run(timeout=20)
    assert not at.exception
    assert any('Country logistics' in e.label for e in at.expander)
    at.text_input(key='golden_spot_city').set_value('Tbilisi, Georgia').run()
    assert not at.exception
    assert any('Verified Tbilisi review' in e.label for e in at.expander)
    assert len(at.selectbox(key='review_tbilisi_site').options) == 5
