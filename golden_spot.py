"""Jumbo screening policy: premises first; surrounding POIs are only evidence.

Scores are transparent screening heuristics, not revenue or investment forecasts.
OSM venue tags establish a place to investigate, never available leasable space.
"""

import math
import re

MODEL_VERSION = "jumbo-v4"
VENUE_TYPES = {"mall", "shopping_centre", "shopping_center", "retail_park", "outlet_centre", "outlet_center"}
TAG_KEYS = ("shop", "amenity", "building", "landuse", "highway", "railway", "public_transport", "leisure", "tourism", "place", "brand", "operator", "disused", "abandoned", "access", "parking")


def category(row):
    return str(row.get("shop") or row.get("amenity") or row.get("kind") or row.get("building") or row.get("landuse") or row.get("highway") or row.get("railway") or row.get("leisure") or row.get("tourism") or "unknown").lower().replace(" ", "_")


def classify_object(row):
    """Fail closed: tenant POIs cannot inherit eligibility from building=retail."""
    kind = category(row)
    name = str(row.get("name") or "").strip()
    tags = {**(row.get("tags") or {}), **{k: v for k, v in row.items() if v is not None}}
    inactive = any(str(tags.get(k, "")).lower() in {"yes", "true", "1"} for k in ("disused", "abandoned"))
    inactive = inactive or any(k.startswith(("disused:", "abandoned:", "demolished:")) for k in tags)
    if inactive:
        return "background", "Inactive or disused feature; availability and redevelopment unverified"
    tenant = tags.get("shop")
    amenity = tags.get("amenity")
    if (tenant and tenant not in VENUE_TYPES) or (amenity and amenity not in VENUE_TYPES):
        if amenity == "parking":
            return "background", "Parking supports access; it is not retail premises"
        return "traffic", "Existing business / activity; traffic factor only, not Jumbo premises"
    if not name or name.casefold() in {"unnamed", "unknown", "retail", "mall", "shopping mall"}:
        return "background", "No identifiable premises name"
    if kind in VENUE_TYPES:
        return "candidate", "Mapped shopping destination; verify a suitable Jumbo unit with the landlord"
    if kind in {"retail", "commercial"}:
        return "background", "Generic commercial building / land tag; suitable Jumbo premises not established"
    if kind in {"supermarket", "hypermarket", "department_store", "marketplace", "cafe", "restaurant", "fast_food", "pharmacy", "cinema", "theatre", "sports_centre", "fitness_centre", "attraction", "museum"}:
        return "traffic", "Traffic generator only; no evidence of available Jumbo premises"
    return "background", "Urban / access context; no verified retail premises type"


def distance(a, b):
    p1, p2 = math.radians(float(a["lat"])), math.radians(float(b["lat"]))
    dlat = p2 - p1
    dlon = math.radians(float(b["lon"]) - float(a["lon"]))
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(min(1, math.sqrt(h)))


def identity(row):
    if row.get("osm_id") and row.get("osm_type"):
        return f"{row['osm_type']}/{row['osm_id']}"
    return f"{row.get('name', '').casefold()}|{float(row['lat']):.6f}|{float(row['lon']):.6f}"


def traffic_score(rows):
    # Many small businesses must not overwhelm family-shopping anchors.
    groups = {"shopping": 0.0, "family": 0.0, "food": 0.0, "services": 0.0}
    for row in rows:
        kind = category(row)
        if kind in {"mall", "retail_park", "supermarket", "hypermarket", "department_store", "marketplace"}:
            groups["shopping"] += 3
        elif kind in {"cinema", "theatre", "sports_centre", "attraction", "museum"}:
            groups["family"] += 2
        elif kind in {"cafe", "restaurant", "fast_food"}:
            groups["food"] += 0.2
        else:
            groups["services"] += 0.1
    return min(20.0, min(12, groups["shopping"]) + min(6, groups["family"]) + min(1, groups["food"]) + min(1, groups["services"]))


def score_candidate(venue, inventory, context_available):
    role, reason = classify_object(venue)
    if role != "candidate":
        raise ValueError("Only eligible premises can receive a Jumbo candidate score")
    nearby = [r for r in inventory if identity(r) != identity(venue) and distance(venue, r) <= 2.2]
    traffic = [r for r in nearby if r["role"] == "traffic" or r["role"] == "candidate"]
    access = [r for r in nearby if distance(venue, r) <= 1.5 and (r.get("highway") or r.get("railway") or r.get("public_transport"))]
    # Nearby parking is an access proxy, never proof of rights or capacity.
    parking = [r for r in nearby if distance(venue, r) <= 0.4 and r.get("amenity") == "parking" and r.get("access") not in {"private", "no"}]
    kind = category(venue)
    fit = 40.0 if kind in VENUE_TYPES else 24.0
    support = traffic_score(traffic) if context_available else None
    road_types = {r.get("highway") for r in access}
    car = 15.0 if road_types & {"motorway", "trunk", "primary"} else 10.0 if road_types & {"secondary", "tertiary"} else 0.0
    transit = min(10.0, 2.0 * len({(r.get("name"), r.get("railway"), r.get("public_transport")) for r in access if r.get("highway") == "bus_stop" or r.get("railway") or r.get("public_transport")}))
    access_score = car + transit if context_available else None
    known_capacity = []
    for row in parking:
        raw_capacity = str((row.get("tags") or {}).get("capacity", ""))
        if raw_capacity.isdigit():
            known_capacity.append(int(raw_capacity))
    # Presence is useful; many small lots are not proof of greater capacity.
    parking_score = (15.0 if max(known_capacity, default=0) >= 100 else 10.0 if parking else 0.0) if context_available else None
    components = {"Venue fit": fit, "Shopping / family traffic": support, "Road / transit access": access_score, "Nearby parking": parking_score}
    # Missing components stay unknown; no normalisation or distance-from-centre penalty.
    score = round(sum(v for v in components.values() if v is not None), 1)
    jumbo_nearby = any(re.search(r"\bjumbo\b", " ".join(str(r.get(k, "")) for k in ("name", "brand", "operator")), re.I) for r in nearby)
    return {
        **venue, "candidate_id": identity(venue), "label": venue["name"],
        "address": venue.get("display_name") or venue["name"],
        "score": score, "components": components, "retail_count": len(traffic) if context_available else None,
        "confidence": "Medium" if context_available else "Low",
        "screening_status": "Premises due diligence required",
        "coverage": 100 if context_available else 40,
        "reasons": [reason,
                    "Roads and parking are proximity proxies; entrances, capacity and delivery access are unverified.",
                    "Mapped Jumbo nearby: check network overlap / cannibalisation." if jumbo_nearby else "Existing Jumbo coverage and cannibalisation: not verified.",
                    "Confirm available contiguous area, floor layout, loading, lease, CAPEX, catchment demand and warehouse supply cost."],
    }


def rank_candidates(candidates, max_results=5):
    # Stable, explicit ties; never suppress a different building merely because it is close.
    return sorted(candidates, key=lambda r: (-r["score"], r["name"].casefold(), r["candidate_id"]))[:max(0, max_results)]
