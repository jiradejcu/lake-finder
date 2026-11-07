"""Listing parsing and scoring (no network)."""
import json

from lake_finder.analysis import Criteria, find_lakes, water_masks
from lake_finder.listings import evaluate_listing, load_listings, parse_tb_page, parse_thai_area_rai
from lake_finder.report import write_all
from lake_finder.viewpoints import ViewCriteria, find_sites
from test_pipeline import make_world

TB_SNIPPET = ('<title>ขายที่ดิน เนื้อที่ 6 ไร่ 50 ตารางวา ต.หนองหญ้า เมืองกาญจนบุรี</title>'
              '<script>x={lat:"13.98414200",lng:"99.49603800",area_width:"40.00",area_deep:"225.00",'
              'property_direction:"S",explanation:"ที่ดิน นส3ก.\\r\\n- แม่น้ำแควน้อย 140 ม.",'
              'sale_price:"4800000.00",rental_price:"0.00"}</script>')


def test_parse_area():
    assert parse_thai_area_rai("6 ไร่ 50 ตารางวา") == 6.125
    assert parse_thai_area_rai("1 ไร่ 2 งาน 100 ตร.ว.") == 1.75
    assert parse_thai_area_rai("no area") is None


def test_parse_tb_page():
    info = parse_tb_page(TB_SNIPPET)
    assert info["lat"] == 13.984142 and info["lon"] == 99.496038
    assert info["price_thb"] == 4_800_000 and info["area_rai"] == 6.125
    assert info["plot_m"] == "40 x 225 m" and "แควน้อย" in info["description"]


def test_load_listings_fetches_missing_coordinates(tmp_path):
    class Resp:
        text = TB_SNIPPET
        def raise_for_status(self): pass

    class Session:
        def get(self, *a, **k): return Resp()

    f = tmp_path / "l.json"
    f.write_text(json.dumps([{"url": "https://tb.co.th/property/x.p.1"}, {"name": "no coords"}]))
    items = load_listings(f, session=Session())
    assert len(items) == 1 and items[0]["lat"] == 13.984142


def _world():
    grid, dem, occ = make_world()
    crit = Criteria(max_distance_km=300)
    lakes, labels, usual = find_lakes(occ, dem, grid, crit)
    _, ever = water_masks(occ, dem, crit)
    vc = ViewCriteria()
    for l in lakes:
        l.sites = find_sites(l, labels, usual, ever, dem, grid, vc)
    return grid, dem, occ, labels, lakes, crit, vc


def test_lakeside_listing_scores_high_and_far_one_low(tmp_path):
    grid, dem, occ, labels, lakes, crit, vc = _world()
    west_shore = {"name": "shore", "lat": float(grid.lat_of_row(240)), "lon": float(grid.lon_of_col(240 - 34)),
                  "price_thb": 2_000_000, "area_rai": 2}
    inland = {"name": "inland", "lat": float(grid.lat_of_row(60)), "lon": float(grid.lon_of_col(150))}
    a = evaluate_listing(west_shore, dem, occ, labels, grid, lakes, crit, vc)
    b = evaluate_listing(inland, dem, occ, labels, grid, lakes, crit, vc)
    assert a.verdict == "Lakeside with mountain view" and not a.flood_zone
    assert a.price_per_rai == 1_000_000
    assert b.lake_mountain_view_deg == 0 and b.fit_score < a.fit_score
    assert a.nearby_sites and a.nearby_sites[0]["km"] < 5

    from lake_finder.listings import report_dict
    summary = write_all(lakes, tmp_path, listings=[report_dict(a), report_dict(b)])
    assert summary["listings"] == 2
    html = (tmp_path / "map.html").read_text()
    assert "Land for sale" in html and "Lakeside with mountain view" in html
    assert (tmp_path / "listings.csv").read_text().splitlines()[1].startswith("shore")


def test_enrich_reload_roundtrip_keeps_listings(tmp_path):
    """write_records -> load_records -> write_records works and keeps scored listings."""
    from lake_finder.enrich import load_records
    from lake_finder.listings import report_dict
    from lake_finder.report import write_records
    grid, dem, occ, labels, lakes, crit, vc = _world()
    shore = {"name": "shore", "lat": float(grid.lat_of_row(240)), "lon": float(grid.lon_of_col(206))}
    write_all(lakes, tmp_path, listings=[report_dict(evaluate_listing(shore, dem, occ, labels, grid, lakes, crit, vc))])
    for _ in range(2):
        recs = load_records(tmp_path)
        assert recs[0]["rank"] == 1 and isinstance(recs[0]["rank"], int)
        summary = write_records(recs, tmp_path)          # listings=None keeps the scored listings
        assert summary["listings"] == 1
    assert "#1 " in (tmp_path / "listings_scored.json").read_text()
