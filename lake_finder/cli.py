"""Command line entry point: ``python -m lake_finder``."""
from __future__ import annotations

import argparse
import logging
import time

from . import BANGKOK
from .analysis import Criteria, find_lakes, water_masks
from .geo import Grid
from .report import lake_score, write_all
from .sources import DataStore
from .viewpoints import ViewCriteria, find_sites


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lake_finder", description=(
        "Find lakes/reservoirs next to mountains near a city, plus shoreline house sites "
        "with a view across the water to the mountains. Uses satellite water maps "
        "(JRC Global Surface Water / ESA WorldCover) and the Copernicus DEM."))
    p.add_argument("--lat", type=float, default=BANGKOK[0], help="city latitude (default Bangkok)")
    p.add_argument("--lon", type=float, default=BANGKOK[1], help="city longitude (default Bangkok)")
    p.add_argument("--city-name", default="Bangkok")
    p.add_argument("--max-distance", type=float, default=250, help="max straight-line km from the city")
    p.add_argument("--water-source", choices=["gsw", "worldcover"], default="gsw")
    p.add_argument("--min-area", type=float, default=0.3, help="minimum lake area, km²")
    p.add_argument("--min-relief", type=float, default=250, help="mountain height above the water, m")
    p.add_argument("--max-mountain-dist", type=float, default=6, help="mountain within this many km of the shore")
    p.add_argument("--view-range", type=float, default=15, help="how far the house looks, km")
    p.add_argument("--min-water", type=float, default=500, help="metres of water in the view before the mountain")
    p.add_argument("--max-slope", type=float, default=10, help="max ground slope at the house site, degrees")
    p.add_argument("--sites-per-lake", type=int, default=3)
    p.add_argument("--names", action="store_true", help="look up lake names on OpenStreetMap (Overpass API)")
    p.add_argument("--top", type=int, default=0, help="only keep the N best lakes (0 = all)")
    p.add_argument("--out", default="output")
    p.add_argument("--cache", default="cache")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    crit = Criteria(city_lat=args.lat, city_lon=args.lon, max_distance_km=args.max_distance,
                    min_area_km2=args.min_area, min_relief_m=args.min_relief,
                    max_mountain_dist_km=args.max_mountain_dist)
    vc = ViewCriteria(view_range_km=args.view_range, min_water_m=args.min_water, max_slope_deg=args.max_slope,
                      min_relief_m=args.min_relief, sites_per_lake=args.sites_per_lake)

    grid = Grid.around(args.lat, args.lon, args.max_distance + args.view_range)
    print(f"Analysis grid {grid.width}x{grid.height} px (~90 m) around {args.city_name}")
    store = DataStore(grid, args.cache)
    t = time.time()
    print("Downloading elevation (Copernicus DEM)...", flush=True)
    dem = store.dem()
    print(f"Downloading satellite water map ({args.water_source})...", flush=True)
    occ = store.water_occurrence(args.water_source)
    print(f"  data ready in {time.time() - t:.0f}s")

    lakes, labels, usual = find_lakes(occ, dem, grid, crit)
    print(f"{len(lakes)} water bodies within {args.max_distance:g} km have mountains next to them")
    _, ever = water_masks(occ, dem, crit)
    for lake in lakes:
        lake.sites = find_sites(lake, labels, usual, ever, dem, grid, vc)
    lakes = [l for l in lakes if l.sites]
    lakes.sort(key=lake_score, reverse=True)
    if args.top:
        lakes = lakes[: args.top]
    print(f"{len(lakes)} of them have shoreline sites with a lake-and-mountain view")

    if args.names:
        from .names import lookup_name
        for lake in lakes:
            lake.name = lookup_name(lake.lat, lake.lon)
            time.sleep(1)  # be polite to the public Overpass server

    summary = write_all(lakes, args.out, (args.lat, args.lon), args.city_name)
    print(f"\n{'#':>3} {'score':>6} {'km':>6} {'km²':>7} {'peak m':>7}  best house site (lat, lon) -> view")
    for i, l in enumerate(lakes[:20], 1):
        s = l.sites[0]
        print(f"{i:>3} {lake_score(l):>6} {l.distance_km:>6.0f} {l.area_km2:>7.1f} {l.max_elev_m:>7.0f}  "
              f"{s.lat:.5f}, {s.lon:.5f} -> {s.best_direction}, {s.mountain_elev_m:.0f} m peak "
              f"{s.mountain_dist_km} km {getattr(l, 'name', None) or ''}")
    print(f"\nWrote {summary['lakes']} lakes / {summary['sites']} sites to {summary['out_dir']}/ "
          "(map.html, lakes.csv, house_sites.csv, results.geojson)")
    return 0
