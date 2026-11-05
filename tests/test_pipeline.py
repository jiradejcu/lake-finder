"""Synthetic-terrain tests (no network)."""
import numpy as np
import pytest

from lake_finder import BANGKOK
from lake_finder.analysis import Criteria, find_lakes, water_masks
from lake_finder.geo import Grid, haversine_km
from lake_finder.names import lookup_name
from lake_finder.report import write_all
from lake_finder.sources import dem_urls, gsw_urls, worldcover_urls
from lake_finder.viewpoints import ViewCriteria, compass, find_sites


def make_world(mountain=True):
    """A 40x40 km patch ~100 km from Bangkok: a round lake with a ridge on its east side,
    a flat plain on the west (the house side), and a thin river that must be ignored."""
    grid = Grid(west=99.6, north=14.3, res_deg=3 / 3600, width=480, height=480)
    rows, cols = np.mgrid[0:grid.height, 0:grid.width]
    lake_r, lake_c = 240, 240
    r = np.hypot(rows - lake_r, cols - lake_c)
    dem = np.full(grid.shape, 100.0, dtype="float32")
    dem += np.clip((r - 30) * 0.5, 0, 20)                       # gentle shore, rising 0.5 m/px
    if mountain:
        ridge = np.exp(-(((cols - 320) / 15.0) ** 2)) * 700       # 700 m ridge 80 px (~7 km) east
        dem += ridge.astype("float32")
    occ = np.zeros(grid.shape, dtype="float32")
    occ[r <= 30] = 100                                          # lake ~2.7 km radius
    occ[(r > 30) & (r <= 33)] = 20                              # seasonal draw-down ring
    occ[100:400, 60] = 100                                      # 1-px river, should be filtered
    return grid, dem, occ


def test_haversine_and_grid():
    assert haversine_km(13.7563, 100.5018, 14.0, 100.5018) == pytest.approx(27.1, abs=0.2)
    g = Grid.around(*BANGKOK, radius_km=100)
    assert g.west < BANGKOK[1] < g.east and g.south < BANGKOK[0] < g.north
    assert g.pixel_area_km2(np.array([0]))[0] == pytest.approx(0.0083, rel=0.02)


def test_tile_urls_cover_bangkok_region():
    g = Grid.around(*BANGKOK, radius_km=250)
    gsw = gsw_urls(g)
    assert any("90E_20N" in u for u in gsw) and any("100E_20N" in u for u in gsw)
    dem = dem_urls(g)
    assert any("N13_00_E100_00" in u for u in dem)
    assert any("N12E099" in u for u in worldcover_urls(g))


def test_finds_mountain_lake_and_ignores_river():
    grid, dem, occ = make_world()
    crit = Criteria(max_distance_km=300)
    lakes, labels, usual = find_lakes(occ, dem, grid, crit)
    assert len(lakes) == 1
    lake = lakes[0]
    assert lake.area_km2 == pytest.approx(np.pi * (30 * 0.0855) ** 2, rel=0.25)
    assert lake.relief_m > 500
    assert lake.peak_lon > lake.lon                  # the ridge is to the east


def test_flat_lake_is_rejected():
    grid, dem, occ = make_world(mountain=False)
    lakes, _, _ = find_lakes(occ, dem, grid, Criteria(max_distance_km=300))
    assert lakes == []


def test_house_sites_face_the_mountain_across_water():
    grid, dem, occ = make_world()
    crit = Criteria(max_distance_km=300)
    lakes, labels, usual = find_lakes(occ, dem, grid, crit)
    _, ever = water_masks(occ, dem, crit)
    sites = find_sites(lakes[0], labels, usual, ever, dem, grid, ViewCriteria())
    assert sites
    best = sites[0]
    assert best.lon < lakes[0].lon                   # house on the west shore...
    assert 45 <= best.best_bearing_deg <= 135        # ...looking east over the lake at the ridge
    assert best.water_width_m >= 500
    assert best.mountain_elev_m - lakes[0].surface_elev_m >= 250
    # never inside the draw-down zone
    r = int(round((grid.north - best.lat) / grid.res_deg - 0.5))
    c = int(round((best.lon - grid.west) / grid.res_deg - 0.5))
    assert occ[r, c] == 0


def test_reports(tmp_path):
    grid, dem, occ = make_world()
    crit = Criteria(max_distance_km=300)
    lakes, labels, usual = find_lakes(occ, dem, grid, crit)
    _, ever = water_masks(occ, dem, crit)
    for l in lakes:
        l.sites = find_sites(l, labels, usual, ever, dem, grid, ViewCriteria())
    summary = write_all(lakes, tmp_path)
    assert summary["lakes"] == 1
    html = (tmp_path / "map.html").read_text()
    assert "/*DATA*/" not in html and "World_Imagery" in html
    assert (tmp_path / "house_sites.csv").read_text().count("\n") == 1 + len(lakes[0].sites)


def test_name_lookup_prefers_water_and_english():
    class Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"elements": [
                {"type": "node", "lat": 14.0, "lon": 99.0, "tags": {"waterway": "dam", "name": "Some Dam"}},
                {"type": "way", "center": {"lat": 14.1, "lon": 99.1},
                 "tags": {"natural": "water", "name": "อ่างเก็บน้ำ", "name:en": "Reservoir"}},
            ]}

    class Session:
        def post(self, *a, **k): return Resp()

    assert lookup_name(14.0, 99.0, session=Session()) == "Reservoir (อ่างเก็บน้ำ)"
    assert compass(0) == "N" and compass(95) == "E" and compass(350) == "N"


def test_access_helpers():
    from lake_finder import access
    # road 1 km east of the point, running north-south
    ways = [("residential", [(14.0, 100.0 + 0.0093), (14.01, 100.0 + 0.0093)]),
            ("track", [(14.0, 100.0001), (14.01, 100.0001)])]   # unpaved: must be ignored
    d, cls = access.nearest_road(14.005, 100.0, ways)
    assert cls == "residential" and 950 < d < 1050
    data = {"elements": [{"type": "way", "tags": {"highway": "primary"},
                          "geometry": [{"lat": 1, "lon": 1}, {"lat": 1, "lon": 2}]}]}
    assert access.parse_ways(data)[0][0] == "primary"
    areas = {"elements": [{"tags": {"boundary": "national_park", "name": "Khao Yai"}},
                          {"tags": {"boundary": "administrative", "admin_level": "6", "name": "Pak Chong"}}]}
    assert access.parse_areas(areas) == ("Khao Yai", "Pak Chong")
    assert access.adjust_score(100, {"protected_area": "x"}) == 10.0
    assert access.adjust_score(100, {"road_dist_m": 4000}) == 50.0
    assert access.adjust_score(100, {}) == 100
