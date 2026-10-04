import json
import math
import time
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Jumbo Location Analyzer", layout="wide")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]
USER_AGENT = "JumboLocationAnalyzer/0.1 (site-selection prototype)"
WORLDPOP_URL = "https://api.worldpop.org/v2"
BUILD_VERSION = "2026-10-04-v9.4"


BASE_ECON_STATE = {
    "econ_currency": "EUR",
    "econ_area": 4500.0,
    "econ_rent": 5.0,
    "econ_capex": 2500000.0,
    "econ_sales": 5000000.0,
    "econ_margin": 50.0,
    "econ_payroll": 250000.0,
    "econ_utilities": 12000.0,
    "econ_logistics": 20000.0,
    "econ_other_opex": 100000.0,
    "econ_scenario_name": "Karavan Mall, Kyiv - Base",
}


def run_overpass_query(query):
    """Run an Overpass query with multiple endpoints and both POST/GET fallbacks."""
    encoded = urllib.parse.urlencode({"data": query})
    data = encoded.encode("utf-8")
    errors = []

    for endpoint in OVERPASS_URLS:
        # POST is preferred, but some public mirrors/cloud egress paths intermittently
        # reject POST requests. Fall back to GET before moving to the next mirror.
        for method in ("POST", "GET"):
            try:
                if method == "POST":
                    url = endpoint
                    req = urllib.request.Request(
                        url,
                        data=data,
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "application/json",
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        method="POST",
                    )
                else:
                    url = f"{endpoint}?{encoded}"
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "application/json",
                        },
                        method="GET",
                    )

                with urllib.request.urlopen(req, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                if isinstance(payload, dict) and "elements" in payload:
                    return payload
                errors.append(f"{endpoint} {method}: invalid response")
            except Exception as exc:
                errors.append(f"{endpoint} {method}: {exc}")

    raise RuntimeError("All Overpass endpoints failed. " + " | ".join(errors))


@st.cache_data(ttl=3600)
def geocode_location(query):
    params = urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1}
    )
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data:
        return None
    item = data[0]
    return {
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
        "display_name": item.get("display_name", query),
    }


@st.cache_data(ttl=3600)
def fetch_nearby_retail(lat, lon, radius=3000):
    query = f"""
    [out:json][timeout:25];
    (
      nwr(around:{radius},{lat},{lon})["shop"~"toys|variety_store|department_store|supermarket|furniture|houseware|gift|stationery"];
      nwr(around:{radius},{lat},{lon})["shop"="mall"];
      nwr(around:{radius},{lat},{lon})["amenity"="parking"];
    );
    out center tags;
    """
    payload = run_overpass_query(query)

    rows = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        point_lat = element.get("lat") or element.get("center", {}).get("lat")
        point_lon = element.get("lon") or element.get("center", {}).get("lon")
        rows.append(
            {
                "name": tags.get("name") or tags.get("brand") or "Unnamed",
                "shop": tags.get("shop"),
                "amenity": tags.get("amenity"),
                "lat": point_lat,
                "lon": point_lon,
            }
        )
    # De-duplicate OSM objects that can represent the same real-world place
    unique = {}
    for row in rows:
        name = (row.get("name") or "").strip().lower()
        category = row.get("shop") or row.get("amenity") or ""
        lat_key = round(row.get("lat"), 4) if row.get("lat") is not None else None
        lon_key = round(row.get("lon"), 4) if row.get("lon") is not None else None
        if name and name != "unnamed":
            key = (name, category)
        else:
            key = (category, lat_key, lon_key)
        unique[key] = row
    return list(unique.values())


