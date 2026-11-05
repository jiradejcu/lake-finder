"""Write results as CSV, GeoJSON and an interactive satellite map (HTML)."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .analysis import Lake


def gmaps(lat, lon) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.5f},{lon:.5f}"


def lake_score(lake: Lake) -> float:
    """Best house-site view score, discounted for distance from the city."""
    best = max((s.score for s in lake.sites), default=0.0)
    return round(best / (1 + lake.distance_km / 150.0), 1)


def lake_record(lake: Lake, rank: int) -> dict:
    return {
        "rank": rank, "name": getattr(lake, "name", None) or f"Water body #{lake.id}",
        "score": lake_score(lake), "lat": round(lake.lat, 5), "lon": round(lake.lon, 5),
        "distance_km": round(lake.distance_km, 1), "area_km2": round(lake.area_km2, 2),
        "surface_elev_m": lake.surface_elev_m, "max_elev_m": lake.max_elev_m, "relief_m": lake.relief_m,
        "mountain_dist_km": lake.mountain_dist_km, "peak_lat": round(lake.peak_lat, 5),
        "peak_lon": round(lake.peak_lon, 5), "google_maps": gmaps(lake.lat, lake.lon),
        "sites": [dict(asdict(s), google_maps=gmaps(s.lat, s.lon)) for s in lake.sites],
    }


def write_all(lakes: list[Lake], out_dir: str | Path, city=(13.7563, 100.5018), city_name="Bangkok") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ranked = sorted(lakes, key=lake_score, reverse=True)
    records = [lake_record(l, i + 1) for i, l in enumerate(ranked)]
    return write_records(records, out_dir, city, city_name)


def write_records(records: list[dict], out_dir: str | Path, city=(13.7563, 100.5018), city_name="Bangkok") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lake_fields = [k for k in records[0] if k != "sites"] if records else ["rank"]
    with open(out / "lakes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=lake_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    site_rows = [{"lake_rank": r["rank"], "lake_name": r["name"], "distance_from_city_km": r["distance_km"], **s}
                 for r in records for s in r["sites"]]
    with open(out / "house_sites.csv", "w", newline="", encoding="utf-8") as f:
        fields = list(site_rows[0]) if site_rows else ["lake_rank"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(site_rows)

    features = []
    for r in records:
        props = {k: v for k, v in r.items() if k != "sites"}
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                         "properties": {"kind": "lake", **props}})
        for s in r["sites"]:
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                             "properties": {"kind": "house_site", "lake_rank": r["rank"], **s}})
            features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [
                [s["lon"], s["lat"]], [s["mountain_lon"], s["mountain_lat"]]]},
                "properties": {"kind": "view_line", "lake_rank": r["rank"]}})
    (out / "results.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=1),
                                         encoding="utf-8")
    (out / "map.html").write_text(render_map(records, city, city_name), encoding="utf-8")
    return {"lakes": len(records), "sites": len(site_rows), "out_dir": str(out)}


def render_map(records: list[dict], city, city_name: str) -> str:
    data = json.dumps({"city": {"lat": city[0], "lon": city[1], "name": city_name}, "lakes": records})
    return MAP_TEMPLATE.replace("/*DATA*/null", data)


MAP_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lake House Finder</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--bg:#fff;--fg:#1c1f23;--muted:#5d6670;--line:#e3e6ea;--accent:#0b6bcb;--sel:#eef5fd}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15181c;--fg:#e8eaed;--muted:#9aa3ad;--line:#2b3036;--accent:#6cb3ff;--sel:#1f2a36}}
:root[data-theme="dark"]{--bg:#15181c;--fg:#e8eaed;--muted:#9aa3ad;--line:#2b3036;--accent:#6cb3ff;--sel:#1f2a36}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
#app{display:flex;height:100%}#side{width:380px;max-width:100%;overflow:auto;border-right:1px solid var(--line)}
#map{flex:1}header{padding:16px;border-bottom:1px solid var(--line)}h1{font-size:18px;margin:0 0 4px}
header p{margin:0;color:var(--muted);font-size:13px}.item{padding:12px 16px;border-bottom:1px solid var(--line);cursor:pointer}
.item:hover,.item.sel{background:var(--sel)}.item h2{font-size:15px;margin:0 0 4px;display:flex;gap:8px}
.rank{color:var(--accent);font-variant-numeric:tabular-nums}.meta{color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums}
a{color:var(--accent)}.empty{padding:16px;color:var(--muted)}
@media (max-width:720px){#app{flex-direction:column-reverse}#side{width:100%;height:45%;border-right:0;border-top:1px solid var(--line)}}
</style></head><body><div id="app"><div id="side"><header><h1>Lake House Finder</h1>
<p>Lakes and reservoirs with a mountain view across the water. Each site is dry, gently sloped shoreland outside the reservoir's maximum water extent. The dashed line shows the view to the mountain.</p></header>
<div id="list"></div></div><div id="map"></div></div>
<script>
const DATA=/*DATA*/null;
const map=L.map('map').setView([DATA.city.lat,DATA.city.lon],8);
const sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Imagery &copy; Esri, Maxar, Earthstar Geographics'}).addTo(map);
const topo=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{maxZoom:17,attribution:'&copy; OpenStreetMap, SRTM, OpenTopoMap'});
const layersCtl=L.control.layers({'Satellite':sat,'Topographic':topo}).addTo(map);
L.marker([DATA.city.lat,DATA.city.lon]).addTo(map).bindPopup(DATA.city.name);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const accessHtml=s=>{if(s.road_dist_m===undefined)return '';const bits=[];
  bits.push(s.road_dist_m==null?'road: unknown':`paved road ${s.road_dist_m} m (${esc(s.road_class)})`);
  if(s.buildings_500m!=null)bits.push(`${s.buildings_500m} buildings within 500 m`);
  if(s.district)bits.push(esc(s.district));
  return (s.protected_area?`<b style="color:#c0392b">⚠ inside ${esc(s.protected_area)} (protected)</b><br>`:'')+bits.join(' · ')+'<br>';};
const list=document.getElementById('list');const groups=[];
if(!DATA.lakes.length)list.innerHTML='<div class="empty">No matching lakes. Try relaxing the criteria.</div>';
DATA.lakes.forEach((l,i)=>{
  const g=L.featureGroup().addTo(map);
  L.circleMarker([l.lat,l.lon],{radius:7,color:'#00b4ff',weight:2,fillOpacity:.5}).addTo(g)
   .bindPopup(`<b>#${l.rank} ${esc(l.name)}</b><br>${l.distance_km} km from ${esc(DATA.city.name)} · ${l.area_km2} km²<br>Mountain ${Math.round(l.max_elev_m)} m (+${Math.round(l.relief_m)} m above water)<br><a target="_blank" href="${l.google_maps}">Open in Google Maps</a>`);
  l.sites.forEach((s,j)=>{
    L.polyline([[s.lat,s.lon],[s.mountain_lat,s.mountain_lon]],{color:'#ffd23f',weight:2,dashArray:'6 6'}).addTo(g);
    L.circleMarker([s.lat,s.lon],{radius:6,color:'#fff',weight:2,fillColor:'#ff5a36',fillOpacity:1}).addTo(g)
     .bindPopup(`<b>House site ${j+1} – ${esc(l.name)}</b><br>Faces ${s.best_direction} (${s.best_bearing_deg}°), view width ${s.view_width_deg}°<br>${s.water_width_m} m of water, then a ${s.mountain_elev_m} m mountain ${s.mountain_dist_km} km away (${s.mountain_angle_deg}° above horizon)<br>${s.height_above_water_m} m above usual water level · slope ${s.slope_deg}°<br>${accessHtml(s)}<a target="_blank" href="${s.google_maps}">Open in Google Maps</a>`);
  });
  groups.push(g);
  const div=document.createElement('div');div.className='item';
  div.innerHTML=`<h2><span class="rank">#${l.rank}</span>${esc(l.name)}</h2><div class="meta">${l.distance_km} km away · ${l.area_km2} km² · peak ${Math.round(l.max_elev_m)} m · ${l.sites.length} house site(s) · score ${l.score}</div>`;
  div.onclick=()=>{document.querySelectorAll('.item').forEach(e=>e.classList.remove('sel'));div.classList.add('sel');map.fitBounds(g.getBounds().pad(.3));};
  list.appendChild(div);
});
if(groups.length)map.fitBounds(L.featureGroup(groups).getBounds().pad(.1));

// Province boundaries, fetched at runtime (the map still works offline without them).
const PROV_URLS=['https://cdn.jsdelivr.net/gh/chingchai/OpenGISData-Thailand@master/provinces.geojson','https://raw.githubusercontent.com/chingchai/OpenGISData-Thailand/master/provinces.geojson'];
const inRing=(x,y,r)=>{let c=false;for(let i=0,j=r.length-1;i<r.length;j=i++){const[xi,yi]=r[i],[xj,yj]=r[j];if((yi>y)!==(yj>y)&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)c=!c;}return c;};
const inGeom=(x,y,g)=>(g.type==='Polygon'?[g.coordinates]:g.coordinates).some(p=>inRing(x,y,p[0])&&!p.slice(1).some(h=>inRing(x,y,h)));
async function loadProvinces(){
  for(const u of PROV_URLS){try{
    const gj=await (await fetch(u)).json();
    const layer=L.geoJSON(gj,{style:{color:'#ff9f1c',weight:2,opacity:.9,fill:false,dashArray:'2 4'},interactive:false,
      onEachFeature:(f,l)=>l.bindTooltip(f.properties.pro_en,{permanent:false})}).addTo(map);
    layer.bringToBack();layersCtl.addOverlay(layer,'Province boundaries');
    const pane=map.createPane('provLabels');pane.style.zIndex=450;pane.style.pointerEvents='none';
    gj.features.forEach(f=>{const p=f.properties;L.marker([p.lat,p.lon],{pane:'provLabels',interactive:false,icon:L.divIcon({className:'',html:`<span style="color:#fff;text-shadow:0 0 3px #000,0 0 3px #000;font:600 11px system-ui;white-space:nowrap">${esc(p.pro_en)}</span>`,iconSize:[0,0]})}).addTo(layer);});
    document.querySelectorAll('.item').forEach((el,i)=>{const l=DATA.lakes[i];const f=gj.features.find(f=>inGeom(l.lon,l.lat,f.geometry));if(f)el.querySelector('.meta').insertAdjacentHTML('afterbegin',`<b>${esc(f.properties.pro_en)}</b> · `);});
    return;
  }catch(e){}}
  console.warn('Province boundaries could not be loaded');
}
loadProvinces();
</script></body></html>
"""
