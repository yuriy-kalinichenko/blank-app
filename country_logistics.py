"""Source-backed country logistics review; no automatic rates or forecasts."""
import json
import math
from pathlib import Path


def load_georgia_review():
    return json.loads((Path(__file__).parent / 'data' / 'georgia_logistics.json').read_text())


def straight_line_km(a, b):
    """Lower-bound geographic separation, never a road distance or transit time."""
    p1, p2 = math.radians(a['lat']), math.radians(b['lat'])
    dp = p2 - p1
    dl = math.radians(b['lon'] - a['lon'])
    h = math.sin(dp / 2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl / 2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def logistics_links(data, facility_name=None):
    facilities = [f for f in data['facilities'] if f['type'].startswith('Warehouse /')]
    if facility_name:
        facilities = [f for f in facilities if f['name'] == facility_name]
    return [
        {'Warehouse': f['name'], 'Candidate': s['name'],
         'Straight-line km · not road': round(straight_line_km(f, s), 1),
         'Road / SLA': 'Not quoted; gate, truck route and loading window unverified'}
        for f in facilities if f['lat'] is not None and f['lon'] is not None
        for s in data['sites']
    ]


def render_tbilisi_review(city_query):
    # This sourced review is independent of the live Golden Spot score.
    if 'tbilisi' not in city_query.casefold() and 'თბილისი' not in city_query:
        return
    import streamlit as st
    data = load_georgia_review()
    with st.expander('Verified Tbilisi review · 16 October 2026', expanded=False):
        st.info(data['ranking_method'])
        st.dataframe([
            {'Survey priority': s['priority'], 'Candidate': s['name'],
             'Address': s['address'], 'Reason to investigate': s['judgment'],
             'Verified competitor subset': ', '.join(s['competitors'])}
            for s in data['sites']
        ], hide_index=True, width='stretch')
        name = st.selectbox('Review candidate evidence', [s['name'] for s in data['sites']], key='review_tbilisi_site')
        site = next(s for s in data['sites'] if s['name'] == name)
        st.write('Facts: ' + site['facts'])
        st.write('Access: ' + site['access'])
        st.write('Unknowns: ' + site['limitations'])
        st.caption('Lease, available unit size, measured footfall, rent and sales are unknown. Tenant stores are competitive context, not candidate premises.')
        for key in site['sources']:
            st.markdown(f'[{key}]({data["sources"][key]})')
        st.download_button('Export verified Tbilisi review', json.dumps(data, ensure_ascii=False, indent=2),
                           'tbilisi-georgia-review-2026-10-16.json', 'application/json', key='tbilisi_review_export')


def render_country_logistics():
    import streamlit as st
    from map_view import render_map
    data = load_georgia_review()
    with st.expander('Country logistics · Georgia / Логистика страны', expanded=False):
        st.caption('Evidence reviewed 16 October 2026 · Georgia (country) · source sample, not an exhaustive operator database')
        st.markdown('#### Routes and import processing')
        st.info('Preliminary comparison: sea container → Poti → Tbilisi 3PL → stores. Validate against Batumi, road supply and direct-to-store quotations before choosing a network.')
        st.dataframe(data['routes'], hide_index=True, width='stretch')
        st.write(data['customs'])
        st.markdown(f'[Revenue Service: SKU duties, origin and documents]({data["sources"]["customs"]}) · '
                    f'[Pre-declaration]({data["sources"]["customs_pre"]})')
        st.markdown('#### Operators, warehouses and gateways')
        st.caption('Mapped points are representative locations or address geocodes. Street-level points are explicitly approximate; they are not loading gates. Offices and unresolved properties are excluded from the point map.')
        points = [
            {'lat': s['lat'], 'lon': s['lon'], 'name': 'Candidate mall · '+s['name'], 'kind': 'candidate'}
            for s in data['sites']
        ] + [
            {'lat': f['lat'], 'lon': f['lon'],
             'name': f['name']+'\n'+f['type']+'\n'+f['coordinate_precision'],
             'kind': 'warehouse' if 'warehouse' in f['type'].casefold() else 'gateway'}
            for f in data['facilities'] if f['lat'] is not None
        ]
        render_map(points, center=(42.0, 43.2), fit=True, title='Georgia gateways, logistics facilities and Tbilisi candidates')
        st.dataframe([
            {'Facility': f['name'], 'Type': f['type'], 'Address': f['address'],
             'Services': f['services'], 'Delivery coverage': f['delivery_zone'],
             'Coordinates': (f"{f['lat']:.6f}, {f['lon']:.6f}" if f['lat'] is not None else 'Unmapped'),
             'Point precision': f['coordinate_precision'], 'Checked': f['checked_at'],
             'Source': data['sources'][f['sources'][0]]}
            for f in data['facilities']
        ], hide_index=True, width='stretch')
        selected = st.selectbox('Facility sources and limitations', [f['name'] for f in data['facilities']], key='georgia_facility')
        facility = next(f for f in data['facilities'] if f['name'] == selected)
        for key in facility['sources']:
            st.markdown(f'[{key}]({data["sources"][key]})')
        st.write(data['raben_status'])
        st.markdown(f'[Raben official country directory]({data["sources"]["raben"]})')
        st.markdown('#### Link to candidate stores')
        st.dataframe(logistics_links(data), hide_index=True, width='stretch')
        st.caption('The above distances are great-circle lower bounds from the mapped GW site to each mall. They exclude roads, congestion, vehicle restrictions, loading time and service commitments; no transport cost or ETA is inferred.')
        st.markdown('#### Storage operating model')
        st.dataframe(data['storage_options'], hide_index=True, width='stretch')
        st.caption('A dedicated warehouse in each country is an option to test, not a requirement. Compare the same volume and service level: port charges + linehaul + handling + storage + picking + store delivery + systems/staff + capital cost. Rates and delivery times remain unknown until quotes are available.')
        with st.expander('Missing inputs before commitment'):
            for missing in data['unknowns']:
                st.write('• '+missing)
        st.download_button('Export Georgia logistics evidence', json.dumps(data, ensure_ascii=False, indent=2),
                           'georgia-logistics-evidence-2026-10-16.json', 'application/json', key='georgia_logistics_export')
