"""Optional: name each lake from OpenStreetMap (Overpass API)."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def lookup_name(lat: float, lon: float, radius_m: int = 3000, session=None, url: str = OVERPASS_URL) -> str | None:
    """Return the name of the nearest OSM water body / reservoir / dam, or None."""
    q = f"""[out:json][timeout:25];
(
  nwr(around:{radius_m},{lat},{lon})["natural"="water"]["name"];
  nwr(around:{radius_m},{lat},{lon})["landuse"="reservoir"]["name"];
  nwr(around:{radius_m},{lat},{lon})["waterway"="dam"]["name"];
);
out tags center 20;"""
    http = session or requests
    try:
        resp = http.post(url, data={"data": q}, timeout=40)
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except (requests.RequestException, ValueError) as exc:
        log.warning("name lookup failed for %.4f,%.4f: %s", lat, lon, exc)
        return None

    def dist2(e):
        c = e.get("center") or e
        return (c.get("lat", lat) - lat) ** 2 + (c.get("lon", lon) - lon) ** 2

    def rank(e):
        t = e.get("tags", {})
        is_water = t.get("natural") == "water" or t.get("landuse") == "reservoir"
        return (0 if is_water else 1, dist2(e))

    for e in sorted(elements, key=rank):
        t = e.get("tags", {})
        name = t.get("name:en") or t.get("name")
        if name:
            if t.get("name:en") and t.get("name") and t["name"] != t["name:en"]:
                return f"{t['name:en']} ({t['name']})"
            return name
    return None