@st.cache_data(ttl=3600)
def fetch_access_context(lat, lon, radius=1500):
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius},{lat},{lon})["highway"~"motorway|trunk|primary|secondary"];
      nwr(around:{radius},{lat},{lon})["highway"="bus_stop"];
      nwr(around:{radius},{lat},{lon})["public_transport"="platform"];
      nwr(around:{radius},{lat},{lon})["railway"~"tram_stop|station|halt|subway_entrance"];
    );
    out center tags;
    """
    payload = run_overpass_query(query)

    rows = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        point_lat = element.get("lat") or element.get("center", {}).get("lat")
        point_lon = element.get("lon") or element.get("center", {}).get("lon")
        rows.append(
            {
                "name": tags.get("name") or tags.get("ref") or "Unnamed",
                "highway": tags.get("highway"),
                "public_transport": tags.get("public_transport"),
                "railway": tags.get("railway"),
                "lat": point_lat,
                "lon": point_lon,
            }
        )

    unique = {}
    for row in rows:
        category = row.get("highway") or row.get("public_transport") or row.get("railway") or ""
        name = (row.get("name") or "").strip().lower()
        lat_key = round(row.get("lat"), 4) if row.get("lat") is not None else None
        lon_key = round(row.get("lon"), 4) if row.get("lon") is not None else None
        key = (category, name, lat_key, lon_key)
        unique[key] = row
    return list(unique.values())


def circle_polygon(lat, lon, radius_km, points=48):
    coords = []
    lat_scale = 110.574
    lon_scale = 111.320 * math.cos(math.radians(lat))
    for i in range(points + 1):
        angle = 2 * math.pi * i / points
        d_lat = (radius_km * math.sin(angle)) / lat_scale
        d_lon = (radius_km * math.cos(angle)) / lon_scale
        coords.append([lon + d_lon, lat + d_lat])
    return {"type": "Polygon", "coordinates": [coords]}


@st.cache_data(ttl=86400)
def worldpop_population(lat, lon, radius_km, year=2025):
    payload = {
        "geojson": circle_polygon(lat, lon, radius_km),
        "year": year,
        "resolution": "1km",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{WORLDPOP_URL}/population",
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        submitted = json.loads(response.read().decode("utf-8"))

    task_id = submitted.get("task_id")
    if not task_id:
        raise RuntimeError(f"WorldPop did not return a task_id: {submitted}")

    last_payload = None
    for _ in range(30):
        status_req = urllib.request.Request(
            f"{WORLDPOP_URL}/tasks/{task_id}",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(status_req, timeout=30) as response:
            last_payload = json.loads(response.read().decode("utf-8"))

        status = last_payload.get("status")
        if status == "success":
            result = last_payload.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"WorldPop success response had no result object: {last_payload}")
            if result.get("total_population") is None:
                raise RuntimeError(f"WorldPop result had no total_population: {last_payload}")
            return result
        if status == "failure":
            raise RuntimeError(last_payload.get("error") or f"WorldPop request failed: {last_payload}")
        time.sleep(1)

    raise TimeoutError(f"WorldPop population request timed out. Last response: {last_payload}")


SCENARIO_FILE = "saved_scenarios.json"


def load_saved_scenarios():
    default_scenarios = {
        "Karavan Mall, Kyiv - Base": {
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
        }
    }
    try:
        with open(SCENARIO_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        merged = {}
        if isinstance(data, dict):
            merged.update(data)
        merged.update(default_scenarios)
        return merged
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_scenarios


def persist_saved_scenarios(data):
    with open(SCENARIO_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def distance_km(lat1, lon1, lat2, lon2):
    if lat2 is None or lon2 is None:
        return None
    radius = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


for state_key, state_value in BASE_ECON_STATE.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_value


st.title("Jumbo Location Analyzer")
st.caption(f"Build: {BUILD_VERSION}")
st.caption(
    "Retail site-selection prototype inspired by leading location-intelligence workflows: "
    "trade area, demand, traffic, competition, economics and scoring."
)

location = st.text_input(
    "Enter address or shopping center",
    value="Karavan Mall, Kyiv",
    placeholder="Example: Karavan Mall, Kyiv",
)

analyze = st.button("Analyze location", type="primary")

if analyze:
    if not location.strip():
        st.warning("Enter a location first.")
    else:
        with st.spinner("Locating the site and scanning nearby retail..."):
            try:
                geo = geocode_location(location.strip())
                if geo is None:
                    st.error("Location not found. Try a more complete address.")
                else:
                    try:
                        retail = fetch_nearby_retail(geo["lat"], geo["lon"])
                        retail_error = None
                        st.session_state["last_good_retail"] = retail
                    except Exception as exc:
                        retail = st.session_state.get("last_good_retail", [])
                        retail_error = str(exc) if not retail else None

                    access = []
                    access_error = None
                    try:
                        access = fetch_access_context(geo["lat"], geo["lon"])
                        st.session_state["last_good_access"] = access
                    except Exception as exc:
                        access = st.session_state.get("last_good_access", [])
                        access_error = str(exc) if not access else None

                    population = {}
                    population_errors = {}
                    # Provisional urban-drive proxy at ~24 km/h average effective speed:
                    # 5 min ≈ 2 km, 10 min ≈ 4 km, 15 min ≈ 6 km.
                    for label, radius in [("5 min", 2), ("10 min", 4), ("15 min", 6)]:
                        try:
                            result = worldpop_population(
                                geo["lat"], geo["lon"], radius, year=2025
                            )
                            if result.get("total_population") is not None:
                                population[label] = result
                            else:
                                population_errors[label] = "No population value returned"
                        except Exception as exc:
                            population_errors[label] = str(exc)

                    st.session_state["analysis"] = {
                        "query": location.strip(),
                        "geo": geo,
                        "retail": retail,
                        "retail_error": retail_error,
                        "population": population,
                        "population_errors": population_errors,
                        "access": access,
                        "access_error": access_error,
                    }
            except Exception as exc:
                st.error(f"Could not locate the site: {exc}")

analysis = st.session_state.get("analysis")

if analysis:
    geo = analysis["geo"]
    retail = analysis["retail"]
    population = analysis.get("population", {})
    access = analysis.get("access", [])

    st.divider()
    st.subheader(analysis["query"])
    st.caption(geo["display_name"])

    map_points = [{"lat": geo["lat"], "lon": geo["lon"]}]
    for item in retail:
        if item.get("lat") is not None and item.get("lon") is not None:
            map_points.append({"lat": item["lat"], "lon": item["lon"]})
    map_df = pd.DataFrame(map_points)
    st.map(map_df, zoom=13)

    st.caption(
        f"Coordinates: {geo['lat']:.5f}, {geo['lon']:.5f} · "
        f"Mapped POIs: {max(len(map_points) - 1, 0)}"
    )

    direct_competitor_types = {
        "toys",
        "variety_store",
        "department_store",
    }
    related_retail_types = {
        "furniture",
        "houseware",
        "gift",
        "stationery",
    }
    anchor_types = {"supermarket", "department_store", "mall"}

    for item in retail:
        item["distance_km"] = distance_km(
            geo["lat"], geo["lon"], item.get("lat"), item.get("lon")
        )

    direct_competitors = [
        r for r in retail
        if r.get("shop") in direct_competitor_types
        and (r.get("name") or "").strip().lower() != "unnamed"
    ]
    related_retail = [
        r for r in retail
        if r.get("shop") in related_retail_types
        and (r.get("name") or "").strip().lower() != "unnamed"
    ]
    anchors = [
        r for r in retail
        if r.get("shop") in anchor_types
        and (r.get("name") or "").strip().lower() != "unnamed"
    ]
    parking = [r for r in retail if r.get("amenity") == "parking"]

    comp_1km = [r for r in direct_competitors if r.get("distance_km") is not None and r["distance_km"] <= 1]
    comp_3km = [r for r in direct_competitors if r.get("distance_km") is not None and r["distance_km"] <= 3]
    anchor_1km = [r for r in anchors if r.get("distance_km") is not None and r["distance_km"] <= 1]
    anchor_3km = [r for r in anchors if r.get("distance_km") is not None and r["distance_km"] <= 3]
    parking_1km = [r for r in parking if r.get("distance_km") is not None and r["distance_km"] <= 1]

    nearest_competitor_km = min(
        [r["distance_km"] for r in direct_competitors if r.get("distance_km") is not None],
        default=None,
    )
    nearest_competitor_name = None
    if nearest_competitor_km is not None:
        nearest_match = min(
            [r for r in direct_competitors if r.get("distance_km") is not None],
            key=lambda r: r["distance_km"],
        )
        nearest_competitor_name = nearest_match.get("name")

    competition_proximity_points = 0
    if nearest_competitor_km is not None:
        if nearest_competitor_km <= 0.5:
            competition_proximity_points = 40
        elif nearest_competitor_km <= 1.0:
            competition_proximity_points = 32
        elif nearest_competitor_km <= 2.0:
            competition_proximity_points = 20
        elif nearest_competitor_km <= 3.0:
            competition_proximity_points = 10

    competition_1km_points = min(30, len(comp_1km) * 10)
    competition_outer_points = min(30, max(0, len(comp_3km) - len(comp_1km)) * 3)
    competition_pressure = min(
        100,
        competition_proximity_points + competition_1km_points + competition_outer_points,
    )

    population_complete = all(
        population.get(label, {}).get("total_population") is not None
        for label in ["5 min", "10 min", "15 min"]
    )

    for item in access:
        item["distance_km"] = distance_km(
            geo["lat"], geo["lon"], item.get("lat"), item.get("lon")
        )

    major_road_types = {"motorway", "trunk", "primary", "secondary"}
    major_roads = [r for r in access if r.get("highway") in major_road_types]
    transit_stops = [
        r for r in access
        if r.get("highway") == "bus_stop"
        or r.get("public_transport") == "platform"
        or r.get("railway") in {"tram_stop", "station", "halt", "subway_entrance"}
    ]
    named_major_roads = sorted({
        (r.get("name") or "").strip()
        for r in major_roads
        if (r.get("name") or "").strip() and (r.get("name") or "").strip().lower() != "unnamed"
    })
    nearest_major_road_km = min(
        [r["distance_km"] for r in major_roads if r.get("distance_km") is not None],
        default=None,
    )

    road_score = 0
    if nearest_major_road_km is not None:
        if nearest_major_road_km <= 0.25:
            road_score = 35
        elif nearest_major_road_km <= 0.5:
            road_score = 30
        elif nearest_major_road_km <= 1.0:
            road_score = 22
        else:
            road_score = 12

    network_score = min(15, len(named_major_roads) * 3)
    transit_score = min(25, len(transit_stops) * 2)
    parking_score = min(25, len(parking_1km) * 2)
    access_score = min(100, road_score + network_score + transit_score + parking_score)

    retail_data_ok = not analysis.get("retail_error")
    access_data_ok = not analysis.get("access_error") and bool(access)
    access_complete = access_data_ok and nearest_major_road_km is not None
    live_modules = 2 + (1 if retail_data_ok else 0) + (1 if population_complete else 0) + (1 if access_complete else 0)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Live data coverage", f"{live_modules} / 5 modules")
    c2.metric("Direct competitors / 1 km", len(comp_1km) if retail_data_ok else "No data")
    c3.metric("Direct competitors / 3 km", len(comp_3km) if retail_data_ok else "No data")
    c4.metric("Retail anchors / 3 km", len(anchor_3km) if retail_data_ok else "No data")
    c5.metric("Parking POIs / 1 km", len(parking_1km) if retail_data_ok else "No data")

    if analysis.get("retail_error"):
        st.warning(
            "The map loaded, but the public OpenStreetMap retail layer is temporarily unavailable."
        )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Executive summary",
            "Catchment & demand",
            "Traffic & access",
            "Competition",
            "Commercial & economics",
        ]
    )

    with tab1:
        st.markdown("### Decision dashboard")
        st.info(
            "Live now: exact site geocoding, mapped nearby retail fabric and commercial economics. "
            "Next: drive-time catchment, demographic demand, traffic and a calibrated Jumbo sales model."
        )

        if retail_data_ok:
            st.write(
                f"Competition pressure proxy: **{competition_pressure}/100** · "
                f"Direct competitors: **{len(comp_1km)} within 1 km**, **{len(comp_3km)} within 3 km**."
            )
        else:
            st.write("Competition pressure proxy: **No data** — retail source unavailable in this run.")

        if len(anchor_1km) > 0:
            st.write(f"Retail context: {len(anchor_1km)} anchor-format retail POI(s) detected within 1 km.")
        coverage = pd.DataFrame(
            [
                ["Location / map", "Live", "OpenStreetMap geocoding"],
                ["Nearby retail / competition", "Live" if retail_data_ok else "Needs retry", "OpenStreetMap POIs"],
                ["Catchment population", "Live proxy" if population_complete else "Needs retry", "WorldPop 2025 + provisional 5/10/15-minute proxy"],
                ["Traffic & access", "Live proxy" if access_complete else "Needs retry", "OpenStreetMap roads, transit and parking"],
                ["Foot & car traffic counts", "Next layer", "Mobility / traffic provider"],
                ["Sales forecast", "Model layer", "Jumbo benchmarks + local drivers"],
                ["Economics", "Ready", "User commercial assumptions"],
            ],
            columns=["Module", "Status", "Source / method"],
        )
        st.dataframe(coverage, use_container_width=True, hide_index=True)

    with tab2:
        st.markdown("### Catchment & demand")
        st.caption(f"Build: {BUILD_VERSION}")
        st.write(
            "Target structure: population and households inside 5-, 10- and 15-minute drive-time "
            "areas, spending power, family/children profile and retail expenditure."
        )
        pop5 = population.get("5 min", {}).get("total_population")
        pop10 = population.get("10 min", {}).get("total_population")
        pop15 = population.get("15 min", {}).get("total_population")

        d1, d2, d3 = st.columns(3)
        d1.metric("5-min population proxy", f"{pop5:,.0f}" if pop5 is not None else "—")
        d2.metric("10-min population proxy", f"{pop10:,.0f}" if pop10 is not None else "—")
        d3.metric("15-min population proxy", f"{pop15:,.0f}" if pop15 is not None else "—")

        if population_complete:
            st.success(
                "Population source: WorldPop 2025. Current zones are provisional circular "
                "urban-drive proxies (~2/4/6 km for 5/10/15 minutes), not final road isochrones."
            )
        elif population:
            st.warning(
                "WorldPop returned population for only some catchment zones. "
                "The available values are shown below; retry the analysis for the missing zones."
            )
            rows = []
            for label, radius in [("5 min", 2), ("10 min", 4), ("15 min", 6)]:
                item = population.get(label, {})
                if item:
                    rows.append({
                        "Catchment": label,
                        "Proxy radius, km": radius,
                        "Population": round(item.get("total_population", 0)),
                        "Area, km²": round(item.get("area_km2", 0), 1),
                        "Density / km²": round(item.get("population_density", 0)),
                    })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.warning(
                "WorldPop demographic layer is temporarily unavailable. "
                "Retail and map analysis still works."
            )

        population_errors = analysis.get("population_errors", {})
        if population_complete:
            st.success("WorldPop status: all 3 catchment population values loaded.")
        elif population:
            loaded_labels = ", ".join(sorted(population.keys()))
            st.warning(f"WorldPop status: partial data loaded for {loaded_labels}.")
        else:
            st.error("WorldPop status: no population values loaded.")

        if population_errors:
            st.markdown("#### WorldPop diagnostics")
            for label, error in population_errors.items():
                st.code(f"{label}: {error}")
        elif not population_complete:
            st.code("No detailed WorldPop error was captured in this build.")

    with tab3:
        st.markdown("### Traffic & access")
        st.caption(f"Build: {BUILD_VERSION}")

        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("Access proxy score", f"{access_score}/100" if access_complete else "No data")
        a2.metric(
            "Nearest major road",
            f"{nearest_major_road_km:.2f} km" if access_complete else "No data",
        )
        a3.metric("Named major roads / 1.5 km", len(named_major_roads) if access_data_ok else "No data")
        a4.metric("Transit stops / 1.5 km", len(transit_stops) if access_data_ok else "No data")
        a5.metric("Parking POIs / 1 km", len(parking_1km) if retail_data_ok else "No data")

        if access_complete:
            st.success(
                "Access layer is live from OpenStreetMap. The score is an infrastructure proxy, "
                "not a measured traffic-volume score."
            )
        else:
            st.warning(
                "Road/transit data is incomplete in this run. Missing data is shown as 'No data' "
                "and is not treated as a real zero."
            )

        if named_major_roads:
            st.write("Major road context: " + ", ".join(named_major_roads[:8]))

        score_table = pd.DataFrame(
            [
                ["Major-road proximity", road_score if access_data_ok else "No data", 35],
                ["Road-network choice", network_score if access_data_ok else "No data", 15],
                ["Public transport", transit_score if access_data_ok else "No data", 25],
                ["Parking presence", parking_score, 25],
            ],
            columns=["Access component", "Current points", "Maximum weight"],
        )
        st.dataframe(score_table, use_container_width=True, hide_index=True)

        st.info(
            "Car traffic volume and footfall are still intentionally blank. "
            "Those require a measured mobility/traffic source; we will not infer them from roads alone."
        )

        if analysis.get("access_error"):
            st.code(f"Access diagnostics: {analysis['access_error']}")

    with tab4:
        st.markdown("### Competition & retail fabric")
        st.caption(f"Build: {BUILD_VERSION}")
        st.caption(
            "Direct competitors = named toy, variety and department-store POIs. "
            "Related home/gift/stationery retail is tracked separately."
        )

        q1, q2, q3, q4, q5 = st.columns(5)
        q1.metric("Competition pressure proxy", f"{competition_pressure}/100" if retail_data_ok else "No data")
        q2.metric(
            "Nearest direct competitor",
            (f"{nearest_competitor_km:.2f} km" if nearest_competitor_km is not None else "None in 3 km") if retail_data_ok else "No data",
        )
        q3.metric("Direct competitors / 1 km", len(comp_1km) if retail_data_ok else "No data")
        q4.metric("Direct competitors / 3 km", len(comp_3km) if retail_data_ok else "No data")
        q5.metric("Retail anchors / 3 km", len(anchor_3km) if retail_data_ok else "No data")

        if nearest_competitor_name:
            st.write(f"Nearest named direct competitor: **{nearest_competitor_name}**")

        pressure_table = pd.DataFrame(
            [
                ["Nearest-competitor proximity", competition_proximity_points if retail_data_ok else "No data", 40],
                ["Direct competitors within 1 km", competition_1km_points if retail_data_ok else "No data", 30],
                ["Additional direct competitors from 1–3 km", competition_outer_points if retail_data_ok else "No data", 30],
            ],
            columns=["Competition component", "Current points", "Maximum weight"],
        )
        st.dataframe(pressure_table, use_container_width=True, hide_index=True)
        st.info(
            "Higher competition pressure means denser/closer named competitors in the public OSM layer. "
            "It is a screening proxy, not a market-share forecast."
        )

        if direct_competitors:
            comp_rows = []
            for item in direct_competitors:
                dist = item.get("distance_km")
                comp_rows.append(
                    {
                        "Name": item["name"],
                        "Type": item.get("shop") or "retail",
                        "Distance, km": round(dist, 2) if dist is not None else None,
                    }
                )
            comp_df = pd.DataFrame(comp_rows).sort_values(
                "Distance, km", na_position="last"
            )
            st.dataframe(comp_df, use_container_width=True, hide_index=True)
        elif retail_data_ok:
            st.write("No named direct competitor POIs were found in the public OSM layer within 3 km.")
        else:
            st.warning("Competition data is unavailable in this run; the app will retry the backup source on the next analysis.")
        st.caption(
            f"Related retail POIs in the scan: {len(related_retail)}. "
            f"Retail anchors in 1 km: {len(anchor_1km)}. "
            "This remains an initial public-data scan, not yet the final competitor/cannibalization model."
        )

    with tab5:
        st.markdown("### Commercial & economics")
        st.caption(f"Build: {BUILD_VERSION}")
        st.info(
            "This module uses commercial assumptions entered by the user. "
            "It does not invent rent, CAPEX, sales or margin from public map data."
        )

        st.success("Base scenario loader is active.")
        if st.button(
            "LOAD BASE SCENARIO NOW",
            type="primary",
            use_container_width=True,
            key="econ_load_base_v9",
        ):
            for state_key, state_value in BASE_ECON_STATE.items():
                st.session_state[state_key] = state_value
            st.rerun()

        saved_scenarios = load_saved_scenarios()
        if saved_scenarios:
            s1, s2 = st.columns([3, 1])
            selected_scenario = s1.selectbox(
                "Saved scenarios",
                ["—"] + sorted(saved_scenarios.keys()),
                key="econ_saved_scenario",
            )
            load_clicked = s2.button(
                "Load scenario",
                use_container_width=True,
                key="econ_load_scenario",
            )
            if load_clicked and selected_scenario != "—":
                saved = saved_scenarios[selected_scenario]
                field_map = {
                    "currency": "econ_currency",
                    "area": "econ_area",
                    "rent": "econ_rent",
                    "capex": "econ_capex",
                    "annual_sales": "econ_sales",
                    "gross_margin": "econ_margin",
                    "payroll": "econ_payroll",
                    "utilities": "econ_utilities",
                    "logistics": "econ_logistics",
                    "other_opex": "econ_other_opex",
                }
                for source_key, state_key in field_map.items():
                    if source_key in saved:
                        st.session_state[state_key] = saved[source_key]
                st.session_state["econ_scenario_name"] = selected_scenario
                st.rerun()

        currency = st.selectbox(
            "Currency",
            ["EUR", "USD", "UAH"],
            index=0,
            key="econ_currency",
        )
        currency_symbol = {"EUR": "€", "USD": "$", "UAH": "₴"}[currency]

        e1, e2, e3 = st.columns(3)
        area = e1.number_input(
            "Store area, m²",
            min_value=0.0,
            value=0.0,
            step=100.0,
            key="econ_area",
        )
        rent = e2.number_input(
            f"Rent, {currency}/m²/month",
            min_value=0.0,
            value=0.0,
            step=0.5,
            key="econ_rent",
        )
        capex = e3.number_input(
            f"CAPEX, {currency}",
            min_value=0.0,
            value=0.0,
            step=10000.0,
            key="econ_capex",
        )

        e4, e5, e6 = st.columns(3)
        annual_sales = e4.number_input(
            f"Expected annual sales, {currency}",
            min_value=0.0,
            value=0.0,
            step=100000.0,
            key="econ_sales",
        )
        gross_margin = e5.number_input(
            "Gross margin, %",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key="econ_margin",
        )
        payroll = e6.number_input(
            f"Annual payroll, {currency}",
            min_value=0.0,
            value=0.0,
            step=10000.0,
            key="econ_payroll",
        )

        e7, e8, e9 = st.columns(3)
        utilities = e7.number_input(
            f"Utilities & maintenance / year, {currency}",
            min_value=0.0,
            value=0.0,
            step=5000.0,
            key="econ_utilities",
        )
        logistics = e8.number_input(
            f"Local logistics / year, {currency}",
            min_value=0.0,
            value=0.0,
            step=5000.0,
            key="econ_logistics",
        )
        other_opex = e9.number_input(
            f"Other annual OPEX, {currency}",
            min_value=0.0,
            value=0.0,
            step=5000.0,
            key="econ_other_opex",
        )

        save_col1, save_col2 = st.columns([3, 1])
        scenario_name = save_col1.text_input(
            "Scenario name",
            value=f"{analysis['query']} - Base",
            key="econ_scenario_name",
        )
        if save_col2.button(
            "Save Scenario",
            type="primary",
            use_container_width=True,
            key="econ_save_scenario",
        ):
            clean_name = scenario_name.strip()
            if not clean_name:
                st.warning("Enter a scenario name before saving.")
            else:
                saved_scenarios[clean_name] = {
                    "location": analysis["query"],
                    "currency": currency,
                    "area": area,
                    "rent": rent,
                    "capex": capex,
                    "annual_sales": annual_sales,
                    "gross_margin": gross_margin,
                    "payroll": payroll,
                    "utilities": utilities,
                    "logistics": logistics,
                    "other_opex": other_opex,
                }
                try:
                    persist_saved_scenarios(saved_scenarios)
                    st.success(f"Scenario saved: {clean_name}")
                except OSError as exc:
                    st.error(f"Could not save scenario on this app instance: {exc}")

        annual_rent = area * rent * 12
        gross_profit = annual_sales * gross_margin / 100
        total_fixed_opex = annual_rent + payroll + utilities + logistics + other_opex
        ebitda = gross_profit - total_fixed_opex

        sales_density = annual_sales / area if area > 0 else None
        occupancy_cost = annual_rent / annual_sales * 100 if annual_sales > 0 else None
        ebitda_margin = ebitda / annual_sales * 100 if annual_sales > 0 else None
        payback = capex / ebitda if ebitda > 0 and capex > 0 else None

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Annual rent", f"{currency_symbol}{annual_rent:,.0f}")
        k2.metric("Gross profit", f"{currency_symbol}{gross_profit:,.0f}")
        k3.metric("Estimated EBITDA", f"{currency_symbol}{ebitda:,.0f}")
        k4.metric(
            "EBITDA margin",
            f"{ebitda_margin:.1f}%" if ebitda_margin is not None else "—",
        )

        k5, k6, k7, k8 = st.columns(4)
        k5.metric(
            "Sales density",
            f"{currency_symbol}{sales_density:,.0f}/m²" if sales_density is not None else "—",
        )
        k6.metric(
            "Occupancy cost",
            f"{occupancy_cost:.1f}%" if occupancy_cost is not None else "—",
        )
        k7.metric(
            "CAPEX payback",
            f"{payback:.1f} years" if payback is not None else "—",
        )
        k8.metric("Total fixed OPEX", f"{currency_symbol}{total_fixed_opex:,.0f}")

        assumptions_complete = (
            area > 0
            and rent > 0
            and annual_sales > 0
            and gross_margin > 0
        )

        if assumptions_complete:
            scenarios = []
            for scenario, sales_factor in [
                ("Conservative", 0.85),
                ("Base", 1.00),
                ("Upside", 1.15),
            ]:
                scenario_sales = annual_sales * sales_factor
                scenario_gp = scenario_sales * gross_margin / 100
                scenario_ebitda = scenario_gp - total_fixed_opex
                scenario_margin = (
                    scenario_ebitda / scenario_sales * 100
                    if scenario_sales > 0
                    else None
                )
                scenario_payback = (
                    capex / scenario_ebitda
                    if capex > 0 and scenario_ebitda > 0
                    else None
                )
                scenarios.append(
                    {
                        "Scenario": scenario,
                        f"Sales ({currency})": round(scenario_sales),
                        f"EBITDA ({currency})": round(scenario_ebitda),
                        "EBITDA margin": (
                            f"{scenario_margin:.1f}%"
                            if scenario_margin is not None
                            else "—"
                        ),
                        "CAPEX payback": (
                            f"{scenario_payback:.1f} years"
                            if scenario_payback is not None
                            else "—"
                        ),
                    }
                )

            st.markdown("#### Sales sensitivity")
            st.dataframe(
                pd.DataFrame(scenarios),
                use_container_width=True,
                hide_index=True,
            )

            if ebitda <= 0:
                st.error(
                    "Base case EBITDA is negative with the current assumptions."
                )
            elif payback is not None:
                st.success(
                    f"Base case is EBITDA-positive with estimated CAPEX payback of {payback:.1f} years."
                )
            else:
                st.success("Base case is EBITDA-positive.")
        else:
            st.warning(
                "Enter at least store area, rent, annual sales and gross margin "
                "to activate the scenario analysis."
            )

st.divider()
st.caption(
    "Prototype. Public map/POI data can be incomplete; investment decisions should use verified commercial, "
    "traffic and demographic sources."
)
