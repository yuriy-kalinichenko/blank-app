import csv
import io
import json
import math
import re
import time
from datetime import datetime, timezone
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import pydeck as pdk
import streamlit as st

from project_library import (
    default_project_library,
    export_project_library as serialize_project_library,
    validate_project_library,
)

st.set_page_config(page_title="Jumbo Location Analyzer", page_icon="📍", layout="wide")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
USER_AGENT = "JumboLocationAnalyzer/1.0 (site-selection decision support)"
WORLDPOP_URL = "https://api.worldpop.org/v2"
VALHALLA_ISOCHRONE_URL = "https://valhalla1.openstreetmap.de/isochrone"
VALHALLA_CLIENT_ID = "jumbo-location-analyzer"
DRIVE_TIME_MINUTES = (15, 30, 40)
BUILD_VERSION = "2026-10-04-v1.0-rc1"

PROJECT_STAGE_OPTIONS = [
    "Screening",
    "Due diligence",
    "Negotiation",
    "Approval",
    "Implementation",
    "Open",
    "On hold",
    "Cancelled",
]


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

                with urllib.request.urlopen(req, timeout=10) as response:
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
      nwr(around:{radius},{lat},{lon})["shop"];
      nwr(around:{radius},{lat},{lon})["amenity"="parking"];
      nwr(around:{radius},{lat},{lon})["landuse"="retail"];
      nwr(around:{radius},{lat},{lon})["building"="retail"];
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
                "landuse": tags.get("landuse"),
                "building": tags.get("building"),
                "lat": point_lat,
                "lon": point_lon,
            }
        )
    # De-duplicate OSM objects that can represent the same real-world place
    unique = {}
    for row in rows:
        name = (row.get("name") or "").strip().lower()
        category = row.get("shop") or row.get("amenity") or row.get("landuse") or row.get("building") or ""
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
      way(around:{radius},{lat},{lon})["highway"~"motorway|trunk|primary|secondary|tertiary"];
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



@st.cache_data(ttl=3600)
def fetch_city_gravity_context(lat, lon, radius=1800):
    """Fetch public-place signals that indicate local urban attraction / city gravity."""
    query = f"""
    [out:json][timeout:25];
    (
      nwr(around:{radius},{lat},{lon})["amenity"~"cafe|restaurant|fast_food|cinema|theatre"];
      nwr(around:{radius},{lat},{lon})["tourism"~"attraction|museum|gallery"];
      nwr(around:{radius},{lat},{lon})["leisure"~"park|sports_centre|fitness_centre"];
      nwr(around:{radius},{lat},{lon})["amenity"="marketplace"];
      way(around:{radius},{lat},{lon})["highway"="pedestrian"];
      nwr(around:{radius},{lat},{lon})["place"~"square|neighbourhood"];
    );
    out center tags;
    """
    payload = run_overpass_query(query)
    rows = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        point_lat = element.get("lat") or element.get("center", {}).get("lat")
        point_lon = element.get("lon") or element.get("center", {}).get("lon")
        if point_lat is None or point_lon is None:
            continue
        rows.append(
            {
                "name": tags.get("name") or "Unnamed",
                "amenity": tags.get("amenity"),
                "tourism": tags.get("tourism"),
                "leisure": tags.get("leisure"),
                "highway": tags.get("highway"),
                "place": tags.get("place"),
                "lat": float(point_lat),
                "lon": float(point_lon),
            }
        )
    return rows

def bbox_from_radius(lat, lon, radius_m):
    """Approximate a bounding box for a local OSM Map API fallback."""
    lat_delta = (radius_m / 1000.0) / 110.574
    lon_scale = max(0.01, 111.320 * math.cos(math.radians(lat)))
    lon_delta = (radius_m / 1000.0) / lon_scale
    return (
        lon - lon_delta,
        lat - lat_delta,
        lon + lon_delta,
        lat + lat_delta,
    )


@st.cache_data(ttl=3600)
def fetch_osm_map_elements(lat, lon, radius_m):
    """Fetch raw OSM elements from tiled standard Map API requests for local resilience."""
    west, south, east, north = bbox_from_radius(lat, lon, radius_m)
    # Split into a 3x3 grid. Smaller tiles are more reliable in dense urban areas.
    steps = 3
    lon_step = (east - west) / steps
    lat_step = (north - south) / steps
    merged = {}
    tile_errors = []
    for ix in range(steps):
        for iy in range(steps):
            tw = west + ix * lon_step
            te = west + (ix + 1) * lon_step
            ts = south + iy * lat_step
            tn = south + (iy + 1) * lat_step
            bbox = f"{tw:.6f},{ts:.6f},{te:.6f},{tn:.6f}"
            url = "https://api.openstreetmap.org/api/0.6/map.json?" + urllib.parse.urlencode({"bbox": bbox})
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                elements = payload.get("elements")
                if not isinstance(elements, list):
                    tile_errors.append(f"{bbox}: no elements list")
                    continue
                for element in elements:
                    key = (element.get("type"), element.get("id"))
                    merged[key] = element
            except Exception as exc:
                tile_errors.append(f"{bbox}: {exc}")
    if not merged:
        raise RuntimeError("OSM Map API tiles returned no elements. " + " | ".join(tile_errors))
    return list(merged.values())


def osm_element_point(element, node_lookup):
    """Return a representative point for a node/way/relation from raw Map API data."""
    if element.get("type") == "node":
        if element.get("lat") is not None and element.get("lon") is not None:
            return float(element["lat"]), float(element["lon"])
        return None, None

    node_ids = element.get("nodes") or []
    coords = [node_lookup.get(node_id) for node_id in node_ids if node_lookup.get(node_id)]
    if coords:
        lat = sum(p[0] for p in coords) / len(coords)
        lon = sum(p[1] for p in coords) / len(coords)
        return lat, lon

    return None, None


@st.cache_data(ttl=3600)
def fetch_osm_map_retail(lat, lon, radius=3000):
    """Keyless retail fallback using the standard OSM Map API."""
    elements = fetch_osm_map_elements(lat, lon, radius)
    node_lookup = {
        e["id"]: (float(e["lat"]), float(e["lon"]))
        for e in elements
        if e.get("type") == "node" and e.get("lat") is not None and e.get("lon") is not None
    }
    rows = []
    for element in elements:
        tags = element.get("tags") or {}
        shop = tags.get("shop")
        amenity = tags.get("amenity")
        landuse = tags.get("landuse")
        building = tags.get("building")
        if not shop and amenity != "parking" and landuse != "retail" and building != "retail":
            continue
        point_lat, point_lon = osm_element_point(element, node_lookup)
        if point_lat is None or point_lon is None:
            continue
        rows.append(
            {
                "name": tags.get("name") or tags.get("brand") or "Unnamed",
                "shop": shop,
                "amenity": amenity,
                "landuse": landuse,
                "building": building,
                "lat": point_lat,
                "lon": point_lon,
            }
        )

    unique = {}
    for row in rows:
        name = (row.get("name") or "").strip().lower()
        category = row.get("shop") or row.get("amenity") or row.get("landuse") or row.get("building") or ""
        lat_key = round(row["lat"], 4)
        lon_key = round(row["lon"], 4)
        key = (name, category) if name and name != "unnamed" else (category, lat_key, lon_key)
        unique[key] = row
    return list(unique.values())


@st.cache_data(ttl=3600)
def fetch_osm_map_access(lat, lon, radius=1500):
    """Keyless access fallback using the standard OSM Map API."""
    elements = fetch_osm_map_elements(lat, lon, max(radius, 2500))
    node_lookup = {
        e["id"]: (float(e["lat"]), float(e["lon"]))
        for e in elements
        if e.get("type") == "node" and e.get("lat") is not None and e.get("lon") is not None
    }

    allowed_highways = {"motorway", "trunk", "primary", "secondary", "tertiary", "bus_stop"}
    allowed_railway = {"tram_stop", "station", "halt", "subway_entrance"}
    rows = []
    for element in elements:
        tags = element.get("tags") or {}
        highway = tags.get("highway")
        public_transport = tags.get("public_transport")
        railway = tags.get("railway")
        if (
            highway not in allowed_highways
            and public_transport != "platform"
            and railway not in allowed_railway
        ):
            continue
        point_lat, point_lon = osm_element_point(element, node_lookup)
        if point_lat is None or point_lon is None:
            continue
        rows.append(
            {
                "name": tags.get("name") or tags.get("ref") or "Unnamed",
                "highway": highway,
                "public_transport": public_transport,
                "railway": railway,
                "lat": point_lat,
                "lon": point_lon,
            }
        )

    unique = {}
    for row in rows:
        category = row.get("highway") or row.get("public_transport") or row.get("railway") or ""
        name = (row.get("name") or "").strip().lower()
        key = (category, name, round(row["lat"], 4), round(row["lon"], 4))
        unique[key] = row
    return list(unique.values())


def fetch_access_with_fallback(lat, lon, radius=1500):
    diagnostics = []
    providers = [
        ("OpenStreetMap / Overpass", lambda: fetch_access_context(lat, lon, radius)),
        ("OpenStreetMap Map API", lambda: fetch_osm_map_access(lat, lon, radius)),
    ]
    successful_empty = []
    for provider_name, loader in providers:
        try:
            rows = loader()
            if rows:
                return rows, provider_name, diagnostics
            successful_empty.append(provider_name)
            diagnostics.append(f"{provider_name}: responded successfully but returned 0 matching access features")
        except Exception as exc:
            diagnostics.append(f"{provider_name}: {exc}")
    if successful_empty:
        return [], " + ".join(successful_empty), diagnostics
    raise RuntimeError("All access providers failed. " + " | ".join(diagnostics))



def get_secret(name):
    """Return an optional Streamlit secret without failing when secrets are not configured."""
    try:
        value = st.secrets.get(name)
        return str(value).strip() if value else None
    except Exception:
        return None


@st.cache_data(ttl=3600)
def fetch_google_retail(lat, lon, radius=3000, api_key=None):
    """Fallback retail POIs from Google Places Nearby Search (New)."""
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")

    url = "https://places.googleapis.com/v1/places:searchNearby"
    body = json.dumps(
        {
            "includedTypes": [
                "toy_store",
                "department_store",
                "shopping_mall",
                "supermarket",
                "furniture_store",
                "home_goods_store",
                "gift_shop",
            ],
            "maxResultCount": 20,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": float(min(radius, 50000)),
                }
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType,places.types",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    type_map = {
        "toy_store": "toys",
        "department_store": "department_store",
        "shopping_mall": "mall",
        "supermarket": "supermarket",
        "furniture_store": "furniture",
        "home_goods_store": "houseware",
        "gift_shop": "gift",
    }
    rows = []
    for place in payload.get("places", []):
        primary = place.get("primaryType")
        mapped = type_map.get(primary)
        if not mapped:
            for candidate in place.get("types", []):
                if candidate in type_map:
                    mapped = type_map[candidate]
                    break
        location = place.get("location", {})
        if not mapped or location.get("latitude") is None or location.get("longitude") is None:
            continue
        rows.append(
            {
                "name": (place.get("displayName") or {}).get("text") or "Unnamed",
                "shop": mapped if mapped != "mall" else "mall",
                "amenity": None,
                "lat": float(location["latitude"]),
                "lon": float(location["longitude"]),
            }
        )
    return rows


