# Handoff notes: everything known so far

Last updated 2026-11-08 (now running in WSL; map deselect, live-reload preview server). Read this together with `README.md` (usage) and `CLAUDE.md` (working rules).

## 1. What the owner wants

> Build a house **at the water's edge** with a **lake view and a mountain behind the lake**,
> **not far from Bangkok**.

So the target isn't just "a lake near a mountain". It's a **buildable shore plot** where the view goes
house → open water → far shore → mountain on the skyline. Land for sale is judged against the same
standard.

## 2. What exists (all on `master`)

| Piece | File | Notes |
|---|---|---|
| Grid + geodesy | `lake_finder/geo.py` | ~90 m (3″) lat/lon grid around a city |
| Data download | `lake_finder/sources.py` | JRC GSW water occurrence (default) or ESA WorldCover; Copernicus GLO‑90 DEM. COGs read through GDAL `/vsicurl`, warped to the grid, cached as `.npy` in `cache/` |
| Lake detection | `lake_finder/analysis.py` | water ≥ 50 % occurrence → opening (removes rivers) → components; arms re‑joined; drops sea (surface < 3 m), size limits; needs ≥ 250 m relief within 10 km and mountain ≤ 6 km from shore |
| House sites | `lake_finder/viewpoints.py` | `cast_views()` sight lines (36 bearings, 15 km, 5 m eye height, curvature + refraction). Site = dry land never seen flooded, slope ≤ 10°, 0–40 m above water |
| Listings | `lake_finder/listings.py` | `listings.json` → parses tb.co.th pages → `evaluate_listing()` → verdict, fit 0–100, pros/cons, nearby lakeside sites |
| Reports | `lake_finder/report.py` | `lakes.csv`, `house_sites.csv`, `listings.csv`, `listings_scored.json`, `results.geojson`, `map.html` (Leaflet + Esri satellite, province overlay, listings layer). Clicking a pin or list item highlights it; clicking empty map clears it (circle markers use `bubblingMouseEvents:false` so only empty-map clicks reach `map.on('click')`) |
| Preview server | `lake_finder/serve.py` | `python -m lake_finder.serve [--dir results] [--port 8765]`. Stdlib only. Listens on 127.0.0.1 and ::1 only, sends `Cache-Control: no-store`, injects an EventSource script into served HTML (files on disk unchanged), and reloads the tab when any file in the folder changes |
| Access check | `lake_finder/access.py`, `lake_finder/enrich.py` | Overpass: nearest paved road, buildings within 500 m, district, national park. Protected → score × 0.1; road > 2 km → demoted. Cache in `results/access_cache.json` (52 sites) |
| Names | `lake_finder/names.py` | Overpass lookup, `--names` flag. **Never succeeded from the cloud sandbox**, so all lakes are still "Water body #N" |
| CLI | `lake_finder/cli.py` | `python -m lake_finder [...]`, `--listings`, `--add-listing URL` |
| Tests | `tests/` | 13 tests, synthetic terrain, no network. `python -m pytest` |

Full run: `python -m lake_finder` (~2 min, ~100 MB on the first run, then instant from `cache/`).

### Regenerating `results/` without losing the access data
Running `python -m lake_finder --out results` **overwrites the OSM access info** in the CSVs. Either re‑run
`python -m lake_finder.enrich --in results --out results --top 20` afterwards (uses the cache; needs Overpass
for uncached sites), or, to only re‑score listings, do what was done last time:
load records with `enrich.load_records('results')`, score listings with `evaluate_listing`, then
`report.write_records(records, 'results', listings=...)`. `write_records(..., listings=None)` keeps the
listings already scored in that folder.

## 3. Current results (snapshot in `results/`, after the access check)

64 water bodies within 250 km of Bangkok have a mountain next to them and at least one site with a
lake‑and‑mountain view (136 sites). Ranking after the OSM access check (top 20 lakes checked):

