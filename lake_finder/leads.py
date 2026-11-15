"""Redraw the map after editing the Facebook leads, without re-running the pipeline.

    python -m lake_finder.leads [--results results] [--leads facebook/leads.json]

Reads the lakes, house sites and scored listings already in ``results/`` and the leads file, and rewrites
the outputs (the map picks up the leads; the other files come out the same).
"""
from __future__ import annotations

import argparse

from . import enrich, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default="results")
    ap.add_argument("--leads", default=None, help="default: facebook/leads.json")
    a = ap.parse_args(argv)
    leads = report.load_leads(a.leads)
    for l in leads:
        missing = [k for k in ("id", "title", "lat", "lon") if l.get(k) in (None, "")]
        if missing:
            raise SystemExit(f"Lead {l.get('id', '?')} is missing {', '.join(missing)}")
    print(report.write_records(enrich.load_records(a.results), a.results, leads=leads))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
