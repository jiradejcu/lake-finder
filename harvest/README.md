# Listing harvest

Portals block plain HTTP, so listings are read through the owner's logged-in Chrome (Claude in Chrome, read-only: no
posting, commenting or messaging sellers). Raw rows go in `raw/*.json`; `python -m lake_finder.harvest build` turns them
into `all.json`, `to_verify.csv` and new entries in `../listings.json` (source `harvest`; hand-added listings are never touched).
Then run `python -m lake_finder --out <scratch>` and write the scored listings into `results/` (HANDOFF.md §2 recipe).

## DDproperty recipe (works, 2026-11-08)
- District search URL (the free-text `q=` parameter is ignored; typing in the box and picking a suggestion changes the page
  client-side but leaves stale `__NEXT_DATA__`, so always load the URL directly):
  `https://www.ddproperty.com/en/property-for-sale?page=N&propertyTypeGroup=L&propertyTypeCode=LAND&isCommercial=false&listingType=sale&districtCode=TH<prov><dist>`
  Verified codes: Tha Muang TH7106, Thong Pha Phum TH7107, Muang Nakhon Nayok TH2601, Pak Thong Chai TH3014, Makham TH2205.
- 20 cards per page; `__NEXT_DATA__ → props.pageProps.pageData.data.listingsData[i].listingData` has id, price, area,
  tenure, tambon. Each detail page (`/en/property/x-for-sale-<id>` redirects to the canonical URL) has
  `listingLocationData` (lat/lon), `descriptionBlockData` (Thai text).
- Run it as an in-page async job (`fetch` with credentials, 1.2 s between detail pages) and poll a `window` variable.
- **Pins:** many ads carry the portal's subdistrict centroid (e.g. 13.86677, 99.59188 shared by six Tha Muang ads). Identical
  coordinates on 2+ ads = `loc_quality: shared`, not trusted for the view verdict.
- Tool output from the page is capped at about 1 KB, and posting to `http://localhost` from the page hangs behind Chrome's
  local-network permission prompt (don't allow it). Filter inside the page and return compact CSV rows instead.

## Facebook (read-only, low yield)
Logged-in search at `facebook.com/search/posts?q=…` works, but results are virtualised teasers with no coordinates or
permalinks, and some text is obfuscated spam. Useful only for finding groups to read by hand:
- ซื้อขายที่ดินติดน้ำ ที่ดินวิวเขาสวย ทั่วไทย
- ซื้อขายที่ดิน กาญจนบุรี ท่าม่วง ท่ามะกา / ซื้อขายที่ดินจังหวัดกาญจนบุรี
- ขายที่ดินนครนายก ราคาถูก วิวเขา ติดน้ำ ติดถนน ราคาเจ้าของ (posts at ต.เขาพระ, Mueang Nakhon Nayok)
- Teasers seen: "ที่ดินวิวเขา ติดน้ำคลองมะนาว ทำเลเขาพระ นครนายก"; "ขายที่ดินติดแม่น้ำแควกาญจนบุรี"; "วิวเขา 180°" (Kanchanaburi).
None has a pin yet: open them by hand, then add with a lat/lon to `listings.json`.
