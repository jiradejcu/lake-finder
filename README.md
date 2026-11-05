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

## Access check (roads, neighbours, protected land)

```bash
python -m lake_finder.enrich --in results --out results --top 20
```

Queries OpenStreetMap (Overpass) for each house site: distance to the nearest paved road, buildings within
500 m, district, and whether the site lies inside a national park / protected area (score ×0.1). Sites more
than 2 km from a paved road are demoted. Overpass is slow, so use `--top N` to check only the best lakes;
answers are cached in `access_cache.json`, and lakes not checked keep their original score.
Missing values mean the lookup failed or OSM has nothing there, not that the answer is "none".

## Results for Bangkok (default settings)

64 water bodies within 250 km have mountains next to them and at least one shoreline site with a
lake‑and‑mountain view. Top of the list, with likely names from their location (confirm with `--names`):

| # | Likely place | km from BKK | Area km² | Peak m | Best site (lat, lon) → view |
|---|---|---|---|---|---|
| 1 | Srinagarind Dam reservoir, Kanchanaburi | 183 | 330 | 1188 | 14.94542, 99.10208 → NNE |
| 2 | Mae Klong river / Tha Muang area, Kanchanaburi | 103 | 5.4 | 459 | 13.98458, 99.56375 → S |
| 3 | Vajiralongkorn (Khao Laem) Dam reservoir, Kanchanaburi | 249 | 239 | 1543 | 14.71375, 98.57542 → E |
| 4–5 | Reservoirs on the south side of Khao Yai, Nakhon Nayok (Khun Dan Prakan Chon area) | ~100 | 0.7–2.3 | 937–1274 | 14.31375, 101.21208 → E |
| 8 | Kaeng Krachan Dam reservoir, Phetchaburi | 136 | 35 | 731 | 12.92042, 99.61792 → NE |
| 13 | Lam Takhong reservoir, Nakhon Ratchasima | 161 | 20 | 764 | 14.83208, 101.53708 → SE |

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
