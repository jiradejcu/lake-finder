import csv
import json

from lake_finder import harvest as h


def test_parse_area_rai():
    assert h.parse_area_rai("4,800 sqm (land)") == 3.0
    assert h.parse_area_rai(None, "เนื้อที่ 1 ไร่ 2 งาน 32 ตารางวา") == 1.58
    assert h.parse_area_rai("", "") is None


def test_keywords_and_warnings():
    t = "ที่ดินติดอ่างเก็บน้ำ วิวภูเขา น.ส.3ก ส.ป.ก"
    assert set(h.flag_keywords(t)) == {"waterfront", "lake", "mountain"}
    assert len(h.title_warnings(t)) == 2
    kw, warn = h.decode_flags("wm|SN")
    assert set(kw) == {"waterfront", "mountain"} and len(warn) == 2


def _row(i, lat, lon, price=1_000_000, area="1,600 sqm (land)", tambon="X"):
    return {"src": "ddproperty", "id": str(i), "prov": "P", "dist": "D", "tambon": tambon,
            "price": price, "area": area, "lat": lat, "lon": lon}


def test_shared_coordinates_are_not_pins():
    recs = [h.normalise(_row(1, 13.1, 99.1)), h.normalise(_row(2, 13.1, 99.1, price=2)),
            h.normalise(_row(3, 13.2, 99.2, price=3)), h.normalise(_row(4, None, None, price=4))]
    h.grade_pins(recs)
    assert [r["loc_quality"] for r in recs] == ["shared", "shared", "pin", "none"]


def test_dedupe_merges_same_plot_across_portals():
    a = h.normalise(_row(1, 13.1, 99.1))
    b = h.normalise({**_row(2, 13.1, 99.1), "src": "livinginsider", "url": "http://b"})
    out = h.dedupe([a, b])
    assert len(out) == 1 and out[0]["other_urls"] == ["http://b"]


def test_build_keeps_manual_listings_and_zone_filter(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "res").mkdir()
    with open(tmp_path / "res" / "house_sites.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lake_rank", "lake_name", "lat", "lon", "score", "protected_area"])
        w.writerow([1, "Lake A", 14.0, 99.5, 80, ""])
    rows = [_row(1, 14.01, 99.5), _row(2, 15.5, 99.5, price=2), {**_row(3, None, None, price=3)}]
    (tmp_path / "raw" / "a.json").write_text(json.dumps(rows), encoding="utf-8")
    lp = tmp_path / "listings.json"
    lp.write_text(json.dumps([{"name": "manual", "lat": 1, "lon": 1}]), encoding="utf-8")
    s = h.build(tmp_path / "raw", tmp_path / "res", tmp_path / "out", lp, radius_km=8, top_lakes=5)
    assert s["pins_scored"] == 1 and s["to_verify"] == 1
    names = [x["name"] for x in json.loads(lp.read_text(encoding="utf-8"))]
    assert names[0] == "manual" and len(names) == 2
    h.build(tmp_path / "raw", tmp_path / "res", tmp_path / "out", lp, radius_km=8, top_lakes=5)
    assert len(json.loads(lp.read_text(encoding="utf-8"))) == 2  # rebuild is idempotent


def test_shoreline_split_and_filter():
    sc = [{"water_dist_m": 100, "water_type": "lake / reservoir (~2 km²)", "fit_score": 50},
          {"water_dist_m": 50, "water_type": "river, canal or small pond", "fit_score": 40},
          {"water_dist_m": 900, "water_type": "lake / reservoir (~2 km²)", "fit_score": 90},
          {"water_dist_m": None, "water_type": None, "fit_score": 1}]
    g = h.shoreline(sc, 300)
    assert len(g["lake"]) == 1 and len(g["river"]) == 1


def test_claims_report(tmp_path):
    (tmp_path / "all.json").write_text(json.dumps([
        {"id": "1", "keywords": {"waterfront": []}, "price_thb": 1, "loc_quality": "pin"},
        {"id": "2", "keywords": {}, "price_thb": 2}]), encoding="utf-8")
    scored = [{"name": "x (DDP 1)", "water_dist_m": 50, "water_type": "river", "fit_score": 1, "lat": 1, "lon": 2},
              {"name": "y (DDP 2)", "water_dist_m": 10, "water_type": "river", "fit_score": 1, "lat": 1, "lon": 2}]
    assert h.claims_report(tmp_path / "all.json", scored, tmp_path / "c.csv") == 1