@st.cache_data(ttl=3600)
def fetch_here_retail(lat, lon, radius=3000, api_key=None):
    """Second fallback retail POIs from HERE Geocoding & Search Discover."""
    if not api_key:
        raise RuntimeError("HERE_API_KEY is not configured")

    queries = [
        ("toy store", "toys"),
        ("variety store", "variety_store"),
        ("department store", "department_store"),
        ("supermarket", "supermarket"),
        ("furniture store", "furniture"),
        ("home goods", "houseware"),
        ("gift shop", "gift"),
        ("stationery", "stationery"),
        ("shopping mall", "mall"),
    ]
    rows = []
    for query, shop_type in queries:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "in": f"circle:{lat},{lon};r={int(radius)}",
                "limit": 20,
                "apiKey": api_key,
            }
        )
        req = urllib.request.Request(
            f"https://discover.search.hereapi.com/v1/discover?{params}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for item in payload.get("items", []):
            position = item.get("position") or {}
            if position.get("lat") is None or position.get("lng") is None:
                continue
            rows.append(
                {
                    "name": item.get("title") or "Unnamed",
                    "shop": shop_type,
                    "amenity": None,
                    "lat": float(position["lat"]),
                    "lon": float(position["lng"]),
                }
            )

    unique = {}
    for row in rows:
        key = (
            (row.get("name") or "").strip().lower(),
            row.get("shop") or "",
            round(row["lat"], 4),
            round(row["lon"], 4),
        )
        unique[key] = row
    return list(unique.values())


def fetch_retail_with_fallback(lat, lon, radius=3000):
    """Try independent providers in order; return real data only, never fabricated values."""
    diagnostics = []
    providers = [
        ("OpenStreetMap / Overpass", lambda: fetch_nearby_retail(lat, lon, radius)),
        ("OpenStreetMap Map API", lambda: fetch_osm_map_retail(lat, lon, radius)),
    ]
    google_key = get_secret("GOOGLE_MAPS_API_KEY")
    here_key = get_secret("HERE_API_KEY")
    if google_key:
        providers.append(
            (
                "Google Places",
                lambda: fetch_google_retail(lat, lon, radius, api_key=google_key),
            )
        )
    else:
        diagnostics.append("Google Places: not configured (missing GOOGLE_MAPS_API_KEY)")
    if here_key:
        providers.append(
            (
                "HERE Discover",
                lambda: fetch_here_retail(lat, lon, radius, api_key=here_key),
            )
        )
    else:
        diagnostics.append("HERE Discover: not configured (missing HERE_API_KEY)")
    successful_empty = []
    for provider_name, loader in providers:
        try:
            rows = loader()
            if rows:
                return rows, provider_name, diagnostics
            successful_empty.append(provider_name)
            diagnostics.append(f"{provider_name}: responded successfully but returned 0 matching retail POIs")
        except Exception as exc:
            diagnostics.append(f"{provider_name}: {exc}")
    if successful_empty:
        return [], " + ".join(successful_empty), diagnostics
    raise RuntimeError("All retail providers failed. " + " | ".join(diagnostics))


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


def normalize_isochrone_geojson(payload):
    """Normalize Valhalla contour metadata so the UI can render it consistently."""
    normalized = {"type": "FeatureCollection", "features": []}
    if not isinstance(payload, dict):
        return normalized

    for feature in payload.get("features", []):
        if not isinstance(feature, dict) or not feature.get("geometry"):
            continue
        properties = dict(feature.get("properties") or {})
        raw_minutes = properties.get("contour", properties.get("time"))
        try:
            minutes = int(round(float(raw_minutes)))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None:
            properties["minutes"] = minutes
        normalized["features"].append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": properties,
            }
        )
    return normalized


@st.cache_data(ttl=3600)
def fetch_drive_time_isochrones(lat, lon, minutes=DRIVE_TIME_MINUTES):
    """Fetch real car drive-time polygons from the Valhalla routing demo service."""
    request_payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": "auto",
        "contours": [{"time": int(value)} for value in minutes],
        "polygons": True,
    }
    params = urllib.parse.urlencode(
        {"json": json.dumps(request_payload, separators=(",", ":"))}
    )
    req = urllib.request.Request(
        f"{VALHALLA_ISOCHRONE_URL}?{params}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/geo+json, application/json",
            "X-Client-Id": VALHALLA_CLIENT_ID,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    geojson = normalize_isochrone_geojson(payload)
    returned_minutes = {
        feature.get("properties", {}).get("minutes")
        for feature in geojson.get("features", [])
    }
    missing = [value for value in minutes if value not in returned_minutes]
    if missing:
        raise RuntimeError(
            "Valhalla response is missing requested contours: "
            + ", ".join(f"{value} min" for value in missing)
        )
    return geojson


def build_drive_time_proxy_geojson(lat, lon):
    """Clearly labelled fallback circles; never presented as real road-network isochrones."""
    proxy_radii_km = {15: 6, 30: 12, 40: 16}
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "minutes": minutes,
                    "proxy_radius_km": radius_km,
                    "proxy": True,
                },
                "geometry": circle_polygon(lat, lon, radius_km),
            }
            for minutes, radius_km in proxy_radii_km.items()
        ],
    }


def render_drive_time_map(lat, lon, geojson):
    """Render nested drive-time polygons without crowding the main site map."""
    palette = {
        15: ([46, 204, 113, 55], [39, 174, 96, 210]),
        30: ([52, 152, 219, 42], [41, 128, 185, 210]),
        40: ([155, 89, 182, 32], [142, 68, 173, 210]),
    }
    layers = []
    features = geojson.get("features", []) if isinstance(geojson, dict) else []

    # Draw larger contours first so the smaller catchments remain legible.
    for minutes in sorted(DRIVE_TIME_MINUTES, reverse=True):
        selected = [
            feature
            for feature in features
            if feature.get("properties", {}).get("minutes") == minutes
        ]
        if not selected:
            continue
        fill_color, line_color = palette[minutes]
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                {"type": "FeatureCollection", "features": selected},
                filled=True,
                stroked=True,
                pickable=True,
                get_fill_color=fill_color,
                get_line_color=line_color,
                line_width_min_pixels=2,
            )
        )

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            [{"lat": lat, "lon": lon}],
            get_position="[lon, lat]",
            get_radius=180,
            radius_min_pixels=6,
            pickable=False,
        )
    )

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=lat,
            longitude=lon,
            zoom=9.2,
            pitch=0,
        ),
        tooltip={"text": "{minutes} min"},
    )
    st.pydeck_chart(deck, use_container_width=True)


def drive_time_geometry(geojson, minutes):
    """Return the polygon/multipolygon geometry for one drive-time contour."""
    if not isinstance(geojson, dict):
        return None
    for feature in geojson.get("features", []):
        if feature.get("properties", {}).get("minutes") == minutes:
            geometry = feature.get("geometry")
            if isinstance(geometry, dict) and geometry.get("type") in {"Polygon", "MultiPolygon"}:
                return geometry
    return None


