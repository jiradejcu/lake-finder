import json

from lake_finder.report import load_leads, render_map, write_records

LEAD = {"id": "fb-x", "title": "Plot </script> on a dam", "summary": "s", "where": "w", "price_thb": None,
        "area": "2 rai", "title_deed": None, "waterfront": "reservoir", "group": "1", "search": "ติดน้ำ",
        "lat": 14.5, "lon": 101.2, "loc_quality": "approx", "radius_m": 2500, "loc_basis": "dam", "thumb": None,
        "warning": "check NP"}


def _data(html):
    return json.loads(html.split("const DATA=", 1)[1].split(";\n", 1)[0])


def test_render_map_embeds_leads_safely():
    html = render_map([], (13.75, 100.5), "Bangkok", [], [LEAD])
    assert "Facebook leads" in html and "fbmark" in html
    assert "</script> on" not in html                       # escaped inside the inline JSON
    assert _data(html)["leads"][0]["radius_m"] == 2500


def test_write_records_reads_leads_file_by_default(tmp_path, monkeypatch):
    f = tmp_path / "leads.json"
    f.write_text(json.dumps([LEAD]), encoding="utf-8")
    monkeypatch.setattr("lake_finder.report.LEADS_FILE", f)
    assert write_records([], tmp_path / "out")["leads"] == 1          # leads=None reads LEADS_FILE
    assert "fb-x" in (tmp_path / "out" / "map.html").read_text(encoding="utf-8")
    assert write_records([], tmp_path / "out2", leads=[])["leads"] == 0
