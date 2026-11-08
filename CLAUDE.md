# CLAUDE.md

Project: find lakeside land near Bangkok where a house would look **across the water at a mountain**.
Read `HANDOFF.md` first. It has the goal, current results, the listing analysed, environment/network facts
and next steps. `README.md` covers usage.

- Default branch: `master`.
- Setup: `pip install -r requirements.txt pytest`. Tests: `python -m pytest` (offline, synthetic terrain).
- Full run: `python -m lake_finder` (first run downloads ~100 MB into `cache/`, which is gitignored).
- `results/` is a committed snapshot **with OSM access data**. Don't overwrite it with a plain
  `python -m lake_finder --out results` unless you re‑run `python -m lake_finder.enrich` afterwards
  (see HANDOFF.md §2).
- Overpass (OSM) is unreachable from the cloud sandbox; names/access lookups must run locally or via a mirror.
- Listings live in `listings.json`; only tb.co.th pages can be parsed automatically.
- When sharing results with the owner, give coordinates with Google Maps links, and say clearly
  when land may be protected (national park, forest reserve, ส.ป.ก.).
