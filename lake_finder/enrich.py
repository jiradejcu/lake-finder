"""Add OpenStreetMap access info to an existing results folder and re-rank.

    python -m lake_finder.enrich --in results --out results
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from .access import adjust_score, site_access
from .report import write_records

LAKE_NUM = {"score", "lat", "lon", "distance_km", "area_km2", "surface_elev_m", "max_elev_m", "relief_m",
            "mountain_dist_km", "peak_lat", "peak_lon"}


def _cast(row: dict, num_fields=None) -> dict:
    out = {}
    for k, v in row.items():
        try:
            out[k] = float(v) if (num_fields is None or k in num_fields) and v != "" else v
        except ValueError:
            out[k] = v
    return out


def load_records(folder: str | Path) -> list[dict]:
    folder = Path(folder)
    with open(folder / "lakes.csv", encoding="utf-8") as f:
        lakes = {int(float(r["rank"])): {**_cast(r, LAKE_NUM), "rank": int(float(r["rank"])), "sites": []} for r in csv.DictReader(f)}
    with open(folder / "house_sites.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = _cast(r)
            lakes[int(float(r["lake_rank"]))]["sites"].append({k: v for k, v in r.items()
                                                        if k not in ("lake_rank", "lake_name", "distance_from_city_km")})
    return list(lakes.values())


def enrich(records: list[dict], cache_file: Path, pause: float = 1.0, log=print, top: int = 0) -> list[dict]:
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    todo = records[:top] if top else records
    n = sum(len(r["sites"]) for r in todo)
    done = 0
    for r in todo:
        for s in r["sites"]:
            key = f"{s['lat']:.5f},{s['lon']:.5f}"
            if key not in cache or all(v is None for v in cache[key].values()):
                cache[key] = site_access(s["lat"], s["lon"])
                cache_file.write_text(json.dumps(cache))
                time.sleep(pause)
            s.update(cache[key])
            s["raw_score"] = s.get("raw_score", s["score"])
            s["score"] = adjust_score(s["raw_score"], cache[key])
            done += 1
            if done % 3 == 0:
                log(f"  {done}/{n} sites checked", flush=True)
        r["sites"].sort(key=lambda s: -s["score"])
        r["score"] = round(max((s["score"] for s in r["sites"]), default=0) / (1 + r["distance_km"] / 150.0), 1)
    records.sort(key=lambda r: -r["score"])
    for i, r in enumerate(records, 1):
        r["rank"] = i
        for s in r["sites"]:
            s.setdefault("google_maps", f"https://www.google.com/maps/search/?api=1&query={s['lat']:.5f},{s['lon']:.5f}")
    return records


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lake_finder.enrich")
    p.add_argument("--in", dest="src", default="results")
    p.add_argument("--out", default="results")
    p.add_argument("--lat", type=float, default=13.7563)
    p.add_argument("--lon", type=float, default=100.5018)
    p.add_argument("--top", type=int, default=0, help="only check the N best lakes (Overpass is slow)")
    p.add_argument("--city-name", default="Bangkok")
    a = p.parse_args(argv)
    records = load_records(a.src)
    records = enrich(records, Path(a.out) / "access_cache.json", top=a.top)
    print(write_records(records, a.out, (a.lat, a.lon), a.city_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