| # | Water body | District (OSM) | km from BKK | Best site | Road to site | Comment |
|---|---|---|---|---|---|---|
| 1 | #546 | Tha Muang, Kanchanaburi | 103 | 13.98458, 99.56375 → S, 389 m hill 1.8 km | 470 m | Not protected; 0 buildings within 500 m. Other sites: 13.97792, 99.57958 (road 69 m), 13.99458, 99.55375 (road 91 m) |
| 2 | #171 | Thong Pha Phum, Kanchanaburi | 249 | 14.71375, 98.57542 → E | 1.3 km | Vajiralongkorn (Khao Laem) reservoir area; far from Bangkok |
| 3 | #408 | Mueang Nakhon Nayok | 108 | 14.30125, 101.32875 → E | 935 m | South of Khao Yai |
| 4 | #304 | Pak Thong Chai, Nakhon Ratchasima | 166 | 14.56958, 101.81542 → NW | unknown | |
| 5 | #976 | Makham, Chanthaburi | 209 | 12.80292, 102.16958 → N | 408 m | |
| 6 | #959 | Kaeng Krachan, Phetchaburi | 136 | 12.92042, 99.61792 → NE | unknown | Kaeng Krachan reservoir; one site is inside the national park |
| 7 | #110 | Lam Sonthi, Lopburi | 208 | 15.43958, 101.36042 → ESE | 871 m | |
| 8 | #981 | Khlung, Chanthaburi | 228 | 12.76875, 102.33958 → NE | 255 m | |
| 9 | #1095 | Kui Buri, Prachuap | 207 | 12.08708, 99.67875 → SSE | 64 m | |
| 12 | #419 | Mueang Kanchanaburi | 148 | 14.23542, 99.22292 → E | 289 m | One site inside Erawan NP |
| 13 | #266 | Dan Chang, Suphan Buri | 163 | 14.78292, 99.42792 → E | 90 m | |

**Dropped because they're in national parks** (score × 0.1): #213 **Srinagarind** (was #1 before the
access check; Khuean Srinagarindra NP, now #31), #407 Khun Dan Prakan Chon area (Khao Yai NP, #39), #560
(Pang Sida NP), #434 (Thap Lan NP). Lake names in this table are inferred from location; confirm with OSM.

## 4. Listing checked: T‑142449, Nong Ya, Mueang Kanchanaburi

- 6 rai 50 sq wah (6.125 rai), **4,800,000 THB** (≈ 783,700 THB/rai), plot 40 × 225 m, faces S, title
  **น.ส.3ก** (not a full chanote/โฉนด). Electricity, groundwater well with automatic sprinklers.
  Listed as about 2 h from Bangkok via motorway M81, 8 km to Kanchanaburi town, **Khwae Noi river 140 m**.
- Pin from the tb.co.th page: **13.984142, 99.496038**. Agent: The Best Property Agent Co. (tb.co.th),
  Line OA `@ssz9615w`. Same ad on DDproperty 500355245, Livinginsider 3102134, Thaihometown 5221311,
  Teedin108 4050196, Hipflat/Dotproperty/Trovit/Mitula/Nestoria `019ea0ae-a024-7152-be24-29533abf8e12`,
  Baania, Baanfinder 18640751, Homehug 111527451, Tperty 1567595, Baantookjai 44761, 2homemarket 51012.