@st.cache_data(ttl=86400)
def worldpop_population_geojson(geometry, year=2025):
    """Calculate WorldPop population inside an arbitrary polygon geometry."""
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("WorldPop requires a Polygon or MultiPolygon geometry.")

    payload = {
        "geojson": geometry,
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



@st.cache_data(ttl=86400)
def worldpop_children_geojson(geometry, year=2025, age_range=(0, 18)):
    """Calculate WorldPop age/sex population inside a polygon and return children 0-18."""
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("WorldPop requires a Polygon or MultiPolygon geometry.")

    payload = {
        "geojson": geometry,
        "year": year,
        "age_range": [int(age_range[0]), int(age_range[1])],
        "sex": "both",
        "resolution": "1km",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{WORLDPOP_URL}/agesex",
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
        raise RuntimeError(f"WorldPop age/sex did not return a task_id: {submitted}")

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
                raise RuntimeError(
                    f"WorldPop age/sex success response had no result object: {last_payload}"
                )
            pyramid = result.get("agesex_pyramid") or result.get("agesexpyramid")
            if not isinstance(pyramid, list):
                raise RuntimeError(
                    f"WorldPop age/sex result had no pyramid: {last_payload}"
                )

            total_children = 0.0
            for row in pyramid:
                if not isinstance(row, dict):
                    continue
                if row.get("total") is not None:
                    total_children += float(row.get("total") or 0)
                else:
                    total_children += float(row.get("male") or 0)
                    total_children += float(row.get("female") or 0)

            return {
                "children_population": total_children,
                "age_range": list(age_range),
                "pyramid": pyramid,
            }
        if status == "failure":
            raise RuntimeError(
                last_payload.get("error")
                or f"WorldPop age/sex request failed: {last_payload}"
            )
        time.sleep(1)

    raise TimeoutError(
        f"WorldPop age/sex request timed out. Last response: {last_payload}"
    )


SCENARIO_FILE = "saved_scenarios.json"


def load_saved_scenarios():
    default_scenarios = default_project_library()
    try:
        with open(SCENARIO_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        merged = {}
        if isinstance(data, dict):
            try:
                merged.update(validate_project_library(data))
            except ValueError:
                pass
        for name, project in default_scenarios.items():
            merged.setdefault(name, project)
        return merged
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_scenarios


def persist_saved_scenarios(data):
    with open(SCENARIO_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


PROJECT_FIELD_MAP = {
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


COMMERCIAL_FIELD_ALIASES = {
    "currency": ["currency", "curr", "валюта"],
    "area": ["store area", "area", "sqm", "sq m", "m2", "m²", "площадь", "площа"],
    "rent": ["rent", "base rent", "monthly rent", "rent per sqm", "аренда", "оренда"],
    "capex": ["capex", "investment", "fit out investment", "инвестиции", "інвестиції"],
    "annual_sales": ["annual sales", "expected annual sales", "sales", "revenue", "продажи", "продажі"],
    "gross_margin": ["gross margin", "margin", "gm", "маржа"],
    "payroll": ["annual payroll", "payroll", "staff cost", "personnel cost", "фоп персонала", "зарплата"],
    "utilities": ["utilities", "utilities maintenance", "maintenance", "коммунальные", "комунальні"],
    "logistics": ["local logistics", "logistics", "логистика", "логістика"],
    "other_opex": ["other annual opex", "other opex", "opex", "прочий opex", "інший opex"],
}


def _normalize_commercial_label(value):
    text = str(value or "").strip().lower()
    text = text.replace("²", "2")
    text = re.sub(r"[^a-zа-яіїє0-9]+", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _match_commercial_field(label):
    normalized = _normalize_commercial_label(label)
    if not normalized:
        return None
    for field, aliases in COMMERCIAL_FIELD_ALIASES.items():
        normalized_aliases = [_normalize_commercial_label(alias) for alias in aliases]
        if normalized in normalized_aliases:
            return field
    for field, aliases in COMMERCIAL_FIELD_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalize_commercial_label(alias)
            if alias_norm and alias_norm in normalized:
                return field
    return None


def _parse_commercial_number(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace("\u00a0", " ").replace(" ", "")
    text = re.sub(r"[€$₴%]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        tail = text.rsplit(",", 1)[-1]
        text = text.replace(",", ".") if len(tail) <= 2 else text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _xlsx_first_sheet_rows(file_bytes):
    """Read values from the first XLSX worksheet using only the Python standard library."""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for item in root.findall("m:si", ns):
                shared_strings.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        main_ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rel_ns = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        package_ns = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}

        first_sheet = workbook.find("m:sheets/m:sheet", main_ns)
        if first_sheet is None:
            return []
        rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = None
        for rel in rels.findall("p:Relationship", package_ns):
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib.get("Target")
                break
        if not target:
            return []
        sheet_path = target.lstrip("/")
        if not sheet_path.startswith("xl/"):
            sheet_path = "xl/" + sheet_path

        sheet = ET.fromstring(archive.read(sheet_path))
        rows = []
        for row in sheet.findall(".//m:sheetData/m:row", main_ns):
            values = []
            last_col = 0
            for cell in row.findall("m:c", main_ns):
                ref = cell.attrib.get("r", "")
                letters = re.match(r"[A-Z]+", ref)
                col_index = 0
                if letters:
                    for ch in letters.group(0):
                        col_index = col_index * 26 + (ord(ch) - 64)
                while last_col + 1 < col_index:
                    values.append("")
                    last_col += 1

                cell_type = cell.attrib.get("t")
                value_node = cell.find("m:v", main_ns)
                if cell_type == "inlineStr":
                    text_node = cell.find("m:is/m:t", main_ns)
                    value = text_node.text if text_node is not None else ""
                elif value_node is None:
                    value = ""
                elif cell_type == "s":
                    idx = int(value_node.text)
                    value = shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
                else:
                    value = value_node.text or ""
                values.append(value)
                last_col = col_index or (last_col + 1)
            rows.append(values)
        return rows


def _commercial_rows_from_upload(uploaded_file):
    raw = uploaded_file.getvalue()
    name = (uploaded_file.name or "").lower()
    if name.endswith(".csv"):
        text = raw.decode("utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.reader(io.StringIO(text), dialect))
    if name.endswith(".xlsx"):
        return _xlsx_first_sheet_rows(raw)
    raise ValueError("Use a .csv or .xlsx file.")


def parse_commercial_upload(uploaded_file):
    """Map common CSV/XLSX commercial layouts into the app's economics fields."""
    rows = [
        [str(value).strip() if value is not None else "" for value in row]
        for row in _commercial_rows_from_upload(uploaded_file)
    ]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        raise ValueError("The uploaded file is empty.")

    parsed = {}

    # Wide layout: header row followed by a values row.
    if len(rows) >= 2:
        for idx, header in enumerate(rows[0]):
            field = _match_commercial_field(header)
            if field and idx < len(rows[1]) and rows[1][idx] != "":
                parsed[field] = rows[1][idx]

    # Key/value layout: each row contains a field label and a value.
    for row in rows:
        if not row:
            continue
        field = _match_commercial_field(row[0])
        if field:
            value = next((cell for cell in row[1:] if cell != ""), "")
            if value != "":
                parsed[field] = value

    result = {}
    for field, value in parsed.items():
        if field == "currency":
            currency = str(value).strip().upper()
            if currency in {"EUR", "USD", "UAH"}:
                result[field] = currency
        else:
            number = _parse_commercial_number(value)
            if number is not None:
                result[field] = number

    if not result:
        raise ValueError(
            "No commercial fields were recognized. Use labels such as Store area, Rent, CAPEX, "
            "Annual sales, Gross margin, Payroll, Utilities, Logistics or Other OPEX."
        )
    return result


def apply_project_to_state(project_name, project):
    """Load one saved project into Streamlit state before widgets are rendered."""
    project_location = (project.get("location") or "").strip()
    st.session_state["location_query"] = project_location
    for source_key, state_key in PROJECT_FIELD_MAP.items():
        if source_key in project:
            st.session_state[state_key] = project[source_key]

    st.session_state["project_name_input"] = project_name
    loaded_stage = project.get("stage", "Screening")
    if loaded_stage == "Approved":
        loaded_stage = "Approval"
    elif loaded_stage == "Rejected":
        loaded_stage = "Cancelled"
    if loaded_stage not in PROJECT_STAGE_OPTIONS:
        loaded_stage = "Screening"
    st.session_state["project_stage"] = loaded_stage
    st.session_state["project_next_action"] = project.get("next_action", "")
    st.session_state["project_owner"] = project.get("owner", "")
    st.session_state["project_deadline"] = project.get("deadline", "")
    st.session_state["active_project_name"] = project_name
    st.session_state["econ_scenario_name"] = project_name

    current_analysis = st.session_state.get("analysis")
    if current_analysis and current_analysis.get("query") != project_location:
        st.session_state.pop("analysis", None)


def reset_project_state():
    """Start a clean project without carrying commercial assumptions from another site."""
    st.session_state["location_query"] = ""
    for state_key in PROJECT_FIELD_MAP.values():
        if state_key == "econ_currency":
            st.session_state[state_key] = "EUR"
        else:
            st.session_state[state_key] = 0.0
    st.session_state["project_name_input"] = "New Jumbo project"
    st.session_state["project_stage"] = "Screening"
    st.session_state["project_next_action"] = ""
    st.session_state["project_owner"] = ""
    st.session_state["project_deadline"] = ""
    st.session_state["active_project_name"] = None
    st.session_state["econ_scenario_name"] = "New Jumbo project"
    st.session_state.pop("analysis", None)


def capture_project_from_state(project_name):
    """Serialize the current site and commercial assumptions as one project."""
    project = {
        "schema_version": 2,
        "location": (st.session_state.get("location_query") or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stage": st.session_state.get("project_stage", "Screening"),
        "next_action": (st.session_state.get("project_next_action") or "").strip(),
        "owner": (st.session_state.get("project_owner") or "").strip(),
        "deadline": (st.session_state.get("project_deadline") or "").strip(),
    }
    for source_key, state_key in PROJECT_FIELD_MAP.items():
        project[source_key] = st.session_state.get(state_key)
    return project


def build_project_comparison(projects):
    """Create a transparent commercial comparison from saved project assumptions."""
    rows = []
    for name, project in projects.items():
        area = float(project.get("area") or 0)
        rent = float(project.get("rent") or 0)
        sales = float(project.get("annual_sales") or 0)
        margin = float(project.get("gross_margin") or 0)
        payroll = float(project.get("payroll") or 0)
        utilities = float(project.get("utilities") or 0)
        logistics = float(project.get("logistics") or 0)
        other_opex = float(project.get("other_opex") or 0)
        capex = float(project.get("capex") or 0)

        annual_rent = area * rent * 12
        gross_profit = sales * margin / 100
        ebitda = gross_profit - annual_rent - payroll - utilities - logistics - other_opex
        ebitda_margin = ebitda / sales * 100 if sales > 0 else None
        payback = capex / ebitda if capex > 0 and ebitda > 0 else None
        sales_density = sales / area if area > 0 else None
        occupancy_cost = annual_rent / sales * 100 if sales > 0 else None

        rows.append(
            {
                "Project": name,
                "Stage": project.get("stage", "Screening"),
                "Next action": project.get("next_action", ""),
                "Owner": project.get("owner", ""),
                "Deadline": project.get("deadline", ""),
                "Location": project.get("location", ""),
                "Area, m²": area or None,
                "Annual sales": sales or None,
                "Sales density / m²": round(sales_density) if sales_density is not None else None,
                "EBITDA": round(ebitda) if sales > 0 else None,
                "EBITDA margin, %": round(ebitda_margin, 1) if ebitda_margin is not None else None,
                "Occupancy cost, %": round(occupancy_cost, 1) if occupancy_cost is not None else None,
                "Payback, years": round(payback, 1) if payback is not None else None,
                "CAPEX": capex or None,
                "Currency": project.get("currency", "EUR"),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["_positive_ebitda"] = df["EBITDA"].fillna(float("-inf")) > 0
    df["_payback_sort"] = df["Payback, years"].fillna(float("inf"))
    df["_margin_sort"] = df["EBITDA margin, %"].fillna(float("-inf"))
    df["_density_sort"] = df["Sales density / m²"].fillna(float("-inf"))
    df = df.sort_values(
        by=["_positive_ebitda", "_payback_sort", "_margin_sort", "_density_sort"],
        ascending=[False, True, False, False],
        kind="stable",
    ).reset_index(drop=True)
    df.insert(0, "Commercial priority", range(1, len(df) + 1))
    return df.drop(
        columns=["_positive_ebitda", "_payback_sort", "_margin_sort", "_density_sort"]
    )

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


def search_retail_anchors(city_query, limit_per_query=10):
    """Discover named retail anchors across the city before scoring them."""
    geocoded = geocode_location(city_query)
    if not geocoded:
        return []

    city_lat = geocoded["lat"]
    city_lon = geocoded["lon"]
    anchors = []
    seen = set()

    # Primary route: enumerate named retail destinations from OSM/Overpass.
    query = f"""
    [out:json][timeout:30];
    (
      nwr(around:22000,{city_lat},{city_lon})["name"]["shop"="mall"];
      nwr(around:22000,{city_lat},{city_lon})["name"]["shop"="department_store"];
      nwr(around:22000,{city_lat},{city_lon})["name"]["shop"="supermarket"];
      nwr(around:22000,{city_lat},{city_lon})["name"]["building"="retail"];
      nwr(around:22000,{city_lat},{city_lon})["name"]["landuse"="retail"];
      nwr(around:22000,{city_lat},{city_lon})["name"]["amenity"="marketplace"];
    );
    out center tags;
    """
    try:
        payload = run_overpass_query(query)
        for element in payload.get("elements", []):
            tags = element.get("tags") or {}
            name = (tags.get("name:en") or tags.get("name") or "").strip()
            point_lat = element.get("lat") or element.get("center", {}).get("lat")
            point_lon = element.get("lon") or element.get("center", {}).get("lon")
            if not name or point_lat is None or point_lon is None:
                continue

            kind = (
                tags.get("shop")
                or tags.get("building")
                or tags.get("landuse")
                or tags.get("amenity")
                or "retail"
            )
            key = (round(float(point_lat), 3), round(float(point_lon), 3), name.casefold())
            if key in seen:
                continue
            seen.add(key)
            anchors.append(
                {
                    "name": name,
                    "display_name": name,
                    "lat": float(point_lat),
                    "lon": float(point_lon),
                    "kind": str(kind).lower(),
                }
            )
    except Exception:
        pass

    # Secondary route: broader geocoder discovery for places missing OSM tags.
    queries = [
        f"shopping mall, {city_query}",
        f"shopping centre, {city_query}",
        f"department store, {city_query}",
        f"hypermarket, {city_query}",
        f"retail park, {city_query}",
        f"market, {city_query}",
    ]
    generic_names = {
        "shopping mall",
        "shopping centre",
        "shopping center",
        "department store",
        "hypermarket",
        "retail park",
        "market",
        "marketplace",
    }

    for query_text in queries:
        params = urllib.parse.urlencode(
            {
                "q": query_text,
                "format": "jsonv2",
                "limit": limit_per_query,
                "addressdetails": 1,
                "namedetails": 1,
            }
        )
        req = urllib.request.Request(
            f"{NOMINATIM_URL}?{params}",
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue

        for item in data:
            try:
                a_lat = float(item["lat"])
                a_lon = float(item["lon"])
            except Exception:
                continue

            if distance_km(city_lat, city_lon, a_lat, a_lon) > 25:
                continue

            namedetails = item.get("namedetails") or {}
            display = item.get("display_name") or ""
            name = (
                namedetails.get("name:en")
                or namedetails.get("name")
                or display.split(",")[0].strip()
            )
            if not name or name.casefold() in generic_names:
                continue

            key = (round(a_lat, 3), round(a_lon, 3), name.casefold())
            if key in seen:
                continue
            seen.add(key)
            anchors.append(
                {
                    "name": name,
                    "display_name": display or name,
                    "lat": a_lat,
                    "lon": a_lon,
                    "kind": (item.get("type") or item.get("class") or "retail").lower(),
                }
            )

    # Prefer true destination-retail formats, but never hard-code a named mall.
    kind_priority = {
        "mall": 0,
        "department_store": 1,
        "retail": 2,
        "supermarket": 3,
        "marketplace": 4,
    }
    anchors.sort(
        key=lambda a: (
            kind_priority.get(str(a.get("kind") or "").lower(), 5),
            distance_km(city_lat, city_lon, a["lat"], a["lon"]) or 0,
        )
    )
    return anchors[:40]


def golden_format_suitability(anchor_kind, retail_count, named_count=0):
    """Return a transparent 0-15 format-fit score for a large-format Jumbo store."""
    kind = (anchor_kind or "").lower()
    if any(token in kind for token in ("mall", "shopping_centre", "shopping_center", "retail")):
        base = 12.0
    elif any(token in kind for token in ("hypermarket", "department_store")):
        base = 10.0
    elif "supermarket" in kind:
        base = 3.5
    elif "market" in kind or "marketplace" in kind:
        base = 1.5
    else:
        base = 4.0
    cluster_bonus = min(3.0, retail_count / 6.0 + named_count / 10.0)
    return min(15.0, base + cluster_bonus)


def golden_corridor_score(access_rows):
    """Return 0-12 score based on major-road / public transport strength."""
    major_weights = {
        "motorway": 4.0,
        "trunk": 3.5,
        "primary": 2.5,
        "secondary": 1.5,
        "tertiary": 0.8,
        "bus_stop": 0.25,
    }
    score = 0.0
    seen = set()
    for row in access_rows or []:
        highway = row.get("highway")
        railway = row.get("railway")
        public_transport = row.get("public_transport")
        signature = (highway, railway, public_transport, row.get("name"))
        if signature in seen:
            continue
        seen.add(signature)
        if highway in major_weights:
            score += major_weights[highway]
        elif railway in {"station", "halt", "subway_entrance"}:
            score += 1.2
        elif public_transport == "platform":
            score += 0.4
    return min(12.0, score)


def golden_distance_penalty(distance_from_city_km, corridor_score, format_score):
    """Penalize fringe sites unless distance is justified by a true destination-retail format."""
    d = float(distance_from_city_km or 0.0)
    if d <= 4:
        return 0.0

    # Corridor alone is not enough. Protection only becomes strong when
    # large-format suitability is also high.
    corridor_factor = min(1.0, float(corridor_score or 0.0) / 12.0)
    format_factor = min(1.0, float(format_score or 0.0) / 15.0)
    protection = corridor_factor * format_factor

    raw = min(20.0, max(0.0, d - 4.0) * 1.6)
    return raw * (1.0 - 0.65 * protection)


def golden_investability_gate(distance_km_value, gravity_count, format_score, retail_count, corridor_score):
    """Apply a hard screening gate so a road corridor alone cannot become the #1 Jumbo site."""
    d = float(distance_km_value or 0.0)
    gravity = int(gravity_count or 0)
    fmt = float(format_score or 0.0)
    retail = int(retail_count or 0)
    corridor = float(corridor_score or 0.0)

    # Far-fringe site with no local gravity needs proof of destination-retail strength.
    if d > 10 and gravity == 0:
        if fmt < 10 or retail < 6:
            return {
                "cap": 49.0,
                "status": "Watchlist",
                "reason": "Far from city centre with zero City Gravity and insufficient destination-retail strength",
            }
        if corridor >= 10 and fmt >= 10 and retail >= 6:
            return {
                "cap": 65.0,
                "status": "Needs demand proof",
                "reason": "Strong corridor, but catchment/demand must be proven before investment ranking",
            }

    return {"cap": 95.0, "status": "Screening", "reason": ""}

def build_golden_spot_candidates(city_query, max_results=5):
    """Screen a city for strong retail zones with resilient open-data fallbacks."""
    geocoded = geocode_location(city_query)
    if not geocoded:
        return [], None

    lat = geocoded["lat"]
    lon = geocoded["lon"]

    retail = []
    access = []
    try:
        retail = fetch_nearby_retail(lat, lon, radius=12000)
    except Exception:
        try:
            retail = fetch_osm_map_retail(lat, lon, radius=6000)
        except Exception:
            retail = []

    try:
        access = fetch_access_context(lat, lon, radius=6000)
    except Exception:
        access = []

    usable = [
        row for row in retail
        if row.get("lat") is not None and row.get("lon") is not None
    ]

    candidates = []

    # Route A: cluster retail objects returned for the city.
    if usable:
        buckets = {}
        for row in usable:
            b_lat = round(float(row["lat"]), 2)
            b_lon = round(float(row["lon"]), 2)
            key = (b_lat, b_lon)
            bucket = buckets.setdefault(
                key,
                {"lat": [], "lon": [], "retail": [], "named": set()},
            )
            bucket["lat"].append(float(row["lat"]))
            bucket["lon"].append(float(row["lon"]))
            bucket["retail"].append(row)
            name = (row.get("name") or "").strip()
            if name and name.lower() != "unnamed":
                bucket["named"].add(name)

        for bucket in buckets.values():
            center_lat = sum(bucket["lat"]) / len(bucket["lat"])
            center_lon = sum(bucket["lon"]) / len(bucket["lon"])
            retail_count = len(bucket["retail"])
            named_count = len(bucket["named"])

            access_count = 0
            for item in access:
                a_lat = item.get("lat")
                a_lon = item.get("lon")
                if a_lat is None or a_lon is None:
                    continue
                if distance_km(center_lat, center_lon, float(a_lat), float(a_lon)) <= 1.5:
                    access_count += 1

            try:
                gravity_count = len(fetch_city_gravity_context(center_lat, center_lon, radius=1800))
            except Exception:
                gravity_count = 0

            local_access_rows = []
            for item in access:
                a_lat = item.get("lat")
                a_lon = item.get("lon")
                if a_lat is None or a_lon is None:
                    continue
                if distance_km(center_lat, center_lon, float(a_lat), float(a_lon)) <= 1.5:
                    local_access_rows.append(item)

            corridor_component = golden_corridor_score(local_access_rows)
            format_component = golden_format_suitability(
                "retail_cluster", retail_count, named_count
            )
            city_distance_km = distance_km(lat, lon, center_lat, center_lon) or 0.0
            distance_penalty = golden_distance_penalty(
                city_distance_km, corridor_component, format_component
            )
            weak_gravity_penalty = 4.0 if gravity_count == 0 and city_distance_km > 8 else 0.0

            retail_component = min(30.0, retail_count * 1.15 + named_count * 1.1)
            access_component = min(13.0, access_count * 0.75)
            gravity_component = min(15.0, gravity_count * 0.45)
            base_component = 15.0
            score = max(
                0.0,
                min(
                    95.0,
                    base_component
                    + retail_component
                    + access_component
                    + gravity_component
                    + corridor_component
                    + format_component
                    - distance_penalty
                    - weak_gravity_penalty,
                ),
            )
            investability = golden_investability_gate(
                city_distance_km,
                gravity_count,
                format_component,
                retail_count,
                corridor_component,
            )
            score = min(score, investability["cap"])
            top_names = sorted(bucket["named"])[:3]
            label = (
                " / ".join(top_names)
                if top_names
                else f"Retail cluster {center_lat:.3f}, {center_lon:.3f}"
            )
            reasons = [
                f"{retail_count} retail / commercial objects in the local cluster",
                f"{access_count} major-road / public-transport access objects within ~1.5 km",
                f"{gravity_count} city-gravity signals nearby (food, leisure, tourism, pedestrian activity)",
                f"Traffic corridor score {corridor_component:.1f}/12",
                f"Large-format suitability {format_component:.1f}/15",
                f"Distance from city centre {city_distance_km:.1f} km; penalty {distance_penalty:.1f}",
                f"Weak-gravity penalty {weak_gravity_penalty:.1f}",
            ]
            if investability["reason"]:
                reasons.append("Screening gate: " + investability["reason"])
            if top_names:
                reasons.append("Recognisable retail anchors: " + ", ".join(top_names))

            candidates.append(
                {
                    "label": label,
                    "address": f"{center_lat:.6f}, {center_lon:.6f}",
                    "lat": center_lat,
                    "lon": center_lon,
                    "score": round(score, 1),
                    "score_base": round(base_component, 1),
                    "score_retail": round(retail_component, 1),
                    "score_access": round(access_component, 1),
                    "score_gravity": round(gravity_component, 1),
                    "score_corridor": round(corridor_component, 1),
                    "score_format": round(format_component, 1),
                    "score_penalty": round(distance_penalty + weak_gravity_penalty, 1),
                    "distance_city_km": round(city_distance_km, 1),
                    "retail_count": retail_count,
                    "access_count": access_count,
                    "gravity_count": gravity_count,
                    "reasons": reasons,
                    "confidence": "Medium" if retail_count >= 5 else "Low",
                    "screening_status": investability["status"],
                    "source": "retail-cluster",
                }
            )

    # Route B: independent named-anchor discovery. This prevents a temporary
    # Overpass/OSM density failure from incorrectly producing an empty shortlist.
    anchors = search_retail_anchors(city_query)
    for anchor in anchors:
        a_lat = anchor["lat"]
        a_lon = anchor["lon"]

        local_retail = []
        local_access = []
        try:
            local_retail = fetch_nearby_retail(a_lat, a_lon, radius=2200)
        except Exception:
            pass
        try:
            local_access = fetch_access_context(a_lat, a_lon, radius=1500)
        except Exception:
            pass

        retail_count = len(
            [
                row for row in local_retail
                if row.get("lat") is not None and row.get("lon") is not None
            ]
        )
        access_count = len(
            [
                row for row in local_access
                if row.get("lat") is not None and row.get("lon") is not None
            ]
        )

        # Even when enrichment calls fail, a named mapped retail anchor is still
        # useful as a low-confidence screening candidate rather than "no result".
        try:
            gravity_count = len(fetch_city_gravity_context(a_lat, a_lon, radius=1800))
        except Exception:
            gravity_count = 0

        corridor_component = golden_corridor_score(local_access)
        format_component = golden_format_suitability(
            anchor.get("kind"), retail_count, 1
        )
        city_distance_km = distance_km(lat, lon, a_lat, a_lon) or 0.0
        distance_penalty = golden_distance_penalty(
            city_distance_km, corridor_component, format_component
        )
        weak_gravity_penalty = 4.0 if gravity_count == 0 and city_distance_km > 8 else 0.0

        retail_component = min(30.0, retail_count * 1.2)
        access_component = min(13.0, access_count * 0.75)
        gravity_component = min(15.0, gravity_count * 0.45)
        base_component = 15.0
        score = max(
            0.0,
            min(
                95.0,
                base_component
                + retail_component
                + access_component
                + gravity_component
                + corridor_component
                + format_component
                - distance_penalty
                - weak_gravity_penalty,
            ),
        )
        investability = golden_investability_gate(
            city_distance_km,
            gravity_count,
            format_component,
            retail_count,
            corridor_component,
        )
        score = min(score, investability["cap"])
        confidence = "Medium" if retail_count >= 4 else "Low"
        reasons = [f"Named retail anchor: {anchor['name']}"]
        if retail_count:
            reasons.append(f"{retail_count} mapped retail objects within ~2.2 km")
        else:
            reasons.append("Local retail-density enrichment unavailable; anchor retained for screening")
        if access_count:
            reasons.append(f"{access_count} mapped access / transport objects within ~1.5 km")
        reasons.append(
            f"{gravity_count} city-gravity signals nearby (food, leisure, tourism, pedestrian activity)"
        )
        reasons.append(f"Traffic corridor score {corridor_component:.1f}/12")
        reasons.append(f"Large-format suitability {format_component:.1f}/15")
        reasons.append(
            f"Distance from city centre {city_distance_km:.1f} km; penalty {distance_penalty:.1f}"
        )
        reasons.append(f"Weak-gravity penalty {weak_gravity_penalty:.1f}")
        if investability["reason"]:
            reasons.append("Screening gate: " + investability["reason"])

        candidates.append(
            {
                "label": anchor["name"],
                "address": anchor.get("display_name") or anchor["name"],
                "lat": a_lat,
                "lon": a_lon,
                "score": round(score, 1),
                "score_base": round(base_component, 1),
                "score_retail": round(retail_component, 1),
                "score_access": round(access_component, 1),
                "score_gravity": round(gravity_component, 1),
                "score_corridor": round(corridor_component, 1),
                "score_format": round(format_component, 1),
                "score_penalty": round(distance_penalty + weak_gravity_penalty, 1),
                "distance_city_km": round(city_distance_km, 1),
                "retail_count": retail_count,
                "access_count": access_count,
                "gravity_count": gravity_count,
                "reasons": reasons,
                "confidence": confidence,
                "screening_status": investability["status"],
                "source": "named-anchor",
            }
        )

    # De-duplicate candidates that represent the same physical area.
    deduped = []
    status_priority = {
        "Screening": 2,
        "Needs demand proof": 1,
        "Watchlist": 0,
    }
    for candidate in sorted(
        candidates,
        key=lambda item: (
            status_priority.get(item.get("screening_status"), 1),
            item["score"],
            item["retail_count"],
            item["access_count"],
            item.get("gravity_count", 0),
        ),
        reverse=True,
    ):
        too_close = any(
            distance_km(
                candidate["lat"],
                candidate["lon"],
                existing["lat"],
                existing["lon"],
            ) <= 0.8
            for existing in deduped
        )
        if not too_close:
            deduped.append(candidate)
        if len(deduped) >= max_results:
            break

    return deduped, geocoded


for state_key, state_value in BASE_ECON_STATE.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_value

if "location_query" not in st.session_state:
    st.session_state["location_query"] = "Karavan Mall, Kyiv"
if "project_name_input" not in st.session_state:
    st.session_state["project_name_input"] = "Karavan Mall, Kyiv - Base"
if "active_project_name" not in st.session_state:
    st.session_state["active_project_name"] = None
if "project_stage" not in st.session_state:
    st.session_state["project_stage"] = "Screening"
if "project_next_action" not in st.session_state:
    st.session_state["project_next_action"] = ""
if "project_owner" not in st.session_state:
    st.session_state["project_owner"] = ""
if "project_deadline" not in st.session_state:
    st.session_state["project_deadline"] = ""
if "project_library" not in st.session_state:
    st.session_state["project_library"] = load_saved_scenarios()


st.title("Jumbo Location Analyzer")
st.caption(f"Build: {BUILD_VERSION}")
st.caption(
    "Site selection & investment screening · catchment, demand, access, competition and economics."
)

saved_projects = st.session_state["project_library"]

# One-time recovery for the Karavan baseline if an earlier Workspace Save
# accidentally replaced its commercial assumptions with zeros.
for _name, _project in saved_projects.items():
    _location = str(_project.get("location") or "").lower()
    _is_karavan = "karavan" in _name.lower() or "karavan" in _location
    _core_values = [
        float(_project.get("area") or 0),
        float(_project.get("rent") or 0),
        float(_project.get("capex") or 0),
        float(_project.get("annual_sales") or 0),
        float(_project.get("gross_margin") or 0),
    ]
    if _is_karavan and not all(value > 0 for value in _core_values):
        _project.update(
            {
                "currency": "EUR",
                "area": 4500.0,
                "rent": 5.0,
                "capex": 2500000.0,
                "annual_sales": 5000000.0,
                "gross_margin": 50.0,
                "payroll": 250000.0,
                "utilities": 120000.0,
                "logistics": 20000.0,
                "other_opex": 100000.0,
                "schema_version": 2,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        try:
            persist_saved_scenarios(saved_projects)
        except OSError:
            pass
        st.session_state["_recovered_project_name"] = _name

_recovered_project_name = st.session_state.pop("_recovered_project_name", None)
if (
    _recovered_project_name
    and st.session_state.get("active_project_name") == _recovered_project_name
):
    apply_project_to_state(
        _recovered_project_name,
        saved_projects[_recovered_project_name],
    )

PROJECT_SELECTOR_PLACEHOLDER = "— Select project —"

pending_load = st.session_state.pop("_pending_project_load", None)
if pending_load and pending_load in saved_projects:
    apply_project_to_state(pending_load, saved_projects[pending_load])
    st.session_state["_pending_project_select"] = pending_load

if st.session_state.pop("_pending_new_project", False):
    reset_project_state()
    st.session_state["_pending_project_select"] = PROJECT_SELECTOR_PLACEHOLDER

golden_pending_name = st.session_state.pop("_golden_pending_name", None)
golden_pending_location = st.session_state.pop("_golden_pending_location", None)
if golden_pending_name:
    st.session_state["project_name_input"] = golden_pending_name
if golden_pending_location:
    st.session_state["location_query"] = golden_pending_location

pending_select = st.session_state.pop("_pending_project_select", None)
if pending_select is not None:
    available_options = [PROJECT_SELECTOR_PLACEHOLDER] + sorted(saved_projects.keys())
    if pending_select in available_options:
        st.session_state["project_selector"] = pending_select

project_flash = st.session_state.pop("_project_flash", None)

def queue_selected_project_load():
    """Selecting a project should load it automatically on the next rerun."""
    selected = st.session_state.get("project_selector")
    if selected and selected != PROJECT_SELECTOR_PLACEHOLDER:
        st.session_state["_pending_project_load"] = selected


with st.container(border=True):
    st.markdown("### Project workspace")
    st.caption("Select a project and it opens automatically. Create, save, rename or delete from one place.")

    if project_flash:
        st.success(project_flash)

    current_project = st.session_state.get("active_project_name")
    current_stage = st.session_state.get("project_stage", "Screening")
    if current_project:
        st.caption(f"Current project: **{current_project}** · {current_stage}")
    else:
        st.caption("Current project: **New unsaved project**")

    project_left, project_middle, project_right = st.columns([1.25, 1, 0.85])
    selected_project = project_left.selectbox(
        "Saved projects",
        [PROJECT_SELECTOR_PLACEHOLDER] + sorted(saved_projects.keys()),
        key="project_selector",
        on_change=queue_selected_project_load,
    )
    project_name = project_middle.text_input(
        "Project name",
        key="project_name_input",
        placeholder="Example: Respublika Park",
    )
    project_right.selectbox(
        "Stage",
        PROJECT_STAGE_OPTIONS,
        key="project_stage",
    )

    workflow_action, workflow_owner, workflow_deadline = st.columns([1.5, 0.8, 0.7])
    workflow_action.text_input(
        "Next action",
        key="project_next_action",
        placeholder="Example: Review lease draft with landlord",
    )
    workflow_owner.text_input(
        "Owner",
        key="project_owner",
        placeholder="Name / team",
    )
    workflow_deadline.text_input(
        "Deadline",
        key="project_deadline",
        placeholder="YYYY-MM-DD",
    )

    # If a stale session already had a selected project when this UI version loaded,
    # make sure the project is loaded even without a fresh selectbox change event.
    if (
        selected_project != PROJECT_SELECTOR_PLACEHOLDER
        and st.session_state.get("active_project_name") != selected_project
        and st.session_state.get("_pending_project_load") != selected_project
    ):
        st.session_state["_pending_project_load"] = selected_project
        st.rerun()

    is_new_project = selected_project == PROJECT_SELECTOR_PLACEHOLDER
    action_new, action_save, action_rename, action_delete = st.columns(4)

    new_project_clicked = action_new.button(
        "＋ New project",
        use_container_width=True,
        key="project_new_v102",
    )
    save_project_clicked = action_save.button(
        "Create project" if is_new_project else "Save changes",
        type="primary",
        use_container_width=True,
        key="project_save_v102",
    )
    rename_project_clicked = action_rename.button(
        "Rename",
        use_container_width=True,
        key="project_rename_v102",
        disabled=is_new_project,
    )
    delete_project_clicked = action_delete.button(
        "Delete",
        use_container_width=True,
        key="project_delete_v102",
        disabled=is_new_project,
    )

    if new_project_clicked:
        st.session_state["_pending_new_project"] = True
        st.rerun()

    if save_project_clicked:
        clean_input_name = project_name.strip()

        if is_new_project:
            target_name = clean_input_name
        else:
            target_name = selected_project
            if clean_input_name and clean_input_name != selected_project:
                st.warning("To change the project name, use Rename.")
                target_name = None

        if target_name is not None:
            if not target_name:
                st.warning("Enter a project name before creating it.")
            elif not (st.session_state.get("location_query") or "").strip():
                st.warning("Enter a location before saving the project.")
            else:
                if is_new_project:
                    saved_projects[target_name] = capture_project_from_state(target_name)
                else:
                    # Workspace Save changes updates project metadata only.
                    # Commercial assumptions are owned by the Commercial Economics
                    # "Save to project" action and must never be overwritten by
                    # zero/empty widget state from a rerun or analysis.
                    existing_project = dict(saved_projects.get(target_name, {}))
                    existing_project["location"] = (
                        st.session_state.get("location_query") or ""
                    ).strip()
                    existing_project["stage"] = st.session_state.get(
                        "project_stage", "Screening"
                    )
                    existing_project["next_action"] = (
                        st.session_state.get("project_next_action") or ""
                    ).strip()
                    existing_project["owner"] = (
                        st.session_state.get("project_owner") or ""
                    ).strip()
                    existing_project["deadline"] = (
                        st.session_state.get("project_deadline") or ""
                    ).strip()
                    existing_project["updated_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    existing_project["schema_version"] = int(
                        existing_project.get("schema_version") or 2
                    )
                    saved_projects[target_name] = existing_project

                st.session_state["project_library"] = saved_projects
                persist_warning = None
                try:
                    persist_saved_scenarios(saved_projects)
                except OSError as exc:
                    persist_warning = str(exc)

                st.session_state["active_project_name"] = target_name
                st.session_state["econ_scenario_name"] = target_name
                st.session_state["_pending_project_select"] = target_name
                if persist_warning:
                    st.session_state["_project_flash"] = (
                        f"{target_name} is saved for this session. "
                        "Server storage is unavailable; use Advanced · import / export for a durable backup."
                    )
                else:
                    st.session_state["_project_flash"] = (
                        f"Project created: {target_name}"
                        if is_new_project
                        else f"Changes saved: {target_name}"
                    )
                st.rerun()

    if rename_project_clicked and not is_new_project:
        clean_name = project_name.strip()
        old_name = selected_project
        if not clean_name:
            st.warning("Enter the new project name first.")
        elif clean_name == old_name:
            st.info("Enter a different name to rename the project.")
        elif clean_name in saved_projects:
            st.warning(f"A project named {clean_name} already exists.")
        else:
            renamed_project = saved_projects.pop(old_name)
            renamed_project["updated_at"] = datetime.now(timezone.utc).isoformat()
            saved_projects[clean_name] = renamed_project
            st.session_state["project_library"] = saved_projects
            try:
                persist_saved_scenarios(saved_projects)
            except OSError:
                pass
            st.session_state["active_project_name"] = clean_name
            st.session_state["econ_scenario_name"] = clean_name
            st.session_state["_pending_project_select"] = clean_name
            st.session_state["_project_flash"] = f"Project renamed: {old_name} → {clean_name}"
            st.rerun()

    if delete_project_clicked and not is_new_project:
        st.session_state["_confirm_delete_project"] = selected_project
        st.rerun()

    confirm_delete = st.session_state.get("_confirm_delete_project")
    if confirm_delete:
        st.warning(f"Delete **{confirm_delete}**? This cannot be undone.")
        confirm_col, cancel_col, _ = st.columns([1, 1, 2])
        if confirm_col.button(
            "Yes, delete",
            type="primary",
            use_container_width=True,
            key="project_delete_confirm_v102",
        ):
            saved_projects.pop(confirm_delete, None)
            st.session_state["project_library"] = saved_projects
            try:
                persist_saved_scenarios(saved_projects)
            except OSError:
                pass
            st.session_state.pop("_confirm_delete_project", None)
            if st.session_state.get("active_project_name") == confirm_delete:
                reset_project_state()
            st.session_state["_pending_project_select"] = PROJECT_SELECTOR_PLACEHOLDER
            st.session_state["_project_flash"] = f"Deleted project: {confirm_delete}"
            st.rerun()

        if cancel_col.button(
            "Cancel",
            use_container_width=True,
            key="project_delete_cancel_v102",
        ):
            st.session_state.pop("_confirm_delete_project", None)
            st.rerun()

    with st.expander("Advanced · import / export", expanded=False):
        st.caption(
            "Use these tools only for backup or moving projects between environments."
        )

        backup_col, import_col = st.columns(2)
        backup_col.download_button(
            "Export library",
            data=serialize_project_library(saved_projects, BUILD_VERSION),
            file_name="jumbo_location_projects.json",
            mime="application/json",
            use_container_width=True,
            key="project_export_library",
        )

        uploaded_library = import_col.file_uploader(
            "Import library",
            type=["json"],
            accept_multiple_files=False,
            key="project_import_library_file",
            label_visibility="collapsed",
        )

        import_clicked = st.button(
            "Import selected file",
            use_container_width=True,
            key="project_import_library_button",
            disabled=uploaded_library is None,
        )

        if import_clicked and uploaded_library is not None:
            try:
                imported_payload = json.loads(
                    uploaded_library.getvalue().decode("utf-8")
                )
                imported_projects = validate_project_library(imported_payload)
                saved_projects.update(imported_projects)
                st.session_state["project_library"] = saved_projects
                try:
                    persist_saved_scenarios(saved_projects)
                except OSError:
                    pass
                st.session_state["_project_flash"] = (
                    f"Imported {len(imported_projects)} project(s). "
                    "Existing projects with the same name were updated."
                )
                st.rerun()
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                st.error(f"Could not import project library: {exc}")

        st.caption(f"Projects in library: {len(saved_projects)}")

    location_ready = bool((st.session_state.get("location_query") or "").strip())
    current_analysis = st.session_state.get("analysis")
    analysis_ready = bool(
        current_analysis
        and current_analysis.get("query") == (st.session_state.get("location_query") or "").strip()
    )
    economics_ready = all(
        float(st.session_state.get(key) or 0) > 0
        for key in ("econ_area", "econ_rent", "econ_capex", "econ_sales", "econ_margin")
    )
    readiness = sum([location_ready, analysis_ready, economics_ready])
    st.caption(
        "Readiness "
        f"{readiness}/3 · Location {'✓' if location_ready else '—'} · "
        f"Live analysis {'✓' if analysis_ready else '—'} · "
        f"Economics {'✓' if economics_ready else '—'}"
    )

active_project_for_card = st.session_state.get("active_project_name")
if active_project_for_card and active_project_for_card in saved_projects:
    card_project = saved_projects[active_project_for_card]
    card_area = float(card_project.get("area") or 0)
    card_rent = float(card_project.get("rent") or 0)
    card_sales = float(card_project.get("annual_sales") or 0)
    card_margin = float(card_project.get("gross_margin") or 0)
    card_payroll = float(card_project.get("payroll") or 0)
    card_utilities = float(card_project.get("utilities") or 0)
    card_logistics = float(card_project.get("logistics") or 0)
    card_other_opex = float(card_project.get("other_opex") or 0)
    card_capex = float(card_project.get("capex") or 0)

    card_annual_rent = card_area * card_rent * 12
    card_gross_profit = card_sales * card_margin / 100
    card_ebitda = (
        card_gross_profit
        - card_annual_rent
        - card_payroll
        - card_utilities
        - card_logistics
        - card_other_opex
    )
    card_ebitda_margin = card_ebitda / card_sales * 100 if card_sales > 0 else None
    card_payback = card_capex / card_ebitda if card_capex > 0 and card_ebitda > 0 else None
    card_sales_density = card_sales / card_area if card_area > 0 else None

    with st.container(border=True):
        st.markdown(f"### Project card · {active_project_for_card}")
        st.caption(
            f"{card_project.get('location', '')} · "
            f"{card_project.get('stage', 'Screening')} · "
            f"{card_project.get('currency', 'EUR')}"
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Area", f"{card_area:,.0f} m²" if card_area > 0 else "—")
        c2.metric("Annual sales", f"{card_sales:,.0f}" if card_sales > 0 else "—")
        c3.metric(
            "EBITDA margin",
            f"{card_ebitda_margin:.1f}%" if card_ebitda_margin is not None else "—",
        )
        c4.metric(
            "Payback",
            f"{card_payback:.1f} years" if card_payback is not None else "—",
        )

        c5, c6, c7, c8 = st.columns(4)
        c5.metric(
            "Sales density",
            f"{card_sales_density:,.0f}/m²" if card_sales_density is not None else "—",
        )
        c6.metric("CAPEX", f"{card_capex:,.0f}" if card_capex > 0 else "—")
        c7.metric("EBITDA", f"{card_ebitda:,.0f}" if card_sales > 0 else "—")
        c8.metric("Stage", card_project.get("stage", "Screening"))

        workflow_bits = []
        if card_project.get("next_action"):
            workflow_bits.append(f"Next: {card_project.get('next_action')}")
        if card_project.get("owner"):
            workflow_bits.append(f"Owner: {card_project.get('owner')}")
        if card_project.get("deadline"):
            workflow_bits.append(f"Deadline: {card_project.get('deadline')}")
        if workflow_bits:
            st.caption(" · ".join(workflow_bits))

        if st.button(
            "Details · map & full analysis",
            type="primary",
            use_container_width=True,
            key=f"project_card_details__{re.sub(r'[^A-Za-z0-9_-]+', '_', active_project_for_card)}",
        ):
            st.session_state["_auto_analyze_project"] = active_project_for_card
            st.session_state["_pending_project_select"] = active_project_for_card
            st.session_state["_project_flash"] = f"Opening full analysis: {active_project_for_card}"
            st.rerun()

        st.caption(
            "Details opens the saved project and refreshes the full location analysis: "
            "Overview, Catchment & demand, Traffic & access, Competition, "
            "Commercial & economics, and Methodology."
        )

comparison_df = build_project_comparison(saved_projects)
if len(comparison_df) >= 2:
    st.markdown("### Portfolio comparison")
    st.caption(
        "Commercial priority uses saved assumptions only: positive EBITDA first, then faster payback, "
        "higher EBITDA margin and higher sales density. It is a screening order, not a final investment approval."
    )

    lead = comparison_df.iloc[0]
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Projects compared", len(comparison_df))
    p2.metric("Commercial priority #1", lead["Project"])
    p3.metric(
        "Priority #1 payback",
        f'{lead["Payback, years"]:.1f} years'
        if pd.notna(lead["Payback, years"])
        else "—",
    )
    p4.metric(
        "Priority #1 EBITDA margin",
        f'{lead["EBITDA margin, %"]:.1f}%'
        if pd.notna(lead["EBITDA margin, %"])
        else "—",
    )

    st.dataframe(
        comparison_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Annual sales": st.column_config.NumberColumn(format="%.0f"),
            "Sales density / m²": st.column_config.NumberColumn(format="%.0f"),
            "EBITDA": st.column_config.NumberColumn(format="%.0f"),
            "EBITDA margin, %": st.column_config.NumberColumn(format="%.1f%%"),
            "Occupancy cost, %": st.column_config.NumberColumn(format="%.1f%%"),
            "Payback, years": st.column_config.NumberColumn(format="%.1f"),
            "CAPEX": st.column_config.NumberColumn(format="%.0f"),
        },
    )

    st.markdown("#### Project pipeline")
    st.caption(
        "Update the stage after each decision meeting. Cancelled projects stay in the history; "
        "Delete is reserved for removing a project completely."
    )
    header_cols = st.columns([1.45, 1.15, 1.7, 0.85, 0.9, 0.55, 0.7])
    for col, label in zip(
        header_cols,
        ["Project", "Stage", "Next action", "Owner", "Deadline", "Save", "Details"],
    ):
        col.caption(label)

    for pipeline_name in comparison_df["Project"].tolist():
        pipeline_project = saved_projects[pipeline_name]
        pipeline_key = re.sub(r"[^A-Za-z0-9_-]+", "_", pipeline_name)
        current_pipeline_stage = pipeline_project.get("stage", "Screening")
        if current_pipeline_stage not in PROJECT_STAGE_OPTIONS:
            current_pipeline_stage = "Screening"
        p_project, p_stage, p_action, p_owner, p_deadline, p_save, p_details = st.columns(
            [1.45, 1.15, 1.7, 0.85, 0.9, 0.55, 0.7]
        )
        p_project.markdown(f"**{pipeline_name}**")
        pipeline_stage = p_stage.selectbox(
            "Stage",
            PROJECT_STAGE_OPTIONS,
            index=PROJECT_STAGE_OPTIONS.index(current_pipeline_stage),
            key=f"pipeline_stage__{pipeline_key}",
            label_visibility="collapsed",
        )
        pipeline_action = p_action.text_input(
            "Next action",
            value=str(pipeline_project.get("next_action") or ""),
            key=f"pipeline_action__{pipeline_key}",
            label_visibility="collapsed",
        )
        pipeline_owner = p_owner.text_input(
            "Owner",
            value=str(pipeline_project.get("owner") or ""),
            key=f"pipeline_owner__{pipeline_key}",
            label_visibility="collapsed",
        )
        pipeline_deadline = p_deadline.text_input(
            "Deadline",
            value=str(pipeline_project.get("deadline") or ""),
            key=f"pipeline_deadline__{pipeline_key}",
            label_visibility="collapsed",
        )
        if p_save.button(
            "Save",
            key=f"pipeline_save__{pipeline_key}",
            use_container_width=True,
        ):
            pipeline_project["stage"] = pipeline_stage
            pipeline_project["next_action"] = pipeline_action.strip()
            pipeline_project["owner"] = pipeline_owner.strip()
            pipeline_project["deadline"] = pipeline_deadline.strip()
            pipeline_project["updated_at"] = datetime.now(timezone.utc).isoformat()
            saved_projects[pipeline_name] = pipeline_project
            st.session_state["project_library"] = saved_projects
            try:
                persist_saved_scenarios(saved_projects)
            except OSError:
                pass
            if st.session_state.get("active_project_name") == pipeline_name:
                apply_project_to_state(pipeline_name, pipeline_project)
            st.session_state["_pending_project_select"] = pipeline_name
            st.session_state["_project_flash"] = f"Workflow updated: {pipeline_name} · {pipeline_stage}"
            st.rerun()

        if p_details.button(
            "Details",
            key=f"pipeline_details__{pipeline_key}",
            use_container_width=True,
        ):
            # Queue the project load for the next rerun. Calling
            # apply_project_to_state() here would mutate widget-backed
            # session_state keys after those widgets were already rendered,
            # which Streamlit rejects at runtime.
            st.session_state["_pending_project_load"] = pipeline_name
            st.session_state["_pending_project_select"] = pipeline_name
            st.session_state["_auto_analyze_project"] = pipeline_name
            st.session_state["_project_flash"] = f"Opening full analysis: {pipeline_name}"
            st.rerun()

    chart_data = comparison_df.dropna(subset=["EBITDA"]).set_index("Project")[["EBITDA"]]
    if not chart_data.empty:
        st.markdown("#### EBITDA comparison")
        st.bar_chart(chart_data, use_container_width=True)
else:
    st.info(
        "Portfolio comparison will appear after at least two projects are saved. "
        "Add the next location and its commercial assumptions to start comparing."
    )


with st.expander("🌟 Golden Spot workspace", expanded=False):
    st.caption(
        "City-level screening for the strongest retail zones. This is a shortlist tool, "
        "not a replacement for full site due diligence."
    )
    gs_left, gs_right = st.columns([1.6, 0.8])
    gs_city = gs_left.text_input(
        "City / area",
        key="golden_spot_city",
        placeholder="Example: Zhytomyr, Ukraine",
    )
    gs_run = gs_right.button(
        "Find Golden Spots",
        type="primary",
        use_container_width=True,
        key="golden_spot_run",
    )

    if gs_run:
        if not gs_city.strip():
            st.warning("Enter a city or area first.")
        else:
            with st.spinner("Screening retail clusters..."):
                gs_results, gs_meta = build_golden_spot_candidates(gs_city.strip())
            st.session_state["golden_spot_results"] = gs_results
            st.session_state["golden_spot_meta"] = gs_meta

    gs_results = st.session_state.get("golden_spot_results") or []
    gs_meta = st.session_state.get("golden_spot_meta")

    if gs_meta:
        st.caption(f"Search centre: {gs_meta.get('display_name', gs_city)}")

    if gs_results:
        st.markdown("#### Recommended shortlist")

        st.markdown("##### Golden Spot map")
        map_rows = []
        for idx, spot in enumerate(gs_results, start=1):
            map_rows.append(
                {
                    "rank": idx,
                    "name": spot.get("label") or f"Golden Spot #{idx}",
                    "address": spot.get("address") or "",
                    "golden_score": float(spot.get("score") or 0),
                    "confidence": spot.get("confidence") or "",
                    "lat": float(spot["lat"]),
                    "lon": float(spot["lon"]),
                }
            )
        gs_map_df = pd.DataFrame(map_rows)
        if not gs_map_df.empty:
            map_layer = pdk.Layer(
                "ScatterplotLayer",
                data=gs_map_df,
                get_position="[lon, lat]",
                get_radius=220,
                get_fill_color=[245, 183, 0, 210],
                get_line_color=[120, 85, 0, 255],
                line_width_min_pixels=2,
                stroked=True,
                filled=True,
                pickable=True,
                auto_highlight=True,
            )
            label_layer = pdk.Layer(
                "TextLayer",
                data=gs_map_df,
                get_position="[lon, lat]",
                get_text="rank",
                get_size=16,
                get_color=[20, 20, 20, 255],
                get_alignment_baseline="'center'",
                pickable=False,
            )
            st.pydeck_chart(
                pdk.Deck(
                    map_style="https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
                    initial_view_state=pdk.ViewState(
                        latitude=float(gs_map_df["lat"].mean()),
                        longitude=float(gs_map_df["lon"].mean()),
                        zoom=11,
                        pitch=0,
                    ),
                    layers=[map_layer, label_layer],
                    tooltip={
                        "html": (
                            "<b>#{rank} {name}</b><br/>"
                            "{address}<br/>"
                            "Golden Score: {golden_score}<br/>"
                            "Confidence: {confidence}"
                        ),
                        "style": {"backgroundColor": "white", "color": "black"},
                    },
                ),
                use_container_width=True,
            )
        for idx, spot in enumerate(gs_results, start=1):
            with st.container(border=True):
                a, b, c1, d = st.columns([1.7, 0.55, 0.6, 0.65])
                a.markdown(f"**#{idx} · {spot['label']}**")
                b.metric("Golden Score", f"{spot['score']:.1f}/100")
                c1.metric("Confidence", spot["confidence"])
                d.metric("Retail cluster", spot["retail_count"])
                st.caption(f"Screening status: **{spot.get('screening_status', 'Screening')}**")

                st.markdown(
                    "**Score breakdown:** "
                    f"Base {spot.get('score_base', 0):.1f} · "
                    f"Retail {spot.get('score_retail', 0):.1f} · "
                    f"Access {spot.get('score_access', 0):.1f} · "
                    f"City Gravity {spot.get('score_gravity', 0):.1f} · "
                    f"Corridor {spot.get('score_corridor', 0):.1f} · "
                    f"Format {spot.get('score_format', 0):.1f} · "
                    f"Penalty −{spot.get('score_penalty', 0):.1f}"
                )
                for reason in spot["reasons"]:
                    st.write("• " + reason)

                st.caption(
                    "Screening score currently uses retail clustering, access and City Gravity. "
                    "Traffic, income, rent, competition quality and cannibalization will be added as the model evolves."
                )

                if st.button(
                    "Create project from this spot",
                    key=f"golden_create__{idx}",
                    use_container_width=True,
                ):
                    spot_name = f"{gs_city.strip()} · Golden Spot #{idx}"
                    st.session_state["_pending_new_project"] = True
                    st.session_state["_golden_pending_name"] = spot_name
                    st.session_state["_golden_pending_location"] = (
                        f"{spot['lat']:.6f}, {spot['lon']:.6f}"
                    )
                    st.rerun()
    elif gs_meta is not None:
        st.info("No reliable shortlist found from the available open-map data for this search.")


location = st.text_input(
    "Enter address or shopping center",
    key="location_query",
    placeholder="Example: Karavan Mall, Kyiv",
)

analyze = st.button("Analyze location", type="primary")
auto_analyze_project = st.session_state.pop("_auto_analyze_project", None)
auto_analyze = bool(
    auto_analyze_project
    and auto_analyze_project == st.session_state.get("active_project_name")
    and location.strip()
)
if auto_analyze:
    st.info(f"Opening full location analysis for {auto_analyze_project}…")

if analyze or auto_analyze:
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
                        retail, retail_source, retail_diagnostics = fetch_retail_with_fallback(
                            geo["lat"], geo["lon"]
                        )
                        retail_error = None
                        st.session_state["last_good_retail"] = retail
                        st.session_state["last_good_retail_source"] = retail_source
                    except Exception as exc:
                        retail = st.session_state.get("last_good_retail", [])
                        retail_source = st.session_state.get("last_good_retail_source", "Cached previous live result") if retail else None
                        retail_diagnostics = [str(exc)]
                        retail_error = str(exc) if not retail else None

                    access = []
                    access_error = None
                    access_source = None
                    access_diagnostics = []
                    try:
                        access, access_source, access_diagnostics = fetch_access_with_fallback(
                            geo["lat"], geo["lon"]
                        )
                        st.session_state["last_good_access"] = access
                        st.session_state["last_good_access_source"] = access_source
                    except Exception as exc:
                        access = st.session_state.get("last_good_access", [])
                        access_source = st.session_state.get(
                            "last_good_access_source",
                            "Cached previous live result" if access else None,
                        )
                        access_diagnostics = [str(exc)]
                        access_error = str(exc) if not access else None

                    drive_time_error = None
                    drive_time_mode = "live"
                    drive_time_source = "Valhalla road-network isochrones"
                    try:
                        drive_time_geojson = fetch_drive_time_isochrones(
                            geo["lat"], geo["lon"]
                        )
                    except Exception as exc:
                        drive_time_error = str(exc)
                        drive_time_mode = "proxy"
                        drive_time_source = "Fallback distance proxy (not road-network routing)"
                        drive_time_geojson = build_drive_time_proxy_geojson(
                            geo["lat"], geo["lon"]
                        )

                    population = {}
                    population_errors = {}
                    for minutes in DRIVE_TIME_MINUTES:
                        label = f"{minutes} min"
                        geometry = drive_time_geometry(drive_time_geojson, minutes)
                        if geometry is None:
                            population_errors[label] = "Drive-time geometry unavailable"
                            continue
                        try:
                            result = worldpop_population_geojson(
                                geometry,
                                year=2025,
                            )
                            if result.get("total_population") is not None:
                                result = dict(result)
                                result["zone_mode"] = drive_time_mode
                                result["zone_source"] = drive_time_source
                                population[label] = result
                            else:
                                population_errors[label] = "No population value returned"
                        except Exception as exc:
                            population_errors[label] = str(exc)

                    children_population = {}
                    children_population_errors = {}
                    for minutes in DRIVE_TIME_MINUTES:
                        label = f"{minutes} min"
                        geometry = drive_time_geometry(drive_time_geojson, minutes)
                        if geometry is None:
                            children_population_errors[label] = "Drive-time geometry unavailable"
                            continue
                        try:
                            result = worldpop_children_geojson(
                                geometry,
                                year=2025,
                                age_range=(0, 18),
                            )
                            result["zone_mode"] = drive_time_mode
                            result["zone_source"] = drive_time_source
                            children_population[label] = result
                        except Exception as exc:
                            children_population_errors[label] = str(exc)

                    st.session_state["analysis"] = {
                        "query": location.strip(),
                        "geo": geo,
                        "retail": retail,
                        "retail_source": retail_source,
                        "retail_diagnostics": retail_diagnostics,
                        "retail_error": retail_error,
                        "population": population,
                        "population_errors": population_errors,
                        "children_population": children_population,
                        "children_population_errors": children_population_errors,
                        "drive_time_geojson": drive_time_geojson,
                        "drive_time_source": drive_time_source,
                        "drive_time_mode": drive_time_mode,
                        "drive_time_error": drive_time_error,
                        "access": access,
                        "access_source": access_source,
                        "access_diagnostics": access_diagnostics,
                        "access_error": access_error,
                    }
            except Exception as exc:
                st.error(f"Could not locate the site: {exc}")

analysis = st.session_state.get("analysis")

if analysis:
    geo = analysis["geo"]
    retail = analysis["retail"]
    retail_source = analysis.get("retail_source") or "Unknown"
    population = analysis.get("population", {})
    children_population = analysis.get("children_population", {})
    drive_time_geojson = analysis.get("drive_time_geojson", {})
    drive_time_source = analysis.get("drive_time_source") or "Unknown"
    drive_time_mode = analysis.get("drive_time_mode") or "unavailable"
    access = analysis.get("access", [])
    access_source = analysis.get("access_source") or "Unknown"

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
        f"Mapped POIs: {max(len(map_points) - 1, 0)} · Retail source: {retail_source}"
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
        population.get(f"{minutes} min", {}).get("total_population") is not None
        for minutes in DRIVE_TIME_MINUTES
    )
    drive_time_live = (
        drive_time_mode == "live"
        and len(drive_time_geojson.get("features", [])) >= len(DRIVE_TIME_MINUTES)
    )
    children_complete = all(
        children_population.get(f"{minutes} min", {}).get("children_population") is not None
        for minutes in DRIVE_TIME_MINUTES
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
    access_data_ok = not analysis.get("access_error")
    access_complete = access_data_ok
    live_modules = (
        2
        + (1 if retail_data_ok else 0)
        + (1 if population_complete else 0)
        + (1 if access_complete else 0)
        + (1 if drive_time_live else 0)
        + (1 if children_complete else 0)
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Live data coverage", f"{live_modules} / 7 modules")
    c2.metric("Direct competitors / 1 km", len(comp_1km) if retail_data_ok else "No data")
    c3.metric("Direct competitors / 3 km", len(comp_3km) if retail_data_ok else "No data")
    c4.metric("Retail anchors / 3 km", len(anchor_3km) if retail_data_ok else "No data")
    c5.metric("Parking POIs / 1 km", len(parking_1km) if retail_data_ok else "No data")

    if analysis.get("retail_error"):
        st.warning(
            "Retail providers did not return live data in this run. The app shows 'No data' instead of inventing values."
        )
        for diagnostic in analysis.get("retail_diagnostics", []):
            st.code(diagnostic)

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "Executive summary",
            "Catchment & demand",
            "Traffic & access",
            "Competition",
            "Commercial & economics",
            "Methodology",
        ]
    )

    with tab1:
        st.markdown("### Decision dashboard")
        st.info(
            "Decision view combines site geocoding, 15/30/40-minute drive-time catchments, "
            "population and children demand, retail/competition context, access and commercial economics. "
            "Measured footfall and a calibrated Jumbo sales forecast remain separate future data/model layers."
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
                ["Nearby retail / competition", "Live" if retail_data_ok else "Needs retry", retail_source],
                ["Drive-time isochrones", "Live" if drive_time_live else "Fallback proxy", drive_time_source],
                [
                    "Catchment population",
                    ("Live in drive-time polygons" if drive_time_live else "Proxy-zone population")
                    if population_complete
                    else "Needs retry",
                    "WorldPop 2025 inside the displayed 15/30/40-minute zones",
                ],
                [
                    "Children 0-18",
                    "Live" if children_complete else "Needs retry",
                    "WorldPop age/sex inside the displayed 15/30/40-minute zones",
                ],
                ["Traffic & access", "Live proxy" if access_complete else "Needs retry", "OpenStreetMap roads, transit and parking"],
                ["Foot & car traffic counts", "Next layer", "Mobility / traffic provider"],
                ["Sales forecast", "Model layer", "Jumbo benchmarks + local drivers"],
                ["Economics", "Ready", "User commercial assumptions"],
            ],
            columns=["Module", "Status", "Source / method"],
        )
        st.dataframe(coverage, use_container_width=True, hide_index=True)

        comparison_df = build_project_comparison(saved_projects)
        if len(comparison_df) > 1:
            with st.expander("Compare saved projects", expanded=False):
                st.caption(
                    "Commercial comparison uses only the assumptions saved in each project. "
                    "No hidden ranking or invented market data is applied."
                )
                st.dataframe(
                    comparison_df,
                    use_container_width=True,
                    hide_index=True,
                )

    with tab2:
        st.markdown("### Catchment & demand")
        st.caption(f"Build: {BUILD_VERSION}")
        st.write(
            "Primary catchment view: 15-, 30- and 40-minute car reach from the candidate site. "
            "When live routing is available these are road-network isochrones, not simple radii."
        )

        render_drive_time_map(
            geo["lat"],
            geo["lon"],
            drive_time_geojson,
        )

        route_cols = st.columns(3)
        for idx, minutes in enumerate(DRIVE_TIME_MINUTES):
            route_cols[idx].metric(f"{minutes}-min drive zone", "Road network" if drive_time_live else "Proxy")

        if drive_time_live:
            st.success(
                "Drive-time source: Valhalla / OpenStreetMap road network. "
                "Contours shown are real routing isochrones for 15, 30 and 40 minutes."
            )
        else:
            st.warning(
                "Live routing was unavailable, so the map uses clearly labelled distance proxies "
                "(6/12/16 km for 15/30/40 minutes). These are not road-network isochrones."
            )
            if analysis.get("drive_time_error"):
                with st.expander("Drive-time provider diagnostic", expanded=False):
                    st.code(analysis["drive_time_error"])

        st.markdown("#### Population inside catchment")
        st.caption(
            "WorldPop 2025 is calculated inside the same 15/30/40-minute zones shown on the map. "
            "When live routing is available, these are real road-network polygons."
        )

        pop15 = population.get("15 min", {}).get("total_population")
        pop30 = population.get("30 min", {}).get("total_population")
        pop40 = population.get("40 min", {}).get("total_population")

        d1, d2, d3 = st.columns(3)
        d1.metric("15-min population", f"{pop15:,.0f}" if pop15 is not None else "—")
        d2.metric("30-min population", f"{pop30:,.0f}" if pop30 is not None else "—")
        d3.metric("40-min population", f"{pop40:,.0f}" if pop40 is not None else "—")

        if population_complete and drive_time_live:
            st.success(
                "WorldPop status: population loaded for all three real 15/30/40-minute drive-time polygons."
            )
        elif population_complete:
            st.warning(
                "WorldPop loaded for all three displayed zones, but routing is in fallback mode, "
                "so these population values belong to proxy zones rather than true road-network isochrones."
            )
        elif population:
            st.warning(
                "WorldPop returned population for only some catchment zones. "
                "The available values are shown below; retry the analysis for the missing zones."
            )
        else:
            st.warning(
                "WorldPop demographic layer is temporarily unavailable. "
                "Drive-time, retail and access analysis still works."
            )

        rows = []
        for minutes in DRIVE_TIME_MINUTES:
            label = f"{minutes} min"
            item = population.get(label, {})
            if item:
                rows.append(
                    {
                        "Catchment": label,
                        "Population": round(item.get("total_population", 0)),
                        "Area, km²": round(item.get("area_km2", 0), 1)
                        if item.get("area_km2") is not None
                        else None,
                        "Density / km²": round(item.get("population_density", 0))
                        if item.get("population_density") is not None
                        else None,
                        "Zone type": "Road-network isochrone"
                        if item.get("zone_mode") == "live"
                        else "Fallback proxy",
                    }
                )
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        population_errors = analysis.get("population_errors", {})
        if not population_complete and population:
            loaded_labels = ", ".join(sorted(population.keys()))
            st.warning(f"WorldPop status: partial data loaded for {loaded_labels}.")
        elif not population:
            st.error("WorldPop status: no population values loaded.")

        if population_errors:
            st.markdown("#### WorldPop diagnostics")
            for label, error in population_errors.items():
                st.code(f"{label}: {error}")
        elif not population_complete:
            st.code("No detailed WorldPop error was captured in this build.")

        st.markdown("#### Children demand")
        child15 = children_population.get("15 min", {}).get("children_population")
        child30 = children_population.get("30 min", {}).get("children_population")
        child40 = children_population.get("40 min", {}).get("children_population")

        ch1, ch2, ch3 = st.columns(3)
        ch1.metric("Children 0-18 / 15 min", f"{child15:,.0f}" if child15 is not None else "—")
        ch2.metric("Children 0-18 / 30 min", f"{child30:,.0f}" if child30 is not None else "—")
        ch3.metric("Children 0-18 / 40 min", f"{child40:,.0f}" if child40 is not None else "—")

        child_rows = []
        for minutes in DRIVE_TIME_MINUTES:
            label = f"{minutes} min"
            total_population = population.get(label, {}).get("total_population")
            children = children_population.get(label, {}).get("children_population")
            child_share = (
                children / total_population * 100
                if children is not None and total_population
                else None
            )
            if children is not None or total_population is not None:
                child_rows.append(
                    {
                        "Catchment": label,
                        "Total population": round(total_population)
                        if total_population is not None
                        else None,
                        "Children 0-18": round(children)
                        if children is not None
                        else None,
                        "Children share, %": round(child_share, 1)
                        if child_share is not None
                        else None,
                    }
                )

        if child_rows:
            with st.expander("Children profile by catchment", expanded=False):
                st.caption(
                    "This is a demographic demand indicator, not a count of households or families."
                )
                st.dataframe(
                    pd.DataFrame(child_rows),
                    use_container_width=True,
                    hide_index=True,
                )

        children_population_errors = analysis.get("children_population_errors", {})
        if children_complete:
            st.success("WorldPop age/sex status: children 0-18 loaded for all three catchments.")
        elif children_population:
            loaded_labels = ", ".join(sorted(children_population.keys()))
            st.warning(f"Children profile status: partial data loaded for {loaded_labels}.")
        else:
            st.warning("Children 0-18 demographic layer is temporarily unavailable.")

        if children_population_errors:
            with st.expander("Children demographic diagnostics", expanded=False):
                for label, error in children_population_errors.items():
                    st.code(f"{label}: {error}")

    with tab3:
        st.markdown("### Traffic & access")
        st.caption(f"Build: {BUILD_VERSION}")
        st.caption(f"Access provider used for this run: {access_source}")

        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("Access proxy score", f"{access_score}/100" if access_complete else "No data")
        a2.metric(
            "Nearest major road",
            (
                f"{nearest_major_road_km:.2f} km"
                if nearest_major_road_km is not None
                else ("None in 1.5 km" if access_data_ok else "No data")
            ),
        )
        a3.metric("Named major roads / 1.5 km", len(named_major_roads) if access_data_ok else "No data")
        a4.metric("Transit stops / 1.5 km", len(transit_stops) if access_data_ok else "No data")
        a5.metric("Parking POIs / 1 km", len(parking_1km) if retail_data_ok else "No data")

        if access_complete:
            st.success(
                f"Access layer is live from {access_source}. The score is an infrastructure proxy, "
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
        for diagnostic in analysis.get("access_diagnostics", []):
            st.code(diagnostic)

    with tab4:
        st.markdown("### Competition & retail fabric")
        st.caption(f"Build: {BUILD_VERSION}")
        st.caption(
            "Direct competitors = named toy, variety and department-store POIs. "
            "Related home/gift/stationery retail is tracked separately."
        )
        st.caption(f"Retail provider used for this run: {retail_source}")

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
            st.write(f"No named direct competitor POIs were found within 3 km in the {retail_source} retail scan.")
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

        active_project = st.session_state.get("active_project_name")
        if active_project:
            st.caption(f"Active project: {active_project}")
        else:
            st.caption("Active project: unsaved working copy")

        active_saved = saved_projects.get(active_project, {}) if active_project else {}
        is_karavan = bool(
            active_project
            and (
                "karavan" in active_project.lower()
                or "karavan" in str(active_saved.get("location") or "").lower()
            )
        )

        if is_karavan:
            required_saved_keys = ("area", "rent", "capex", "annual_sales", "gross_margin")
            if not all(float(active_saved.get(key) or 0) > 0 for key in required_saved_keys):
                active_saved.update(
                    {
                        "currency": "EUR",
                        "area": 4500.0,
                        "rent": 5.0,
                        "capex": 2500000.0,
                        "annual_sales": 5000000.0,
                        "gross_margin": 50.0,
                        "payroll": 250000.0,
                        "utilities": 120000.0,
                        "logistics": 20000.0,
                        "other_opex": 100000.0,
                        "schema_version": 2,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                saved_projects[active_project] = active_saved
                st.session_state["project_library"] = saved_projects
                try:
                    persist_saved_scenarios(saved_projects)
                except OSError:
                    pass

        st.caption(
            "Enter the commercial assumptions directly below. Results recalculate automatically, "
            "and Save to project stores the values inside the current project."
        )

        project_key = re.sub(r"[^a-zA-Z0-9_-]+", "_", active_project or "working_copy")
        stored_currency = str(active_saved.get("currency") or "EUR")
        if stored_currency not in {"EUR", "USD", "UAH"}:
            stored_currency = "EUR"

        currency = st.selectbox(
            "Currency",
            ["EUR", "USD", "UAH"],
            index=["EUR", "USD", "UAH"].index(stored_currency),
            key=f"commercial_currency__{project_key}",
        )
        currency_symbol = {"EUR": "€", "USD": "$", "UAH": "₴"}[currency]

        e1, e2, e3 = st.columns(3)
        area = e1.number_input(
            "Store area, m²",
            min_value=0.0,
            value=float(active_saved.get("area") or 0),
            step=100.0,
            key=f"commercial_area__{project_key}",
        )
        rent = e2.number_input(
            f"Rent, {currency}/m²/month",
            min_value=0.0,
            value=float(active_saved.get("rent") or 0),
            step=0.5,
            key=f"commercial_rent__{project_key}",
        )
        capex = e3.number_input(
            f"CAPEX, {currency}",
            min_value=0.0,
            value=float(active_saved.get("capex") or 0),
            step=10000.0,
            key=f"commercial_capex__{project_key}",
        )

        e4, e5, e6 = st.columns(3)
        annual_sales = e4.number_input(
            f"Expected annual sales, {currency}",
            min_value=0.0,
            value=float(active_saved.get("annual_sales") or 0),
            step=100000.0,
            key=f"commercial_sales__{project_key}",
        )
        gross_margin = e5.number_input(
            "Gross margin, %",
            min_value=0.0,
            max_value=100.0,
            value=float(active_saved.get("gross_margin") or 0),
            step=0.5,
            key=f"commercial_margin__{project_key}",
        )
        payroll = e6.number_input(
            f"Annual payroll, {currency}",
            min_value=0.0,
            value=float(active_saved.get("payroll") or 0),
            step=10000.0,
            key=f"commercial_payroll__{project_key}",
        )

        e7, e8, e9 = st.columns(3)
        utilities = e7.number_input(
            f"Utilities & maintenance / year, {currency}",
            min_value=0.0,
            value=float(active_saved.get("utilities") or 0),
            step=5000.0,
            key=f"commercial_utilities__{project_key}",
        )
        logistics = e8.number_input(
            f"Local logistics / year, {currency}",
            min_value=0.0,
            value=float(active_saved.get("logistics") or 0),
            step=5000.0,
            key=f"commercial_logistics__{project_key}",
        )
        other_opex = e9.number_input(
            f"Other annual OPEX, {currency}",
            min_value=0.0,
            value=float(active_saved.get("other_opex") or 0),
            step=5000.0,
            key=f"commercial_other_opex__{project_key}",
        )

        save_commercial_clicked = st.button(
            "Save to project",
            type="primary",
            use_container_width=True,
            key=f"commercial_save_to_project__{project_key}",
            disabled=not bool(active_project),
        )
        if save_commercial_clicked:
            required_commercial = {
                "Store area": area,
                "Rent": rent,
                "CAPEX": capex,
                "Annual sales": annual_sales,
                "Gross margin": gross_margin,
            }
            missing_commercial = [
                label for label, value in required_commercial.items() if float(value or 0) <= 0
            ]
            if missing_commercial:
                st.error(
                    "Commercial data was not saved. Fill the required fields first: "
                    + ", ".join(missing_commercial)
                    + "."
                )
            else:
                project_record = dict(saved_projects.get(active_project, {}))
                project_record.update(
                    {
                        "currency": currency,
                        "area": float(area),
                        "rent": float(rent),
                        "capex": float(capex),
                        "annual_sales": float(annual_sales),
                        "gross_margin": float(gross_margin),
                        "payroll": float(payroll),
                        "utilities": float(utilities),
                        "logistics": float(logistics),
                        "other_opex": float(other_opex),
                        "schema_version": 2,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                saved_projects[active_project] = project_record
                st.session_state["project_library"] = saved_projects
                try:
                    persist_saved_scenarios(saved_projects)
                    st.success(f"Commercial data saved to {active_project}.")
                except OSError:
                    st.warning(
                        "Commercial data is saved for this session, but local server storage is unavailable."
                    )

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

    with tab6:
        st.markdown("### Methodology & data dictionary")
        st.caption(f"Build: {BUILD_VERSION}")
        st.write(
            "This page explains what each input means, the unit to enter, the source, and how the app calculates the outputs. "
            "The objective is that another country team can use the model without guessing definitions."
        )

        with st.expander("Advanced · upload commercial file", expanded=False):
            st.caption(
                "Optional only. Use this when a landlord or colleague sends a ready CSV/XLSX file. "
                "For normal work, enter the figures directly above."
            )
            commercial_upload = st.file_uploader(
                "Commercial file",
                type=["csv", "xlsx"],
                accept_multiple_files=False,
                key="commercial_data_upload",
            )
            apply_commercial_upload = st.button(
                "Apply commercial data",
                use_container_width=True,
                key="commercial_data_apply",
                disabled=commercial_upload is None,
            )
            if apply_commercial_upload and commercial_upload is not None:
                try:
                    imported_commercial = parse_commercial_upload(commercial_upload)
                    imported_labels = []
                    for field, value in imported_commercial.items():
                        state_key = PROJECT_FIELD_MAP[field]
                        st.session_state[state_key] = value
                        imported_labels.append(field.replace("_", " "))
                    st.session_state["_commercial_upload_flash"] = (
                        "Commercial data applied: " + ", ".join(imported_labels)
                    )
                    st.rerun()
                except (UnicodeDecodeError, ValueError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
                    st.error(f"Could not read commercial data: {exc}")

        commercial_upload_flash = st.session_state.pop("_commercial_upload_flash", None)
        if commercial_upload_flash:
            st.success(commercial_upload_flash)

        st.markdown("#### Commercial & economics inputs")
        methodology_rows = [
            ["Store area, m²", "Trading / net sales area used for store productivity and rent calculations. Use the same area definition consistently across countries.", "m²", "Lease plan / technical drawings", "Input"],
            ["Rent", "Monthly base rent per m². Enter on the same VAT basis as the rest of the model; recommended comparison basis is excluding recoverable VAT.", "currency / m² / month", "LOI / lease offer", "Input"],
            ["CAPEX", "One-time investment required to open the store: fit-out, MEP, furniture/fixtures, IT/security, signage and other opening investment included in the approved project scope.", "currency", "Project budget", "Input"],
            ["Expected annual sales", "Expected gross merchandise sales for a full 12-month stabilized year. For cross-country comparison, use a consistent VAT convention; recommended management view is net sales excluding VAT.", "currency / year", "Jumbo benchmark + local forecast", "Input"],
            ["Gross margin", "Sales minus cost of goods sold, divided by sales.", "% of sales", "Commercial plan / historical stores", "Input"],
            ["Annual payroll", "Total annual employer cost for the store team, including salaries/wages, employer taxes and regular benefits/bonuses included in local payroll cost.", "currency / year", "HR staffing model", "Input"],
            ["Utilities & maintenance", "Electricity, heating/cooling, water and routine facility/technical maintenance attributable to the store.", "currency / year", "FM budget / benchmarks", "Input"],
            ["Local logistics", "Recurring local inbound / last-mile / store delivery and handling cost included in the site P&L.", "currency / year", "Supply-chain budget", "Input"],
            ["Other annual OPEX", "Recurring store operating costs not already captured above, e.g. security, cleaning, consumables, local services and other site-specific costs.", "currency / year", "Operating budget", "Input"],
        ]
        st.dataframe(
            pd.DataFrame(methodology_rows, columns=["Field", "Definition", "Unit", "Typical source", "Type"]),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("#### Calculated commercial outputs")
        formula_rows = [
            ["Annual rent", "Store area × monthly rent × 12"],
            ["Gross profit", "Expected annual sales × gross margin %"],
            ["Total fixed OPEX", "Annual rent + payroll + utilities & maintenance + local logistics + other OPEX"],
            ["Estimated EBITDA", "Gross profit − total fixed OPEX"],
            ["EBITDA margin", "Estimated EBITDA ÷ annual sales"],
            ["Sales density", "Annual sales ÷ store area"],
            ["Occupancy cost", "Annual rent ÷ annual sales"],
            ["CAPEX payback", "CAPEX ÷ EBITDA, only when EBITDA is positive"],
        ]
        st.dataframe(
            pd.DataFrame(formula_rows, columns=["Output", "Formula"]),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("#### Location-data logic")
        st.write(
            "**Competition:** the app first requests a broad local retail scan and then classifies toy, variety and department stores as direct competitors. If OpenStreetMap/Overpass is unavailable, it can automatically "
            "fall back to Google Places and then HERE Discover when their API keys are configured. No synthetic competitor counts are inserted."
        )
        st.write(
            "**Traffic & access:** the current score uses mapped major roads, public transport and parking as an infrastructure proxy. "
            "It is not a measured car-count or footfall metric. Real traffic counts remain blank until a measured mobility/traffic source is connected."
        )
        st.write(
            "**Catchment:** the app requests 15/30/40-minute car isochrones from Valhalla using the OpenStreetMap road network. "
            "WorldPop population and children 0-18 are calculated inside the same displayed polygons. "
            "If routing is unavailable, the app switches to explicitly labelled 6/12/16 km proxy zones rather than presenting them as true drive-time."
        )

        provider_rows = [
            ["OpenStreetMap / Overpass", "Retail POIs + roads/transit", "Active with multiple public mirrors", "No API key"],
            ["OpenStreetMap Map API", "Emergency local fallback for POIs + roads/transit", "Active for small local bounding boxes", "No API key"],
            ["Valhalla / OpenStreetMap", "15/30/40-minute car isochrones", "Active with explicit proxy fallback", "No API key"],
            ["WorldPop", "Population + age 0-18 inside catchments", "Active when service responds", "No key in current implementation"],
            ["Google Places", "Independent retail fallback", "Ready" if get_secret("GOOGLE_MAPS_API_KEY") else "Not configured", "GOOGLE_MAPS_API_KEY"],
            ["HERE Discover", "Independent retail fallback", "Ready" if get_secret("HERE_API_KEY") else "Not configured", "HERE_API_KEY"],
            ["Measured mobility / traffic provider", "Car counts / footfall", "Not connected", "Future provider"],
        ]
        st.dataframe(
            pd.DataFrame(provider_rows, columns=["Provider", "Role", "Status", "Configuration"]),
            use_container_width=True,
            hide_index=True,
        )
        st.info(
            "Recommended finance convention for cross-country comparison: use net sales and costs excluding recoverable VAT, "
            "then apply the same convention to every store benchmark. If a country team uses a different convention, document it in the scenario."
        )

st.divider()
st.caption(
    "Decision-support release candidate. Public routing, map/POI and demographic sources can be incomplete or temporarily unavailable; "
    "final investment decisions should use verified commercial and measured traffic data."
)
