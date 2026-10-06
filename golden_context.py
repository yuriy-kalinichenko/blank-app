"""Shared OSM map tiles covering every candidate's complete evidence radius."""
import math

from golden_spot import TAG_KEYS, distance

CONTEXT_RADIUS_KM = 2.2
TILE_DEGREES = 0.025


def context_tiles(candidates):
    """Aligned tiles are shared by nearby candidates; include boundary neighbours."""
    tiles = set()
    for site in candidates:
        lat, lon = float(site['lat']), float(site['lon'])
        dy = CONTEXT_RADIUS_KM / 110.574
        dx = CONTEXT_RADIUS_KM / max(0.01, 111.320 * math.cos(math.radians(lat)))
        for x in range(math.floor((lon-dx)/TILE_DEGREES), math.floor((lon+dx)/TILE_DEGREES)+1):
            for y in range(math.floor((lat-dy)/TILE_DEGREES), math.floor((lat+dy)/TILE_DEGREES)+1):
                tiles.add((x, y))
    return [(round(x*TILE_DEGREES,6), round(y*TILE_DEGREES,6),
             round((x+1)*TILE_DEGREES,6), round((y+1)*TILE_DEGREES,6))
            for x, y in sorted(tiles)]


def relevant(tags):
    return bool(tags.get('shop') or tags.get('building') == 'retail' or tags.get('landuse') == 'retail'
        or tags.get('amenity') in {'parking','cafe','restaurant','fast_food','pharmacy','cinema','theatre','marketplace'}
        or tags.get('leisure') in {'park','sports_centre','fitness_centre'}
        or tags.get('tourism') in {'attraction','museum','gallery'}
        or tags.get('highway') in {'motorway','trunk','primary','secondary','tertiary','pedestrian','bus_stop'}
        or tags.get('public_transport') == 'platform'
        or tags.get('railway') in {'station','halt','subway_entrance','tram_stop'})


def map_context(candidates, load_tile):
    """Never call partial tiles complete or compare candidates with unequal coverage."""
    tiles = context_tiles(candidates)
    if not tiles:
        raise ValueError('No eligible premises available for surrounding-map coverage')
    merged = {}
    errors = []
    for bbox in tiles:
        try:
            elements = load_tile(bbox)
            if not isinstance(elements, list):
                raise ValueError('missing elements list')
            for element in elements:
                merged[(element.get('type'), element.get('id'))] = element
        except Exception as exc:
            errors.append(str(exc))
            if isinstance(exc, TimeoutError) or getattr(exc, 'code', None) == 429:
                break
    if errors:
        raise RuntimeError(f'Surrounding-map coverage incomplete: {len(tiles)} tiles required; '
                           f'{len(errors)} failed requests. Retry can reuse successful tiles. {errors[0]}')
    nodes = {e['id']: (e['lat'], e['lon']) for e in merged.values()
             if e.get('type') == 'node' and 'lat' in e and 'lon' in e}
    ways = {}
    for e in merged.values():
        coords = [nodes[n] for n in e.get('nodes', []) if n in nodes]
        if coords:
            ways[e['id']] = (sum(p[0] for p in coords)/len(coords), sum(p[1] for p in coords)/len(coords))
    rows = []
    for e in merged.values():
        tags = e.get('tags') or {}
        if not relevant(tags):
            continue
        point = nodes.get(e['id']) if e.get('type') == 'node' else ways.get(e['id']) if e.get('type') == 'way' else None
        if e.get('type') == 'relation':
            coords = [ways[m['ref']] for m in e.get('members', []) if m.get('type') == 'way' and m.get('ref') in ways]
            if coords:
                point = (sum(p[0] for p in coords)/len(coords), sum(p[1] for p in coords)/len(coords))
        if point is None:
            continue
        row = {'name': tags.get('name:en') or tags.get('name') or tags.get('brand') or 'Unnamed',
               'lat': float(point[0]), 'lon': float(point[1]), 'tags': tags,
               **{k: tags[k] for k in TAG_KEYS if k in tags},
               'osm_type': e['type'], 'osm_id': e['id'],
               'discovery_source': 'OpenStreetMap Map API · candidate surroundings'}
        if any(distance(row, site) <= CONTEXT_RADIUS_KM for site in candidates):
            rows.append(row)
    return rows
