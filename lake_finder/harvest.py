"""Turn raw listing harvests (collected in a browser) into scored-listing input.

Portals block plain HTTP, so listings are read through the owner's logged-in Chrome
(see ``harvest/README.md``) and dropped into ``harvest/raw/*.json`` as a list of rows::

    {"src": "ddproperty", "id": "500126082", "url": "...", "prov": "Kanchanaburi",
     "dist": "Tha Muang", "tambon": "Wang Khanai", "price": 4200000, "area": "4,800 sqm (land)",
     "tenure": "F", "lat": 13.86, "lon": 99.59, "sub": "...", "desc": "..."}

``python -m lake_finder.harvest build`` then

1. normalises price/area (rai) and flags Thai keywords (waterfront, mountain view, ...);
2. grades the location: ``pin`` (own coordinates), ``shared`` (several ads share the same
   coordinates, so it is a portal's subdistrict centroid, not the plot), ``none``;
3. keeps listings within ``--radius`` km of a candidate house site (from ``results/house_sites.csv``);
4. writes ``harvest/all.json``, ``harvest/to_verify.csv`` (no trustworthy pin: call the agent)
   and appends the ``pin`` ones to ``listings.json`` so ``python -m lake_finder`` scores them.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from .geo import haversine_km

SQM_PER_RAI = 1600.0
KEYWORDS = {
    "waterfront": ["ติดน้ำ", "ริมน้ำ", "ติดอ่าง", "ริมอ่าง", "ติดแม่น้ำ", "ริมแม่น้ำ", "ติดคลอง", "ริมคลอง",
                   "ติดทะเลสาบ", "ริมทะเลสาบ", "ติดเขื่อน", "ริมเขื่อน", "ติดบึง", "ริมบึง", "ติดหนอง", "ริมหนอง"],
    "lake": ["ทะเลสาบ", "อ่างเก็บน้ำ", "เขื่อน", "วิวน้ำ", "วิวอ่าง", "วิวทะเลสาบ", "lake", "reservoir", "dam"],
    "mountain": ["วิวภูเขา", "วิวเขา", "ติดภูเขา", "ติดเขา", "ภูเขา", "mountain"],
}
TENURE_WARN = {"F": None, "L": "leasehold"}
TITLE_WARN = [("ส.ป.ก", "ส.ป.ก. (ALRO land: cannot be freely sold or built on)"),
              ("สปก", "ส.ป.ก. (ALRO land: cannot be freely sold or built on)"),
              ("ภบท", "ภบท.5 (tax receipt only, not a title)"),
              ("น.ส.3", "น.ส.3 (not a full chanote)"), ("นส.3", "น.ส.3 (not a full chanote)"),
              ("ป่าสงวน", "forest reserve mentioned")]


def parse_area_rai(text: str | None, desc: str = "") -> float | None:
    """'4,800 sqm (land)' -> 3.0 rai; falls back to 'X ไร่ Y งาน Z ตารางวา' in the description."""
    if text:
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*sqm\s*\(land\)", text)  # houses list built-up area without "(land)"
        if m:
            return round(float(m.group(1).replace(",", "")) / SQM_PER_RAI, 3)
    m = re.search(r"([\d.,]+)\s*ไร่(?:\s*([\d.,]+)\s*งาน)?(?:\s*([\d.,]+)\s*(?:ตารางวา|ตร\.?ว))?", desc or "")
    if m:
        rai = float(m.group(1).replace(",", ""))
        ngan = float((m.group(2) or "0").replace(",", ""))
        wah = float((m.group(3) or "0").replace(",", ""))
        return round(rai + ngan / 4 + wah / 400, 3)
    return None


def flag_keywords(text: str) -> dict[str, list[str]]:
    low = (text or "").lower()
    return {k: [w for w in ws if w in low] for k, ws in KEYWORDS.items() if any(w in low for w in ws)}


def title_warnings(text: str) -> list[str]:
    seen, out = set(), []
    for key, msg in TITLE_WARN:
        if key in (text or "") and msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out


FLAG_KW = {"w": "waterfront", "l": "lake", "m": "mountain"}
FLAG_WARN = {"S": TITLE_WARN[0][1], "B": TITLE_WARN[2][1], "N": TITLE_WARN[3][1], "F": TITLE_WARN[5][1]}


def decode_flags(flags: str) -> tuple[dict, list]:
    """Compact browser-side flags 'wlm|SBNF' -> (keywords, warnings)."""
    kw_part, _, warn_part = (flags or "").partition("|")
    return ({FLAG_KW[c]: [] for c in kw_part if c in FLAG_KW}, [FLAG_WARN[c] for c in warn_part if c in FLAG_WARN])


def normalise(row: dict) -> dict:
    text = " ".join(filter(None, [row.get("sub"), row.get("desc")]))
    rec = {
        "key": f"{row.get('src')}:{row.get('id')}",
        "src": row.get("src"), "id": row.get("id"), "url": row.get("url"),
        "prov": row.get("prov"), "dist": row.get("dist"), "tambon": row.get("tambon"),
        "price_thb": row.get("price"), "area_rai": parse_area_rai(row.get("area"), text),
        "tenure": row.get("tenure"), "lat": row.get("lat"), "lon": row.get("lon"),
        "title": row.get("sub"), "description": (row.get("desc") or "")[:500],
        "keywords": flag_keywords(text), "warnings": title_warnings(text),
    }
    if "flags" in row:  # compact row: the browser already looked at the text
        rec["keywords"], rec["warnings"] = decode_flags(row["flags"])
    if not rec["url"] and row.get("src") == "ddproperty":
        rec["url"] = f"https://www.ddproperty.com/en/property/x-for-sale-{row['id']}"
    if rec["price_thb"] and rec["area_rai"]:
        rec["price_per_rai"] = round(rec["price_thb"] / rec["area_rai"])
    return rec


def grade_pins(recs: list[dict]) -> None:
    """Set ``loc_quality`` on each record. Identical coordinates on 2+ ads => portal centroid."""
    def k(r):
        return None if r.get("lat") is None or r.get("lon") is None else (round(r["lat"], 4), round(r["lon"], 4))
    counts = Counter(k(r) for r in recs if k(r))
    for r in recs:
        key = k(r)
        r["loc_quality"] = "none" if key is None else ("shared" if counts[key] > 1 else "pin")


def dedupe(recs: list[dict]) -> list[dict]:
    """Merge the same plot advertised on several portals / re-posted (same price, area, tambon)."""
    merged: dict[tuple, dict] = {}
    for r in recs:
        sig = (r.get("price_thb"), r.get("area_rai"), (r.get("tambon") or "").lower(), r.get("prov"))
        if None in sig[:2]:
            sig = ("uniq", r["key"])
        if sig in merged:
            m = merged[sig]
            m.setdefault("other_urls", [])
            if r.get("url") and r["url"] not in m["other_urls"] and r["url"] != m.get("url"):
                m["other_urls"].append(r["url"])
        else:
            merged[sig] = dict(r)
    return list(merged.values())


def load_sites(path: str | Path, top_lakes: int | None = None) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if top_lakes:
        rows = [r for r in rows if float(r["lake_rank"]) <= top_lakes]
    return [{"lake": r["lake_name"], "rank": int(float(r["lake_rank"])), "lat": float(r["lat"]),
             "lon": float(r["lon"]), "score": float(r["score"]), "protected": r.get("protected_area") or ""}
            for r in rows]


def nearest_site(lat: float, lon: float, sites: list[dict]) -> tuple[dict, float]:
    best = min(sites, key=lambda s: float(haversine_km(lat, lon, s["lat"], s["lon"])))
    return best, round(float(haversine_km(lat, lon, best["lat"], best["lon"])), 2)


def attach_zone(recs: list[dict], sites: list[dict]) -> None:
    for r in recs:
        if r.get("lat") is None:
            continue
        s, d = nearest_site(r["lat"], r["lon"], sites)
        r["near_lake"], r["near_site_km"] = s["lake"], d
        r["near_lake_rank"] = s["rank"]


def to_listing_item(r: dict) -> dict:
    return {
        "name": f"{r.get('area_rai') or '?'} rai, " + ", ".join(x for x in (r.get("tambon"), r.get("dist"), r.get("prov")) if x)
                + f" ({r['key'].replace('ddproperty:', 'DDP ')})",
        "url": r.get("url"), "lat": r["lat"], "lon": r["lon"], "price_thb": r.get("price_thb"),
        "area_rai": r.get("area_rai"), "description": r.get("description"),
        "other_urls": r.get("other_urls", []), "source": "harvest", "loc_quality": r["loc_quality"],
        "notes": "; ".join(r.get("warnings", [])) or None,
    }


def build(raw_dir: str | Path, results_dir: str | Path, out_dir: str | Path, listings_path: str | Path,
          radius_km: float, top_lakes: int) -> dict:
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    rows = []
    for f in sorted(raw_dir.glob("*.json")):
        rows += json.loads(f.read_text(encoding="utf-8"))
    recs = dedupe([normalise(r) for r in rows if r.get("id")])
    grade_pins(recs)
    sites = load_sites(Path(results_dir) / "house_sites.csv", top_lakes)
    attach_zone(recs, sites)
    keep = [r for r in recs if r.get("near_site_km") is not None and r["near_site_km"] <= radius_km]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "all.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")

    pins = [r for r in keep if r["loc_quality"] == "pin"]
    verify = [r for r in recs if r["loc_quality"] != "pin"]
    with open(out_dir / "to_verify.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "url", "prov", "dist", "tambon", "price_thb", "area_rai", "loc_quality",
                    "approx_lat", "approx_lon", "keywords", "warnings", "title"])
        for r in verify:
            w.writerow([r["key"], r.get("url"), r.get("prov"), r.get("dist"), r.get("tambon"), r.get("price_thb"),
                        r.get("area_rai"), r["loc_quality"], r.get("lat"), r.get("lon"),
                        ",".join(r["keywords"]), "; ".join(r["warnings"]), r.get("title")])

    lp = Path(listings_path)
    existing = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else []
    manual = [x for x in existing if x.get("source") != "harvest"]  # never touch hand-added listings
    lp.write_text(json.dumps(manual + [to_listing_item(r) for r in pins], ensure_ascii=False, indent=2),
                  encoding="utf-8")
    return {"rows": len(rows), "unique": len(recs), "in_zone": len(keep), "pins_scored": len(pins),
            "to_verify": len(verify)}


def shoreline(scored: list[dict], max_m: float = 300.0) -> dict[str, list[dict]]:
    """Split scored listings into lake/reservoir-front and river-front within ``max_m`` of permanent water."""
    out = {"lake": [], "river": []}
    for r in scored:
        d, wt = r.get("water_dist_m"), (r.get("water_type") or "")
        if d is None or d > max_m:
            continue
        out["lake" if wt.startswith("lake") else "river"].append(r)
    for v in out.values():
        v.sort(key=lambda r: (r["water_dist_m"], -r["fit_score"]))
    return out


def write_shoreline(scored: list[dict], out_dir: str | Path, max_m: float = 300.0) -> dict:
    groups = shoreline(scored, max_m)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "shoreline.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["kind", "water_dist_m", "fit_score", "verdict", "price_thb", "area_rai", "price_per_rai",
                    "distance_km", "lat", "lon", "flood_zone", "name", "url", "google_maps", "warnings"])
        for kind, rows in groups.items():
            for r in rows:
                w.writerow([kind, r["water_dist_m"], r["fit_score"], r["verdict"], r.get("price_thb"), r.get("area_rai"),
                            r.get("price_per_rai"), r.get("distance_km"), r["lat"], r["lon"], r.get("flood_zone"),
                            r["name"], r.get("url"), r.get("google_maps"), r.get("notes") or ""])
    return {k: len(v) for k, v in groups.items()}


def claims_report(all_path: str | Path, scored: list[dict], out_path: str | Path) -> int:
    """Ads whose text claims waterfront/lake, with the satellite distance to water at their pin."""
    recs = {r["id"]: r for r in json.loads(Path(all_path).read_text(encoding="utf-8"))}
    rows = []
    for sc in scored:
        m = re.search(r"\((?:DDP|ddproperty:)\s*(\w+)\)", sc["name"])
        r = recs.get(m.group(1)) if m else None
        if not r or not ({"waterfront", "lake"} & set(r.get("keywords", {}))):
            continue
        rows.append((sc.get("water_dist_m") if sc.get("water_dist_m") is not None else 1e9, sc, r))
    rows.sort(key=lambda x: x[0])
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["water_dist_m", "water_type", "claims", "fit_score", "price_thb", "area_rai", "dist", "prov",
                    "lat", "lon", "loc_quality", "url", "google_maps", "warnings"])
        for d, sc, r in rows:
            w.writerow([sc.get("water_dist_m"), sc.get("water_type"), "+".join(r["keywords"]), sc["fit_score"],
                        r.get("price_thb"), r.get("area_rai"), r.get("dist"), r.get("prov"), sc["lat"], sc["lon"],
                        r.get("loc_quality"), r.get("url"), sc.get("google_maps"), "; ".join(r.get("warnings", []))])
    return len(rows)


def select_waterfront(scored: list[dict], all_path: str | Path, max_m: float = 400.0) -> list[dict]:
    """Keep only listings next to water: satellite water within ``max_m``, or an ad that says waterfront.

    Each kept item gets ``waterfront_basis``: 'satellite' (verified at its pin) or 'ad claim' (unverified)."""
    recs = {r["id"]: r for r in json.loads(Path(all_path).read_text(encoding="utf-8"))} if Path(all_path).exists() else {}
    out = []
    for sc in scored:
        d = sc.get("water_dist_m")
        m = re.search(r"\((?:DDP|ddproperty:)\s*(\w+)\)", sc["name"])
        r = recs.get(m.group(1)) if m else None
        if d is not None and d <= max_m:
            basis = "satellite"
        elif r and "waterfront" in r.get("keywords", {}):
            basis = "ad claim"
        else:
            continue
        item = dict(sc, waterfront_basis=basis)
        if r and r.get("thumb"):
            item["thumb"] = r["thumb"]
        out.append(item)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build scored-listing input from raw browser harvests")
    p.add_argument("cmd", choices=["build", "shore", "claims", "publish"])
    p.add_argument("--raw", default="harvest/raw")
    p.add_argument("--results", default="results")
    p.add_argument("--out", default="harvest")
    p.add_argument("--listings", default="listings.json")
    p.add_argument("--radius", type=float, default=8.0, help="km from a house site (default 8)")
    p.add_argument("--top-lakes", type=int, default=5)
    p.add_argument("--scored", default="results/listings_scored.json")
    p.add_argument("--max-water-m", type=float, default=300.0, help="shoreline: max distance to water (default 300)")
    a = p.parse_args(argv)
    if a.cmd == "publish":
        from . import enrich, report
        scored = json.loads(Path(a.scored).read_text(encoding="utf-8"))
        keep = select_waterfront(scored, Path(a.out) / "all.json", a.max_water_m)
        print(report.write_records(enrich.load_records(a.results), a.results, listings=keep))
        return 0
    if a.cmd == "claims":
        scored = json.loads(Path(a.scored).read_text(encoding="utf-8"))
        print(claims_report(Path(a.out) / "all.json", scored, Path(a.out) / "waterfront_claims.csv"))
        return 0
    if a.cmd == "shore":
        print(write_shoreline(json.loads(Path(a.scored).read_text(encoding="utf-8")), a.out, a.max_water_m))
        return 0
    print(build(a.raw, a.results, a.out, a.listings, a.radius, a.top_lakes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