- Analysis: elevation 34 m, flat (0.7°), never flooded (nearest flooded pixel 186 m). Nearest permanent
  water is the river, **~280 m** (a 90 m grid can't resolve the 140 m claim). Hills 285–342 m are 2.5–4 km E/ESE,
  and 471 m at 10 km WNW. **No open water between the plot and the hills.**
- **Verdict: "Mountain view, water nearby", fit 37/100.** Good farm/resort land, not a lake‑view plot.
- The best alternative is **lake #1 (Tha Muang), 6–9 km east**. Look for land near 13.978, 99.580 or 13.985, 99.564.

## 5. Environment / network facts (cloud sessions)

- Personal cloud environment **"lake-finder"** was created (limited network) with these hosts:
  tb.co.th, www.livinginsider.com, www.ddproperty.com, www.thaihometown.com, www.teedin108.com,
  overpass-api.de, storage.googleapis.com, copernicus-dem-90m.s3.amazonaws.com,
  esa-worldcover.s3.eu-central-1.amazonaws.com (+ package registries). Use it for new sessions.
- Works: Copernicus DEM, JRC GSW, ESA WorldCover, tb.co.th, PyPI/npm, cdn.jsdelivr.net (province GeoJSON).
- Doesn't work from the sandbox:
  - **overpass-api.de**: the tunnel opens, then the connection is reset (names and access checks fail).
    It did work for whoever produced the access cache, so run Overpass work locally, or try a mirror
    (overpass.kumi.systems is already a fallback in `access.py` but isn't on the allowlist).
  - livinginsider and teedin108 return 403; thaihometown resets the connection; ddproperty was untested
    (likely bot‑blocked).
  - server.arcgisonline.com (Esri tiles) and unpkg.com (Leaflet) are blocked, so the map renders without imagery
    in headless screenshots. For screenshots: `npm pack leaflet@1.9.4`, then route `https://unpkg.com/**` to the local
    `dist/` folder in Playwright.
- `rasterio`, `scipy` and `pytest` must be pip‑installed in a fresh container (`pip install -r requirements.txt pytest`).
- `http://localhost:8765/map.html` is served by `python -m lake_finder.serve` (see §2). It only exists on
  the machine where it was started.

## 5b. Local machine (owner's PC) and the move to WSL

The owner worked locally on Windows 11 (repo at `D:\Workspace\Personal\lake-finder`, VS Code + Claude Code,
Claude in Chrome for browser tests) and is **moving to WSL** from 2026-11-08. Why: `rasterio` wasn't
installed on Windows (most tests couldn't run), Python console windows kept popping up, and LF/CRLF warnings.

Setting up in WSL:
1. Clone into the Linux filesystem, not `/mnt/d/...` (much faster):
   `git clone git@github.com:jiradejcu/lake-finder.git ~/lake-finder` (needs a GitHub SSH key in WSL).
2. `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest`, then
   `python -m pytest` (all tests should pass; on Windows 2 test files failed to import without rasterio).
3. `cache/` is gitignored. The first full run downloads ~100 MB again. You could copy `D:\...\lake-finder\cache`
   from `/mnt/d/Workspace/Personal/lake-finder/cache` to skip that.
4. Preview: `python -m lake_finder.serve &`, then open http://localhost:8765/map.html in Windows Chrome
   (WSL2 forwards localhost). Before starting it, stop any leftover Windows server on 8765.
5. Not yet verified: whether Claude in Chrome connects to a Claude Code session running in WSL. Check it on the
   first browser test and record the answer here.

Current state (first WSL session, 2026-11-08):
- Claude Code runs in WSL (Linux 6.6, WSL2) but the repo is still at `/mnt/d/Workspace/Personal/lake-finder`
  (not yet cloned into `~/lake-finder`; that remains the faster option).
- System `python3` has **no** `pytest`, `rasterio` or `scipy`, and there is no `.venv` or `cache/` yet. Run step 2 above
  before tests or a full run. No preview server is running.
- On `/mnt/d` every file looked modified because of file-mode bits (644 vs 755). Fixed locally with
  `git config core.fileMode false`; the clone needs the same if it stays on `/mnt/d`. CRLF warnings remain (files are CRLF in the working copy).
- Branch `master` only, working tree clean, nothing unpushed known. Claude in Chrome from WSL is still unverified.

## 6. Known limitations and gotchas

- 90 m DEM: no small terraces, existing buildings or roads; site heights and slopes are approximate.
- Lake "centroid" (`lat`/`lon` in `lakes.csv`) can fall off the water for odd‑shaped reservoirs. Use site coordinates.
- `water_dist_m` for listings is measured to GSW pixels ≥ 50 % occurrence; narrow rivers (< ~60 m) may be missed or offset.
- Distances are straight‑line, not driving.
- A site not flagged as protected may still be forest reserve (ป่าสงวน), ALRO land (ส.ป.ก.), or RID/EGAT land.
  OSM doesn't cover these well. Check with the Land Department (LandsMaps) before buying.
- `enrich.load_records` used to crash on ranks saved as `1.0`. Fixed, with a regression test.

## 7. Suggested next steps

1. Get lake names: run `python -m lake_finder --names` locally, or add an Overpass mirror host to the
   environment and to `names.py`.
2. Search land listings **near the top sites** (especially lake #1 Tha Muang, #3 Nakhon Nayok, #9 Kui Buri) and
   add them to `listings.json` (lat/lon by hand when the site isn't tb.co.th).
3. More listing parsers (DDproperty/Livinginsider need a browser or an API; they block plain HTTP).
4. Driving time from Bangkok (OSRM/Google), and land‑title / zoning checks (LandsMaps, ผังเมือง).
5. Optional: recent Sentinel‑2 imagery for current water levels; price‑per‑rai comparison across listings.

## 8. Listing harvest (added 2026-11-08)

New: `lake_finder/harvest.py` + `harvest/README.md` (recipe, verified DDproperty district codes, pitfalls).
- Claude in Chrome **does connect from WSL** (resolved the open question in §5b).
- Harvested DDproperty land ads in the districts of the top-5 lakes (Tha Muang, Thong Pha Phum, Muang Nakhon Nayok, Pak Thong Chai,
  Makham): 101 ads, 70 with their own pin, 31 on a shared centroid. 26 pins lie within 12 km of a house site and are now scored on the map.
- **Result: none is a lake-view plot.** Best fit 43/100 (DDP 500323310, Makham, 11.2 rai, 692 m from a stream, mountains N).
  Nearest to a lakeside site: DDP 500672450 (Nakhon Nayok, 1.5 km from a site, 22.9 rai, 73 M THB, 15.6 deg slope, fit 30).
  Portal ads in these districts are farmland; true shore plots are rare and often state land.
- Not done yet: Livinginsider / Thaihometown / Teedin108 / Hipflat adapters; neighbouring districts (shores span several, e.g. Khao Laem
  reservoir); the 31 centroid-pinned ads (ask agents for exact pins; `harvest/to_verify.csv` is empty only because compact rows were
  filtered to pins); lakes ranked 6+. Facebook is read-only and low-yield (see harvest/README.md).
- Chrome permission prompt: a "local network / location" prompt appeared after a page tried to POST to localhost. Block it.

### 8b. Waterfront-only search (same day, later session)
Owner's rule: **only land next to water; land with a house is also fine; request pause 1 s is enough.**
- Harvested 17 districts (land + houses, DDproperty): 254 land ads + 63 house ads. House ads give built-up area only (no
  "(land)"), so `parse_area_rai` ignores them. `python -m lake_finder.harvest shore` (pins within `--max-water-m` of lake/river
  water, satellite check) and `... claims` (ads whose *text* says ติดน้ำ/ริมน้ำ/ติดอ่าง..., ranked by satellite distance)
  write `harvest/shoreline.csv` and `harvest/waterfront_claims.csv`.
- **Result: no verified lake-front plot.** Within 400 m of water: DDP 500022579 (Kui Buri, house, claims lake, 91 m),
  DDP 500507442 (Tha Muang, 331 m, 1.65 M THB, claims lake), DDP 500479975 (Tha Maka, 2.1 rai, 12.5 M, river 203 m),
  DDP 500465217 (Muang Kanchanaburi, 286 m river), and the original T-142449 (river 278 m). None has a lake-and-mountain view
  at its pin (fit 30-39). Most "waterfront" claims are >1 km from satellite water: small streams/ponds or imprecise agent pins.
- Pins are the weak link: call the agent / open the ad, then correct `lat`/`lon` in `listings.json`.
- Livinginsider: free-text search ignores keywords from the home page (lands on the rent page); not pursued.

## 9. State at the end of the 2026-11-08 session, and plan for the new always-on server

The owner is moving the project to a different always-on server and asked to **save everything and not start new work until setup is done**.

### Owner's decisions (apply from now on)
- **Only land next to water.** Land **with a house** is also fine. Price and size don't matter (negotiable). About 4 h from Bangkok is a
  bit long but can still be considered.
- **Drop the portal (DDproperty) listings. Focus on Facebook**, "a lot more potential". The map currently shows only the owner's
  hand-added Nong Ya listing (T-142449, river 278 m). Ask before deleting that one too.
- Facebook may be searched with the owner's logged-in Chrome (Claude in Chrome), **read-only**: no joining groups, posting, commenting
  or messaging sellers.
- **Approximate pins are OK, ideally with a circle of uncertainty.** Place a lead at the best-known spot (named subdistrict, dam or
  lake shore) with a circle whose radius matches how vague the location is (e.g. ~1 km for a village, ~3-5 km for a tambon), label it
  "approximate" and keep `loc_quality: approx` in the data. Not built yet.
- **Thumbnails in the pin** for quick visualising. `report.py` already shows `p.thumb` (image above the verdict) and a
  `waterfront_basis` label in the popup and sidebar, but no listing has one now. Plan: save each lead's photo as a **screenshot crop**
  (`computer` `zoom` with `save_to_disk`) into `results/thumbs/<id>.png` and set `thumb` to that relative path.
  Do **not** try to fetch portal/CDN images with spoofed User-Agent/Referer headers: the auto-mode classifier blocks that as bot-check
  circumvention (DDproperty's `th1-cdn.pgimgs.com` returns 403 to plain curl).

### What exists now (all on `master`)
- `lake_finder/harvest.py` (+ `tests/test_harvest.py`, 21 tests pass): normalise browser-collected rows, grade pins (`pin` / `shared`
  centroid / `none`), dedupe, zone filter, `build`, `shore` (pins within N m of water), `claims` (ads whose text says waterfront),
  `publish` / `select_waterfront` (write only waterfront listings into `results/`).
- `harvest/README.md`: the DDproperty recipe (verified district codes, in-page fetch job, output limits). `harvest/raw/*.json`,
  `all.json`, `shoreline.csv`, `waterfront_claims.csv` are the archived results (not on the map).
- `facebook/leads.md`: the Facebook leads found so far (below).

### Facebook: how it works (verified)
- Logged in as the owner in Chrome. Public group search works without joining:
  `https://www.facebook.com/groups/<id>/search/?q=<thai words>` (also `/search/groups?q=...` to find groups, `/search/posts?q=...`).
- Each search only renders ~3-4 posts; scroll with `window.scrollBy` and 2 s pauses to load a few more.
- Post text: `document.body.innerText` lines filtered for `ไร่|ล้าน|บาท|แสน|เขื่อน|อ่าง|ติดน้ำ|วิว` works. `role="article"` does **not**.
  The DOM exposes no permalinks, Google Maps links or coordinates in search results, so a lead is "group + search word".
- Tool output from the page is capped (~1 KB), `browser_batch` (navigate + wait + JS per page) is the efficient way to sweep several
  groups and queries. Posting to `http://localhost` from a page hangs behind Chrome's local-network prompt (Block it).
- Groups: 261278386002393 (บ้านและที่ดินติดแม่น้ำ ติดคลอง วิวเขา ทั่วประเทศ), 374887530519395 (ที่ดิน ติดแม่น้ำ ติดเขา วิวสวย ทั่วประเทศ),
  1067484823904943 (ซื้อขายที่ดินติดน้ำ ที่ดินวิวเขาสวย ทั่วไทย), 2579213389026077 (ขายที่ดินนครนายก), 578959672993971 and 570399346988669
  (ติดแม่น้ำวิวภูเขาแปลงเล็กใกล้กรุงเทพ), 131684337532579 (ที่ดินติดน้ำแปลงสวย), 1052985162145992 (วังน้ำเขียว), 717521746622716 (ปากช่อง).

### Facebook leads so far (details in `facebook/leads.md`)
1. Si Sawat, Kanchanaburi, above Srinagarind dam (ต.ท่ากระดาน): 5 rai 3 ngan 94 sq wah, **โฉนดครุฑแดง**, 2.3 M THB, "water and mountain view, never floods".
2. Si Sawat: 3 rai 1 ngan at 500-550 k THB/rai, "view of Srinagarind, north of the dam, never floods" (two posts).
3. Srinagarind shore, **422 rai, 7.5 M THB** (≈18 k/rai, suspiciously cheap: check lease/reserve), floating-raft business included.
4. Thong Pha Phum, Kanchanaburi: **2-storey building 495 m² on 1 rai on the Kwai Noi river**, 2.5 km from the district office.
5. Kanchanaburi: 45 rai on the Kwai Yai river, developed.
6. Nakhon Nayok: waterfront 1+ rai with one house; waterfront durian orchard 5 rai 14 sq wah; mountain-view plots at Ban Na.
Srinagarind lies in/next to Khuean Srinagarindra NP (the access check ranked it down); red-eagle chanote = private title but verify on LandsMaps.
Si Sawat is ~4 h from Bangkok.

### DDproperty findings (archived, why it was dropped)
Harvested 17 districts (254 land + 63 house ads). No verified lake-front plot: only 5 pins within 400 m of water (Tha Muang 331 m "lake",
Kui Buri house 91 m, Tha Maka river 203 m, Muang Kanchanaburi river 286 m, Nong Ya river 278 m), all with fit 30-39. Most "waterfront"
claims were >1 km from satellite water (streams/ponds or imprecise pins).

### Next steps once the new server is ready (not started)
1. Set up: clone the repo, `python3 -m venv .venv && pip install -r requirements.txt pytest`, `python -m pytest` (21 pass). `cache/` (~257 MB, gitignored)
   re-downloads on the first full run (or copy it). Chrome with the owner's Facebook login plus Claude in Chrome must be reachable from the
   session. Keep **one** preview server on port 8765 (`python -m lake_finder.serve`).
2. Build a Facebook leads layer: `facebook/leads.json` (id, text summary, price, area, title type, group, search word, `lat`/`lon`,
   `loc_quality: approx`, `radius_m`, `thumb`), rendered on the map as a pin plus an uncertainty circle (L.circle, dashed), with the
   thumbnail in the popup and a "NP / forest-reserve warning" where relevant. Approximate pins: use the named tambon/dam/lake shore
   (the lake coordinates in `results/lakes.csv` and `house_sites.csv` help), and say clearly it is approximate.
3. Sweep more groups and queries with `browser_batch` (Srinagarind/Si Sawat, Khao Laem/Thong Pha Phum, Nakhon Nayok, Kaeng Krachan,
   Kui Buri, Khlung/Makham), keep only posts that are next to water, record each in `leads.json`, save thumbnails as screenshot crops.
4. Commit and push at each verified milestone; test the map in Chrome after every UI change (reload, check `DATA.listings.length`).
