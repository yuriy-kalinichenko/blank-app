"""Interactive raster/SVG maps that do not require a WebGL context."""
import json
import math


def map_html(points, *, center, zoom=12, geojson=None, fit=False):
    clean = []
    for point in points:
        try:
            lat, lon = float(point['lat']), float(point['lon'])
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        clean.append({**point, 'lat': lat, 'lon': lon})
    payload = json.dumps({'points': clean, 'center': list(center), 'zoom': zoom,
                          'geojson': geojson, 'fit': fit}, allow_nan=False)
    # Provider names and addresses are data, never executable HTML or scripts.
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return r'''<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css">
<style>html,body{margin:0;height:100%;font:14px system-ui}#map{height:100%;min-height:400px}
#status{position:absolute;z-index:1000;bottom:28px;left:10px;max-width:80%;background:white;padding:5px 9px;border-radius:4px}
.site-number{background:#ffc938;border:2px solid #795b00;border-radius:50%;text-align:center;line-height:26px;font-weight:700;color:#111}
.leaflet-popup-content{white-space:pre-line}</style></head><body>
<div id="map" role="region" aria-label="Interactive location map"></div>
<div id="status" role="status">Loading map…</div>
<script id="map-data" type="application/json">''' + payload + r'''</script>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js" onerror="document.getElementById('status').textContent='Map library unavailable. Please reload or check your connection.'"></script>
<script>
if (typeof L !== 'undefined') {
 const data=JSON.parse(document.getElementById('map-data').textContent);
 const status=document.getElementById('status');
 const map=L.map('map',{scrollWheelZoom:false}).setView(data.center,data.zoom);
 const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
  maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
 }).addTo(map);
 let tileError=false;
 tiles.on('tileerror',()=>{tileError=true;status.textContent='Some background tiles are unavailable. Markers remain visible.';});
 tiles.on('load',()=>{if(!tileError) status.textContent='Map ready · '+data.points.length+' locations';});
 const bounds=L.latLngBounds([]);
 const text=(value)=>{const el=document.createElement('span');el.textContent=String(value);return el;};
 if(data.geojson){
  const features=[...(data.geojson.features||[])].sort((a,b)=>(b.properties?.minutes||0)-(a.properties?.minutes||0));
  const polygons=L.geoJSON({type:'FeatureCollection',features},{
   style:f=>({color:({15:'#27ae60',30:'#2980b9',40:'#8e44ad'})[f.properties?.minutes]||'#2980b9',weight:2,fillOpacity:0.12}),
   onEachFeature:(f,l)=>l.bindPopup(text(String(f.properties?.minutes||'')+' min'+(f.properties?.proxy?' · approximate radius, not a route calculation':'')))
  }).addTo(map);
  if(polygons.getBounds().isValid())bounds.extend(polygons.getBounds());
 }
 for(const p of data.points){
  const pos=[p.lat,p.lon];bounds.extend(pos);
  const label=(p.rank?'#'+p.rank+' ':'')+(p.name||'Selected site');
  let marker;
  if(p.rank){marker=L.marker(pos,{title:label,icon:L.divIcon({className:'site-number',html:String(Number(p.rank)),iconSize:[28,28],iconAnchor:[14,14]})});}
  else{marker=L.circleMarker(pos,{radius:p.selected?8:4,color:p.selected?'#b34800':'#176b93',weight:1,fillOpacity:0.8});}
  marker.bindTooltip(text(label));
  let details=label+(p.address?'\n'+p.address:'');
  if(p.golden_score!==undefined) details+='\nEvidence score: '+p.golden_score+' / 100\nConfidence: '+p.confidence;
  marker.bindPopup(text(details)).addTo(map);
 }
 if(data.fit&&bounds.isValid())map.fitBounds(bounds.pad(0.12),{maxZoom:14});
 L.control.scale({imperial:false}).addTo(map);
 new ResizeObserver(()=>map.invalidateSize()).observe(document.getElementById('map'));
}
</script></body></html>'''


def render_map(points, *, center, zoom=12, geojson=None, fit=False, title='Interactive location map'):
    import streamlit as st
    import inspect
    markup = map_html(points, center=center, zoom=zoom, geojson=geojson, fit=fit)
    if hasattr(st, 'iframe'):
        options = {"alt": title} if "alt" in inspect.signature(st.iframe).parameters else {}
        st.iframe(markup, height=440, **options)
    else:
        from streamlit.components.v1 import html
        html(markup, height=440)
