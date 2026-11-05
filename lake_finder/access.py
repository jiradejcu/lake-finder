"""Optional: check each house site for road access, neighbours and protected land (OpenStreetMap).

Everything here is advisory. OSM coverage of Thai land titles is poor, so a site that is not
flagged as protected is not necessarily buildable. Verify with the Land Department.
"""
from __future__ import annotations

import logging
import math
import time

import requests

log = logging.getLogger(__name__)
OVERPASS_URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
HEADERS = {"User-Agent": "lake-finder/0.1 (personal land search; github.com/jiradejcu/lake-finder)"}
PAVED = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"}
PROTECTED_Q = '["boundary"~"^(national_park|protected_area)$"]'


def run_query(query: str, session=None, urls=OVERPASS_URLS, retries: int = 2) -> dict | None:
    http = session or requests
    for url in urls:
        for attempt in range(retries):
            try:
                resp = http.post(url, data={"data": query}, headers=HEADERS, timeout=45)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("overpass %s failed (%s)", url, exc)
                time.sleep(2 * (attempt + 1))
    return None


def _xy(lat, lon, lat0):
    return lon * 111_320 * math.cos(math.radians(lat0)), lat * 110_540


def point_segment_m(lat, lon, a, b) -> float:
    """Metres from a point to the segment a-b (each a (lat, lon) pair)."""
    px, py = _xy(lat, lon, lat)
    ax, ay = _xy(*a, lat)
    bx, by = _xy(*b, lat)
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def nearest_road(lat, lon, ways) -> tuple[float | None, str | None]:
    """ways: iterable of (highway_class, [(lat, lon), ...]). Returns (metres, class) of the closest paved road."""
    best, cls = None, None
    for kind, pts in ways:
        if kind not in PAVED:
            continue
        for a, b in zip(pts, pts[1:]):
            d = point_segment_m(lat, lon, a, b)
            if best is None or d < best:
                best, cls = d, kind
    return (round(best) if best is not None else None), cls


def parse_ways(data: dict) -> list[tuple[str, list[tuple[float, float]]]]:
    out = []
    for e in (data or {}).get("elements", []):
        if e.get("type") == "way" and e.get("geometry") and e.get("tags", {}).get("highway"):
            out.append((e["tags"]["highway"], [(p["lat"], p["lon"]) for p in e["geometry"]]))
    return out


def count_near(lat, lon, centres, radius_m) -> int:
    return sum(1 for (la, lo) in centres
               if math.hypot(*(a - b for a, b in zip(_xy(la, lo, lat), _xy(lat, lon, lat)))) <= radius_m)


def parse_buildings(data: dict) -> list[tuple[float, float]]:
    out = []
    for e in (data or {}).get("elements", []):
        c = e.get("center") or e
        if "building" in e.get("tags", {}) and "lat" in c:
            out.append((c["lat"], c["lon"]))
    return out


def parse_areas(data: dict) -> tuple[str | None, str | None]:
    """From an ``is_in`` result return (protected_area_name, district_name)."""
    protected = district = None
    for e in (data or {}).get("elements", []):
        t = e.get("tags", {})
        if t.get("boundary") in ("national_park", "protected_area") and protected is None:
            protected = t.get("name:en") or t.get("name") or t.get("boundary")
        elif t.get("boundary") == "administrative" and t.get("admin_level") == "6":
            district = t.get("name:en") or t.get("name")
    return protected, district


def site_access(lat, lon, radius_m: int = 3000, session=None, urls=OVERPASS_URLS) -> dict:
    """Road distance, neighbour count, protected-area flag and district for one site.
    Missing values mean the lookup failed, not that the answer is none."""
    hw = "|".join(sorted(PAVED))
    data = run_query(
        f'[out:json][timeout:30];is_in({lat},{lon})->.a;rel(pivot.a)["boundary"];out tags;'
        f'way["highway"~"^({hw})$"](around:{radius_m},{lat},{lon});out tags geom;'
        f'nwr["building"](around:500,{lat},{lon});out tags center 400;', session, urls, retries=1)
    roads = near = areas = data
    res = {"road_dist_m": None, "road_class": None, "buildings_500m": None, "protected_area": None, "district": None}
    if roads is not None:
        res["road_dist_m"], res["road_class"] = nearest_road(lat, lon, parse_ways(roads))
    if near is not None:
        res["buildings_500m"] = len(parse_buildings(near))
    if areas is not None:
        res["protected_area"], res["district"] = parse_areas(areas)
    return res


def adjust_score(score: float, acc: dict, max_road_m: float = 2000) -> float:
    """Demote sites in protected areas or far from any paved road. Unknowns are left alone."""
    if acc.get("protected_area"):
        score *= 0.1
    d = acc.get("road_dist_m")
    if d is not None and d > max_road_m:
        score *= max(0.2, max_road_m / d)
    return round(score, 1)
