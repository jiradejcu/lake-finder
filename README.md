# lake-finder

Find **lakes and reservoirs next to mountains, within driving distance of Bangkok**, and on each shore find
**house sites at the water's edge with the lake in front and mountains behind it**.

Everything comes from free satellite data. No API keys are needed.

| What | Dataset | Resolution |
|---|---|---|
| Water | [JRC Global Surface Water](https://global-surface-water.appspot.com/): Landsat 1984‑2021, % of time each pixel was water | 30 m |
| Water (alternative) | [ESA WorldCover 2021](https://esa-worldcover.org/): Sentinel‑1/2 land cover, class 80 = water | 10 m |
| Terrain | [Copernicus GLO‑90 DEM](https://registry.opendata.aws/copernicus-dem/): TanDEM‑X elevation | 90 m |
| Names (optional) | OpenStreetMap via the Overpass API | – |

Rasters are streamed as Cloud‑Optimized GeoTIFFs. Only the needed blocks are downloaded, then resampled
onto a single ~90 m grid and cached in `cache/`.

## How it works

1. **Water bodies.** Pixels that are water ≥ 50 % of the time count as usual water. A morphological
   opening removes thin rivers and canals. Connected components become lakes, and arms of the same
   reservoir are merged back together. Sea, estuaries and salt pans (surface ≈ sea level) are dropped,
   as are lakes smaller than `--min-area`.
2. **Next to a mountain.** Within 10 km of the shore, terrain must rise at least `--min-relief` m
   (default 250 m) above the water surface. The nearest such terrain must be within
   `--max-mountain-dist` km (default 6 km).
3. **Lake view with the mountain behind.** For candidate shore pixels, sight lines are cast in 36
   compass directions, up to 15 km, with Earth curvature and refraction included. A direction is a
   *lake + mountain view* when:
   - the line reaches the water within 300 m (the house faces the lake),
   - at least `--min-water` m (default 500 m) of the line is over water,
   - the skyline point (the highest‑looking terrain, i.e. what you actually see on the horizon) is
     ≥ 250 m above the lake and ≥ 1.5° above eye level, seen from a 5 m balcony.
4. **Buildable site.** The site must be dry land that never appears as water in the 38‑year satellite
   record. That keeps it outside the reservoir's maximum extent and draw‑down zone. Slope must be
   ≤ `--max-slope`°, and the site must be 0–40 m above the usual water level.
5. **Ranking.** Site score = sum over good directions of the mountain's apparent height (capped at
   15°). This rewards wide panoramas of tall mountains. Lake score = best site score ÷
   (1 + distance / 150 km).

## Usage

```bash
pip install -r requirements.txt
python -m lake_finder                  # Bangkok, 250 km radius (~2 min first run, ~100 MB download)
python -m lake_finder --names          # also fetch lake names from OpenStreetMap
python -m lake_finder --max-distance 150 --min-relief 400 --top 10
python -m lake_finder --water-source worldcover
python -m lake_finder --lat 18.79 --lon 98.98 --city-name "Chiang Mai"
```

Outputs, written to `output/` by default:

- `map.html`: interactive map on satellite imagery. Blue = lake, red = house site, dashed yellow = view
  line to the mountain. Popups link to Google Maps.
- `lakes.csv`: one row per lake (distance, area, peak, relief…).
- `house_sites.csv`: one row per site (coordinates, facing direction, view width, water width,
  mountain height, distance and apparent angle, slope, height above the water).
- `results.geojson`: the same data for QGIS / Google Earth / geojson.io.

The `results/` folder holds a snapshot run with the default settings for Bangkok.

To view a map in the browser, run `python -m lake_finder.serve` (or `--dir output`) and open
http://localhost:8765/map.html. The preview server turns off caching and reloads the tab whenever a
file in the folder changes. It listens on this machine only.

## Access check (roads, neighbours, protected land)

```bash
python -m lake_finder.enrich --in results --out results --top 20
```

Queries OpenStreetMap (Overpass) for each house site: distance to the nearest paved road, buildings within
500 m, district, and whether the site lies inside a national park / protected area (score ×0.1). Sites more
than 2 km from a paved road are demoted. Overpass is slow, so use `--top N` to check only the best lakes;
answers are cached in `access_cache.json`, and lakes not checked keep their original score.
Missing values mean the lookup failed or OSM has nothing there, not that the answer is "none".

## Scoring land for sale

Add land listings to `listings.json`. Each one needs `lat`/`lon`, or a `url` from tb.co.th, whose pages
contain the pin location, price and description. Every run scores each listing with the same satellite
and terrain checks. It shows up as a purple diamond on the map, with a verdict, a 0–100 fit score, pros
and cons, and the best lakeside sites within 20 km for comparison. Results also go to `listings.csv` and
`listings_scored.json`. `lake_finder.enrich` keeps them when it rewrites the map.

```bash
python -m lake_finder --add-listing "https://tb.co.th/property/...p.142449"   # read & save a listing
python -m lake_finder --listings my_listings.json
```

Fit score (0–100): 40 for a view across water to mountains, 20 for being on the water (lakes count more
than rivers), 20 for how much mountain is on the skyline and how high it rises above the water, 20 for
buildable ground (gentle slope, never flooded).

`listings.json` currently holds one listing: 6 rai 50 sq wah in Nong Ya, Mueang Kanchanaburi, 4.8 M THB
(T‑142449). Verdict: **mountain view, water nearby**, fit 37/100. It sits about 280 m from the
Khwae Noi river, with 300 m+ hills 2.5–4 km to the east, but there's no open water between the plot and
the hills. Lake #1 (Tha Muang District) has lakeside sites with mountain views 6–9 km away.

## Results for Bangkok (default settings)

64 water bodies within 250 km have mountains next to them and at least one shoreline site with a
lake‑and‑mountain view. The top 20 were checked for access with OpenStreetMap. Districts come from OSM;
lake names are still missing (Overpass was unreachable from the cloud sandbox).

| # | Area (district) | km from BKK | Best site (lat, lon) → view | Paved road |
|---|---|---|---|---|
| 1 | Tha Muang, Kanchanaburi | 103 | 13.98458, 99.56375 → S | 470 m (another site 69 m) |
| 2 | Thong Pha Phum, Kanchanaburi (Khao Laem reservoir) | 249 | 14.71375, 98.57542 → E | 1.3 km |
| 3 | Mueang Nakhon Nayok | 108 | 14.30125, 101.32875 → E | 935 m |
| 4 | Pak Thong Chai, Nakhon Ratchasima | 166 | 14.56958, 101.81542 → NW | ? |
| 5 | Makham, Chanthaburi | 209 | 12.80292, 102.16958 → N | 408 m |

Srinagarind, Khao Yai (Khun Dan Prakan Chon), Pang Sida and Thap Lan reservoirs score well on views but lie
inside national parks, so the access check pushes them down. See `HANDOFF.md` for the full picture.

## Caveats: check before buying land

- **Protected land.** Many reservoir shores in Thailand are inside national parks (Srinagarind,
  Kaeng Krachan, Khao Yai…), forest reserves, or land owned by the Royal Irrigation Department or EGAT,
  where private building isn't allowed. Check the land title (โฉนด / น.ส.3) and the zoning.
- Distances are straight‑line, not driving distance.
- The DEM is 90 m. Small terraces, roads and existing buildings aren't visible at that resolution.
  Visit the site, or at least check the satellite layer in `map.html`.
- Reservoir levels vary a lot between dry and wet seasons. Sites are kept outside the maximum observed
  extent, but ask locally about flooding.

## Tests

```bash
pip install pytest && python -m pytest
```

The tests use synthetic terrain (a lake with a ridge beside it) and need no network.
