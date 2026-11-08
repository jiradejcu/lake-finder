# CLAUDE.md

Project: find lakeside land near Bangkok where a house would look **across the water at a mountain**.
Read `HANDOFF.md` first. It has the goal, current results, the listing analysed, environment/network facts
and next steps. `README.md` covers usage.

- Default branch: `master`.
- Setup: `pip install -r requirements.txt pytest`. Tests: `python -m pytest` (offline, synthetic terrain).
- Preview the map: `python -m lake_finder.serve` → http://localhost:8765/map.html (no cache, live reload).
  Use it instead of `python -m http.server`, which lets Chrome show stale copies. On Windows start it
  windowless: `Start-Process pythonw -ArgumentList '-m','lake_finder.serve'` (no console pop-up).
- Full run: `python -m lake_finder` (first run downloads ~100 MB into `cache/`, which is gitignored).
- `results/` is a committed snapshot **with OSM access data**. Don't overwrite it with a plain
  `python -m lake_finder --out results` unless you re‑run `python -m lake_finder.enrich` afterwards
  (see HANDOFF.md §2).
- Overpass (OSM) is unreachable from the cloud sandbox; names/access lookups must run locally or via a mirror.
- Listings live in `listings.json`; only tb.co.th pages can be parsed automatically.
- When sharing results with the owner, give coordinates with Google Maps links, and say clearly
  when land may be protected (national park, forest reserve, ส.ป.ก.).

## Owner's working preferences (apply in every session, local or cloud)

- **Commit and push to `master` at every important milestone** (a finished, verified feature or fix)
  without asking first. Keep unrelated milestones in separate commits. Don't commit unverified work.
- **Test UI changes in the browser yourself** (Claude in Chrome) with real clicks, then report what you
  checked. Reload the page before trusting what it shows, and check that the data you expect is there
  (e.g. `DATA.listings.length`). A stale page hid the for-sale pin once.
- **No visible console windows.** On Windows, run long-lived processes (the preview server) with
  `pythonw` via `Start-Process`. In WSL/Linux, a background job is fine.
- **One preview server only.** Before starting `lake_finder.serve`, stop any other server on port 8765
  (an old `python -m http.server 8765` kept reappearing on Windows and served an outdated map).
  Stop your own server when the session's work is done, unless the owner is still using the map.
