"""Score land-for-sale listings with the same satellite and terrain analysis.

A listing needs coordinates. Give ``lat``/``lon`` yourself, or give a ``url``
from a site we can read (currently tb.co.th, whose pages include the pin
coordinates, price and description) and they are filled in automatically.

``listings.json`` is a list of objects such as::

    {"name": "6 rai, Nong Ya, Mueang Kanchanaburi",
     "url": "https://tb.co.th/property/....p.142449",
     "lat": 13.984142, "lon": 99.496038,
     "price_thb": 4800000, "area_rai": 6.125,
     "other_urls": ["https://www.ddproperty.com/..."], "notes": "..."}
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import requests
from scipy import ndimage

from .analysis import Criteria, Lake
from .geo import Grid, haversine_km
from .viewpoints import ViewCriteria, cast_views, compass, slope_deg

log = logging.getLogger(__name__)
SQM_PER_RAI = 1600.0
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) lake-finder"}


# --------------------------------------------------------------------------- input

def parse_thai_area_rai(text: str) -> float | None:
    """'6 ไร่ 1 งาน 50 ตารางวา' -> rai (1 rai = 4 ngan = 400 sq wah)."""
    rai = re.search(r"([\d.,]+)\s*ไร่", text)
    ngan = re.search(r"([\d.,]+)\s*งาน", text)
    wah = re.search(r"([\d.,]+)\s*(?:ตารางวา|ตร\.?\s*ว\.?)", text)
    if not (rai or ngan or wah):
        return None
    num = lambda m: float(m.group(1).replace(",", "")) if m else 0.0
    return round(num(rai) + num(ngan) / 4 + num(wah) / 400, 4)


def parse_tb_page(html: str) -> dict:
    """Extract coordinates, price and description from a tb.co.th property page."""
    out: dict = {}
    m = re.search(r'\blat:"(-?\d+\.\d+)",lng:"(-?\d+\.\d+)"', html)
    if m:
        out["lat"], out["lon"] = float(m.group(1)), float(m.group(2))
    m = re.search(r'\bsale_price:"([\d.]+)"', html)
    if m and float(m.group(1)) > 0:
        out["price_thb"] = float(m.group(1))
    m = re.search(r'\bexplanation:"((?:[^"\\]|\\.)*)"', html)
    if m:
        try:
            out["description"] = json.loads(f'"{m.group(1)}"')
        except ValueError:
            out["description"] = m.group(1)
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    if m:
        out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()
        area = parse_thai_area_rai(out["title"])
        if area:
            out["area_rai"] = area
    w = re.search(r'\barea_width:"([\d.]+)"', html)
    dpt = re.search(r'\barea_deep:"([\d.]+)"', html)
    if w and dpt and float(w.group(1)) > 0:
        out["plot_m"] = f"{float(w.group(1)):g} x {float(dpt.group(1)):g} m"
    m = re.search(r'\bproperty_direction:"(\w+)"', html)
    if m:
        out["facing"] = m.group(1)
    return out


def fetch_listing(url: str, session=None) -> dict:
    if "tb.co.th/" not in url:
        raise ValueError("only tb.co.th pages can be read automatically; add lat/lon by hand for other sites")
    http = session or requests
    resp = http.get(url, headers=UA, timeout=40)
    resp.raise_for_status()
    return parse_tb_page(resp.text)


def load_listings(path: str | Path, fetch: bool = True, session=None) -> list[dict]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for item in items:
        item = dict(item)
        if fetch and item.get("url") and ("lat" not in item or "price_thb" not in item):
            try:
                fetched = fetch_listing(item["url"], session=session)
                for k, v in fetched.items():
                    item.setdefault(k, v)
            except (requests.RequestException, ValueError) as exc:
                log.warning("could not read %s: %s", item["url"], exc)
        if "lat" not in item or "lon" not in item:
            log.warning("skipping listing without coordinates: %s", item.get("name") or item.get("url"))
            continue
        item.setdefault("name", item.get("title") or item.get("url") or f"{item['lat']:.5f}, {item['lon']:.5f}")
        out.append(item)
    return out


# ---------------------------------------------------------------------- evaluation

@dataclass
class ListingReport:
    name: str
    lat: float
    lon: float
    url: str | None = None
    other_urls: list = field(default_factory=list)
    price_thb: float | None = None
    area_rai: float | None = None
    price_per_rai: float | None = None
    price_per_sqm: float | None = None
    description: str | None = None
    plot_m: str | None = None
    distance_km: float = 0.0
    elev_m: float = 0.0
    slope_deg: float = 0.0
    water_type: str = ""
    water_dist_m: float = 0.0
    flood_zone: bool = False
    flood_dist_m: float = 0.0
    nearest_mountain_lake: str | None = None
    nearest_mountain_lake_km: float | None = None
    mountain_elev_m: float = 0.0
    mountain_relief_m: float = 0.0
    mountain_dist_km: float = 0.0
    mountain_direction: str = ""
    mountain_lat: float = 0.0
    mountain_lon: float = 0.0
    mountain_view_deg: float = 0.0
    lake_mountain_view_score: float = 0.0
    lake_mountain_view_deg: float = 0.0
    fit_score: int = 0
    verdict: str = ""
    pros: list = field(default_factory=list)
    cons: list = field(default_factory=list)
    nearby_sites: list = field(default_factory=list)


def evaluate_listing(item: dict, dem: np.ndarray, occ: np.ndarray, labels: np.ndarray, grid: Grid,
                     lakes: list[Lake], crit: Criteria, vc: ViewCriteria, search_km: float = 20.0) -> ListingReport:
    lat, lon = float(item["lat"]), float(item["lon"])
    rep = ListingReport(name=item["name"], lat=lat, lon=lon, url=item.get("url"),
                        other_urls=list(item.get("other_urls", [])), price_thb=item.get("price_thb"),
                        area_rai=item.get("area_rai"), description=item.get("description") or item.get("notes"),
                        plot_m=item.get("plot_m"))
    if rep.price_thb and rep.area_rai:
        rep.price_per_rai = round(rep.price_thb / rep.area_rai)
        rep.price_per_sqm = round(rep.price_thb / (rep.area_rai * SQM_PER_RAI))
    rep.distance_km = round(float(haversine_km(crit.city_lat, crit.city_lon, lat, lon)), 1)

    r = int((grid.north - lat) / grid.res_deg)
    c = int((lon - grid.west) / grid.res_deg)
    if not (0 <= r < grid.height and 0 <= c < grid.width):
        rep.verdict = "Outside the analysed area"
        return rep
    dy, dx = grid.pixel_size_m(lat)
    W = int(np.ceil(max(search_km, vc.view_range_km) * 1000 / min(dx, dy))) + 2
    r0, c0 = max(r - W, 0), max(c - W, 0)
    win = (slice(r0, min(r + W, grid.height)), slice(c0, min(c + W, grid.width)))
    pr, pc = r - r0, c - c0
    z, o, lab = dem[win], occ[win], labels[win]
    usual, ever = (o >= crit.water_threshold) & ~np.isnan(z), (o > 0) & ~np.isnan(z)

    rep.elev_m = round(float(z[pr, pc]), 1)
    rep.slope_deg = round(float(slope_deg(z[max(pr - 2, 0):pr + 3, max(pc - 2, 0):pc + 3], dy, dx)
                                [min(pr, 2), min(pc, 2)]), 1)
    rep.flood_zone = bool(o[pr, pc] > 0)
    rep.flood_dist_m = round(float(ndimage.distance_transform_edt(~ever, sampling=(dy, dx))[pr, pc])) if ever.any() else -1

    # Nearest water and what kind it is.
    if usual.any():
        dist, (ir, ic) = ndimage.distance_transform_edt(~usual, sampling=(dy, dx), return_indices=True)
        rep.water_dist_m = round(float(dist[pr, pc]))
        wr, wc = ir[pr, pc], ic[pr, pc]
        comp_lab, _ = ndimage.label(usual, structure=np.ones((3, 3)))
        comp = comp_lab == comp_lab[wr, wc]
        lake_ids = np.unique(lab[comp & (lab > 0)])
        area = float(comp.sum() * dy * dx / 1e6)
        if lake_ids.size:
            rep.water_type = f"lake / reservoir (~{area:.1f} km²)"
        else:
            rep.water_type = "river, canal or small pond"
        level = float(np.percentile(z[comp & ~np.isnan(z)], 25)) if comp.any() else rep.elev_m
        level = min(level, rep.elev_m)
    else:
        rep.water_dist_m, rep.water_type, level = -1, "none within search area", rep.elev_m

    # Mountains around the plot.
    rr, cc = np.mgrid[0:z.shape[0], 0:z.shape[1]]
    dkm = np.hypot((rr - pr) * dy, (cc - pc) * dx) / 1000
    near = (dkm <= crit.mountain_search_km) & ~np.isnan(z)
    k = np.argmax(np.where(near, z, -np.inf))
    mr, mc = np.unravel_index(k, z.shape)
    rep.mountain_elev_m = round(float(z[mr, mc]))
    rep.mountain_relief_m = round(float(z[mr, mc] - level))
    rep.mountain_dist_km = round(float(dkm[mr, mc]), 1)
    rep.mountain_direction = compass(np.degrees(np.arctan2((mc - pc) * dx, -(mr - pr) * dy)))
    rep.mountain_lat = round(float(grid.lat_of_row(r0 + mr)), 5)
    rep.mountain_lon = round(float(grid.lon_of_col(c0 + mc)), 5)

    # Sight lines from a balcony on the plot.
    v = cast_views(z, usual, np.array([pr]), np.array([pc]), level, dy, dx, vc)
    step = 360.0 / vc.n_bearings
    mountain_dirs = (v.sky_z[0] - level >= vc.min_relief_m) & (v.sky_angle[0] >= vc.min_angle_deg)
    rep.mountain_view_deg = float(mountain_dirs.sum() * step)
    rep.lake_mountain_view_score = round(float(v.score[0]), 1)
    rep.lake_mountain_view_deg = float(v.good[0].sum() * step)
    if mountain_dirs.any():   # point the map's view line at the most impressive skyline
        b = int(np.argmax(np.where(mountain_dirs, v.sky_angle[0], -1)))
        s = v.sky[0, b]
        rep.mountain_lat = round(float(grid.lat_of_row(r0 + v.ri[0, b, s])), 5)
        rep.mountain_lon = round(float(grid.lon_of_col(c0 + v.ci[0, b, s])), 5)
        rep.mountain_elev_m = round(float(v.sky_z[0, b]))
        rep.mountain_relief_m = round(float(v.sky_z[0, b] - level))
        rep.mountain_dist_km = round(float(v.d[s]) / 1000, 1)
        rep.mountain_direction = compass(v.bearings[b])

    # The best lakeside sites from the main analysis nearby, for comparison.
    best_lake = None
    for lake in lakes:
        for s_ in lake.sites:
            dk = float(haversine_km(lat, lon, s_.lat, s_.lon))
            if dk <= search_km:
                rep.nearby_sites.append({"lake_id": lake.id, "lake_name": getattr(lake, "name", None) or f"Water body #{lake.id}",
                                         "lat": s_.lat, "lon": s_.lon, "km": round(dk, 1), "score": s_.score,
                                         "direction": s_.best_direction})
        dl = float(haversine_km(lat, lon, lake.lat, lake.lon))
        if best_lake is None or dl < best_lake[1]:
            best_lake = (lake, dl)
    rep.nearby_sites.sort(key=lambda s_: -s_["score"])
    rep.nearby_sites = rep.nearby_sites[:5]
    if best_lake:
        rep.nearest_mountain_lake = getattr(best_lake[0], "name", None) or f"Water body #{best_lake[0].id}"
        rep.nearest_mountain_lake_km = round(best_lake[1], 1)

    _judge(rep, crit, vc)
    return rep


def _judge(rep: ListingReport, crit: Criteria, vc: ViewCriteria) -> None:
    """Fit for 'house at the water's edge, lake view, mountain behind' (0-100), with reasons."""
    lakeside = rep.water_type.startswith("lake")
    view = min(rep.lake_mountain_view_score, 60) / 60 * 40                      # 40: lake + mountain view
    water = 20 if rep.water_dist_m <= 150 else 12 if rep.water_dist_m <= 400 else 5 if rep.water_dist_m <= 1000 else 0
    water = water if lakeside else water * 0.6                                  # 20: on the water, lake > river
    mountain = min(rep.mountain_view_deg / 60, 1) * 10 + min(max(rep.mountain_relief_m, 0) / 600, 1) * 10  # 20
    build = (10 if rep.slope_deg <= vc.max_slope_deg else 3) + (0 if rep.flood_zone else 10)               # 20
    rep.fit_score = int(round(view + water + mountain + build))

    p, n = rep.pros, rep.cons
    if rep.lake_mountain_view_deg:
        p.append(f"View across water to mountains over {rep.lake_mountain_view_deg:g}° of the horizon")
    else:
        n.append("No view across open water to a mountain (needs ≥ "
                 f"{vc.min_water_m:g} m of water in front of a ≥ {vc.min_relief_m:g} m mountain)")
    if rep.water_dist_m >= 0:
        (p if rep.water_dist_m <= 300 else n).append(f"Nearest permanent water: {rep.water_type}, {rep.water_dist_m:g} m away")
    if rep.mountain_view_deg:
        p.append(f"Mountains on the skyline over {rep.mountain_view_deg:g}° — highest-looking {rep.mountain_elev_m} m, "
                 f"{rep.mountain_dist_km} km {rep.mountain_direction}")
    else:
        n.append(f"Hills nearby are low or far (best {rep.mountain_elev_m} m, {rep.mountain_dist_km} km {rep.mountain_direction})")
    if rep.flood_zone:
        n.append("Plot is inside the area the satellites have seen flooded (1984–2021)")
    else:
        p.append(f"Never flooded in the satellite record (closest flooded pixel {rep.flood_dist_m:g} m)")
    if rep.slope_deg > vc.max_slope_deg:
        n.append(f"Steep ground ({rep.slope_deg}°)")
    if rep.nearby_sites:
        b = rep.nearby_sites[0]
        p.append(f"Lakeside site with a mountain view {b['km']} km away ({b['lake_name']}, score {b['score']}) — compare")

    if rep.lake_mountain_view_deg and lakeside:
        rep.verdict = "Lakeside with mountain view"
    elif rep.lake_mountain_view_deg:
        rep.verdict = "Water + mountain view"
    elif rep.mountain_view_deg and 0 <= rep.water_dist_m <= 1000:
        rep.verdict = "Mountain view, water nearby"
    elif rep.mountain_view_deg:
        rep.verdict = "Mountain view only"
    elif 0 <= rep.water_dist_m <= 1000:
        rep.verdict = "Water nearby, no mountain view"
    else:
        rep.verdict = "Poor fit"


def report_dict(rep: ListingReport) -> dict:
    d = asdict(rep)
    d["google_maps"] = f"https://www.google.com/maps/search/?api=1&query={rep.lat:.5f},{rep.lon:.5f}"
    return d
