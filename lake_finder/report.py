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


def write_all(lakes: list[Lake], out_dir: str | Path, city=(13.7563, 100.5018), city_name="Bangkok",
              listings: list[dict] | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ranked = sorted(lakes, key=lake_score, reverse=True)
    records = [lake_record(l, i + 1) for i, l in enumerate(ranked)]
    return write_records(records, out_dir, city, city_name, listings)


LISTING_COLS = ["name", "verdict", "fit_score", "price_thb", "area_rai", "price_per_rai", "distance_km", "lat", "lon",
                "water_type", "water_dist_m", "flood_zone", "mountain_elev_m", "mountain_relief_m", "mountain_dist_km",
                "mountain_direction", "mountain_view_deg", "lake_mountain_view_deg", "lake_mountain_view_score",
                "slope_deg", "url", "google_maps"]


def write_records(records: list[dict], out_dir: str | Path, city=(13.7563, 100.5018), city_name="Bangkok",
                  listings: list[dict] | None = None) -> dict:
    """Write all outputs. ``listings=None`` keeps the scored listings already in ``out_dir``
    (so ``lake_finder.enrich`` does not drop them); pass ``[]`` to clear them."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scored = out / "listings_scored.json"
    if listings is None:
        listings = json.loads(scored.read_text(encoding="utf-8")) if scored.exists() else []
    listings = sorted(listings, key=lambda l: -l["fit_score"])
    # Point listings' "nearby lakeside sites" at the lake names/ranks used in this output.
    by_site = {(round(float(st["lat"]), 5), round(float(st["lon"]), 5)): r for r in records for st in r["sites"]}
    for l in listings:
        for ns in l.get("nearby_sites", []):
            r = by_site.get((round(ns["lat"], 5), round(ns["lon"], 5)))
            if r:
                ns["lake_name"] = f"#{int(r['rank'])} {r['name']}"
        l["pros"] = [x for x in l.get("pros", []) if not x.startswith("Lakeside site with a mountain view")]
        if l.get("nearby_sites"):
            b = l["nearby_sites"][0]
            l["pros"].append(f"Lakeside site with a mountain view {b['km']} km away ({b['lake_name']}, score {b['score']}) — compare")
    if listings:
        scored.write_text(json.dumps(listings, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(out / "listings.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LISTING_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(listings)
    elif scored.exists():
        scored.unlink()

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
    for l in listings:
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [l["lon"], l["lat"]]},
                         "properties": {"kind": "listing", **{k: v for k, v in l.items() if k != "nearby_sites"}}})
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
    (out / "map.html").write_text(render_map(records, city, city_name, listings), encoding="utf-8")
    return {"lakes": len(records), "sites": len(site_rows), "listings": len(listings), "out_dir": str(out)}


def render_map(records: list[dict], city, city_name: str, listings: list[dict] | None = None) -> str:
    data = json.dumps({"city": {"lat": city[0], "lon": city[1], "name": city_name}, "lakes": records,
                       "listings": listings or []}).replace("</", "<\\/")
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
.site{margin:6px 0 0;padding:6px 8px;border-left:3px solid #ff5a36;background:var(--sel);font-size:12.5px;color:var(--muted)}.site b{color:var(--fg)}
.rank{color:var(--accent);font-variant-numeric:tabular-nums}.meta{color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums}
a{color:var(--accent)}.empty{padding:16px;color:var(--muted)}
h3{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0;padding:14px 16px 6px;border-bottom:1px solid var(--line)}
.badge{display:inline-block;white-space:nowrap;align-self:flex-start;font-size:11.5px;padding:1px 7px;border-radius:9px;background:#7b3fe4;color:#fff}
.fit{font-weight:600;color:var(--fg)}.pc{margin:6px 0 0;padding-left:18px;font-size:12.5px}.pc li.pro::marker{content:"+ ";color:#2e9d57}.pc li.con::marker{content:"– ";color:#d2452f}
.lmark{width:18px;height:18px;background:#7b3fe4;border:2px solid #fff;transform:rotate(45deg);box-shadow:0 1px 4px #0006}
.lmark.hi{background:#ffd23f;border-color:#7b3fe4}
@media (max-width:720px){#app{flex-direction:column-reverse}#side{width:100%;height:45%;border-right:0;border-top:1px solid var(--line)}}
</style></head><body><div id="app"><div id="side"><header><h1>Lake House Finder</h1>
<p>Lakes and reservoirs with a mountain view across the water. Each site is dry, gently sloped shoreland outside the reservoir's maximum water extent. The dashed line shows the view to the mountain. Purple diamonds are land for sale, scored the same way.</p></header>
<div id="listings"></div><h3>Lakes with a mountain view</h3><div id="list"></div></div><div id="map"></div></div>
<script>
const DATA=/*DATA*/null;
const map=L.map('map').setView([DATA.city.lat,DATA.city.lon],8);
const sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Imagery &copy; Esri, Maxar, Earthstar Geographics'}).addTo(map);
const topo=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{maxZoom:17,attribution:'&copy; OpenStreetMap, SRTM, OpenTopoMap'});
const layersCtl=L.control.layers({'Satellite':sat,'Topographic':topo}).addTo(map);
L.marker([DATA.city.lat,DATA.city.lon]).addTo(map).bindPopup(DATA.city.name);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const blank=v=>v===undefined||v===null||v==='';
const accessHtml=s=>{const k=['road_dist_m','buildings_500m','protected_area','district'];
  if(k.every(x=>blank(s[x])))return 'Access: not checked (run lake_finder.enrich)<br>';const bits=[];
  bits.push(blank(s.road_dist_m)?'paved road: unknown':`paved road ${s.road_dist_m} m (${esc(s.road_class)})`);
  if(!blank(s.buildings_500m))bits.push(`${s.buildings_500m} buildings within 500 m`);
  if(s.district)bits.push(esc(s.district));
  return (s.protected_area?`<b style="color:#c0392b">⚠ inside ${esc(s.protected_area)} (protected)</b><br>`:'')+bits.join(' · ')+'<br>';};
const siteHtml=(l,s,j)=>`<b>House site ${j+1} – ${esc(l.name)}</b><br>Score ${s.score}${s.raw_score&&s.raw_score!=s.score?` (view score ${s.raw_score})`:''}<br>Faces ${s.best_direction} (${s.best_bearing_deg}°), view width ${s.view_width_deg}°<br>${s.water_width_m} m of water, then a ${s.mountain_elev_m} m mountain ${s.mountain_dist_km} km away (${s.mountain_angle_deg}° above horizon)<br>${s.height_above_water_m} m above usual water level · slope ${s.slope_deg}° · elevation ${s.elev_m} m<br>${accessHtml(s)}${s.lat}, ${s.lon} · <a target="_blank" href="${s.google_maps}">Open in Google Maps</a>`;
const LAKE_STYLE={radius:7,color:'#00b4ff',weight:2,fillOpacity:.5},LAKE_HI={radius:13,color:'#ffd23f',weight:4,fillOpacity:.8};
const SITE_STYLE={radius:6,color:'#fff',weight:2,fillColor:'#ff5a36',fillOpacity:1},SITE_HI={radius:11,color:'#ffd23f',weight:4,fillColor:'#ff5a36'};
const list=document.getElementById('list');const groups=[],items=[];let cur=null;
function select(i,focus){
  if(cur!==null){const o=items[cur];o.div.classList.remove('sel');o.lakeM.setStyle(LAKE_STYLE);o.siteMs.forEach(m=>m.setStyle(SITE_STYLE));}
  cur=i;const it=items[i];it.div.classList.add('sel');it.lakeM.setStyle(LAKE_HI);it.lakeM.bringToFront();
  it.siteMs.forEach(m=>{m.setStyle(SITE_HI);m.bringToFront();});
  it.div.scrollIntoView({block:'nearest',behavior:'smooth'});
  if(focus)map.fitBounds(it.g.getBounds().pad(.3));
}
if(!DATA.lakes.length)list.innerHTML='<div class="empty">No matching lakes. Try relaxing the criteria.</div>';
DATA.lakes.forEach((l,i)=>{
  const g=L.featureGroup().addTo(map);const siteMs=[];
  const lakeM=L.circleMarker([l.lat,l.lon],{...LAKE_STYLE,bubblingMouseEvents:false}).addTo(g)
   .bindPopup(`<b>#${l.rank} ${esc(l.name)}</b><br>${l.distance_km} km from ${esc(DATA.city.name)} · ${l.area_km2} km²<br>Mountain ${Math.round(l.max_elev_m)} m (+${Math.round(l.relief_m)} m above water)<br><a target="_blank" href="${l.google_maps}">Open in Google Maps</a>`);
  lakeM.on('click',()=>select(i,false));
  l.sites.forEach((s,j)=>{
    L.polyline([[s.lat,s.lon],[s.mountain_lat,s.mountain_lon]],{color:'#ffd23f',weight:2,dashArray:'6 6'}).addTo(g);
    const m=L.circleMarker([s.lat,s.lon],{...SITE_STYLE,bubblingMouseEvents:false}).addTo(g).bindPopup(siteHtml(l,s,j));
    m.on('click',()=>select(i,false));siteMs.push(m);
  });
  groups.push(g);
  const div=document.createElement('div');div.className='item';
  div.innerHTML=`<h2><span class="rank">#${l.rank}</span>${esc(l.name)}</h2>
   <div class="meta"><span class="prov"></span>Score ${l.score} · ${l.distance_km} km from ${esc(DATA.city.name)} · ${l.area_km2} km²<br>
   Water surface ${l.surface_elev_m} m · highest peak ${Math.round(l.max_elev_m)} m (+${Math.round(l.relief_m)} m) · mountain ${l.mountain_dist_km} km from shore<br>
   <a target="_blank" href="${l.google_maps}" onclick="event.stopPropagation()">Lake in Google Maps</a></div>
   ${l.sites.map((s,j)=>`<div class="site" data-j="${j}"><b>Site ${j+1}</b> · score ${s.score}<br>${siteHtml(l,s,j).split('<br>').slice(2).join('<br>')}</div>`).join('')}`;
  div.onclick=()=>{select(i,true);lakeM.openPopup();};
  div.querySelectorAll('.site').forEach(el=>el.onclick=e=>{if(e.target.tagName==='A')return;e.stopPropagation();select(i,false);const m=siteMs[+el.dataset.j];map.flyTo(m.getLatLng(),15);m.openPopup();});
  list.appendChild(div);items.push({div,g,lakeM,siteMs});
});
// Land for sale, scored with the same satellite / terrain checks.
const fmt=n=>blank(n)?'–':Number(n).toLocaleString('en-US');
const lbox=document.getElementById('listings');let curL=null;
function deselect(){if(cur!==null){const o=items[cur];o.div.classList.remove('sel');o.lakeM.setStyle(LAKE_STYLE);o.siteMs.forEach(m=>m.setStyle(SITE_STYLE));cur=null;}
  if(curL){curL.div.classList.remove('sel');curL.icon.classList.remove('hi');curL=null;}}
map.on('click',deselect);  // clicking empty map clears the highlight (markers don't bubble clicks to the map)
const _select=select;select=(i,f)=>{if(curL){curL.div.classList.remove('sel');curL.icon.classList.remove('hi');curL=null;}_select(i,f);};
if(DATA.listings.length){
  lbox.innerHTML='<h3>Land for sale — how well it fits</h3>';
  DATA.listings.forEach(p=>{
    const g=L.featureGroup().addTo(map);
    if(p.mountain_view_deg>0)L.polyline([[p.lat,p.lon],[p.mountain_lat,p.mountain_lon]],{color:'#b98cff',weight:2,dashArray:'4 6'}).addTo(g);
    const links=[p.url,...(p.other_urls||[])].filter(Boolean).slice(0,4).map((u,i)=>`<a target="_blank" rel="noopener" href="${esc(u)}" onclick="event.stopPropagation()">${i?'mirror '+i:'listing'}</a>`).join(' · ');
    const li=(a,c)=>a.map(x=>`<li class="${c}">${esc(x)}</li>`).join('');
    const near=p.nearby_sites.length?`<b>Best lakeside sites within 20 km:</b><ul class="pc">${p.nearby_sites.slice(0,3).map(s=>`<li>${esc(s.lake_name)} – ${s.km} km, faces ${s.direction}, score ${s.score} (<a target="_blank" href="https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lon}" onclick="event.stopPropagation()">map</a>)</li>`).join('')}</ul>`:'';
    const facts=`${fmt(p.price_thb)} ฿ · ${p.area_rai??'–'} rai · ${fmt(p.price_per_rai)} ฿/rai · ${p.distance_km} km from ${esc(DATA.city.name)}${p.plot_m?' · plot '+esc(p.plot_m):''}`;
    const body=`<span class="fit">${esc(p.verdict)} · fit ${p.fit_score}/100</span><br>${facts}<ul class="pc">${li(p.pros,'pro')}${li(p.cons,'con')}</ul>${near}${links} · <a target="_blank" href="${p.google_maps}" onclick="event.stopPropagation()">Google Maps</a>`;
    const m=L.marker([p.lat,p.lon],{icon:L.divIcon({className:'',html:'<div class="lmark"></div>',iconSize:[18,18],iconAnchor:[9,9]}),zIndexOffset:1000}).addTo(g)
     .bindPopup(`<b>${esc(p.name)}</b><br>${body}`,{maxWidth:340});
    const div=document.createElement('div');div.className='item';
    div.innerHTML=`<h2><span class="badge">For sale</span>${esc(p.name)}</h2><div class="meta"><span class="prov"></span>${body}</div>`;
    const it={div,icon:null};
    const pick=()=>{deselect();curL=it;div.classList.add('sel');it.icon=m.getElement().firstChild;it.icon.classList.add('hi');};
    m.on('click',pick);
    div.onclick=()=>{pick();const b=L.featureGroup([g]);p.nearby_sites.slice(0,1).forEach(s=>b.addLayer(L.marker([s.lat,s.lon])));map.fitBounds(b.getBounds().pad(.4));m.openPopup();};
    lbox.appendChild(div);groups.push(g);
  });
}
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
    document.querySelectorAll('#listings .item').forEach((el,i)=>{const l=DATA.listings[i];const f=gj.features.find(f=>inGeom(l.lon,l.lat,f.geometry));if(f)el.querySelector('.prov').innerHTML=`<b>${esc(f.properties.pro_en)}</b> · `;});
    document.querySelectorAll('#list .item').forEach((el,i)=>{const l=DATA.lakes[i];const f=gj.features.find(f=>inGeom(l.lon,l.lat,f.geometry));if(f)el.querySelector('.prov').innerHTML=`<b>${esc(f.properties.pro_en)}</b> · `;});
    return;
  }catch(e){}}
  console.warn('Province boundaries could not be loaded');
}
loadProvinces();
</script></body></html>
"""
