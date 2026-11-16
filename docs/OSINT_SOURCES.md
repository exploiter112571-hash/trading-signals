# OSINT sources: what was adopted, and what could be next

This pipeline originally got its flight and conflict-news numbers only through
Osiris, a third-party app run locally (see KNOWN_RISKS #2). This page records
what was taken from two open-source OSINT projects to reduce that dependence,
and which further sources are worth adding.

## From God's Eye View

[bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)
(MIT code; each data source keeps its own terms, see its `DATA_SOURCES.md`) is
a browser 3D globe of live satellites, flights, vessels, cameras and events.
### The app, running locally

God's Eye View runs as a local service next to Osiris:

- Installed at `~/gods-eye-view` (upstream clone, `npm ci`, no keys needed).
- Unit file: `deploy/systemd/gods-eye-view.service`. Install with
  `cp deploy/systemd/gods-eye-view.service ~/.config/systemd/user/ && systemctl --user enable --now gods-eye-view`.
- Open **http://localhost:4173** in a Windows browser (WSL forwards
  localhost) to see the Gulf live: flights, military traffic, GNSS
  integrity, news/conflicts, satellites. Use it to check by eye what a score
  spike is made of. It binds to localhost only (upstream default).
- Optional keys (AISStream for vessels, NASA FIRMS for fires, Cesium/Google
  for 3D) go in `~/gods-eye-view/.env` or the in-app POWER UP panel.
- Update: `cd ~/gods-eye-view && git pull && npm ci && systemctl --user restart gods-eye-view`.

The pipeline also reads from the running app:

| Table | Source | What it adds |
| --- | --- | --- |
| `gnss` | `localhost:4173/api/gnss-integrity` at four 250 NM anchors covering the Gulf box | Share of Gulf aircraft whose reported NIC/NACp falls below the ADS-B Out minima (God's Eye View's gpsjam-style rule; not validated against known events). A proxy for GPS jamming/spoofing, which tends to rise with military activity. |

`gnss` runs as a shadow component compared with its own 7-day average, not
gpsjam's fixed 2%/10% bands, because the Gulf has chronic GPS interference.
If the app is down the poller skips the row; nothing else is affected.

Note: the app and the poller both call adsb.lol from this IP. With the app
open in a browser for long stretches, adsb.lol may answer the poller with
HTTP 429 now and then; those polls just skip `mil_jets`.

### Feeds re-implemented in the poller

Two of its data feeds were also adopted directly into `poller.py`,
re-implemented in Python (no code copied), so they don't depend on the app
running:

| Table | Source | What it fixes |
| --- | --- | --- |
| `gdelt_v2` | GDELT 2.0 15-minute event exports, `data.gdeltproject.org/gdeltv2/` (keyless; [GDELT terms](https://www.gdeltproject.org/about.html#termsofuse)) | The Osiris "GDELT" is an RSS headline geo-mapper with no timestamps (KNOWN_RISKS #2). These are real CAMEO-coded events with exact 15-minute timestamps. Old exports stay online, so `poller.py --backfill-gdelt 7` builds the 7-day baseline at once. |
| `mil_jets` | adsb.lol `/v2/mil` (keyless; ODbL 1.0) | The Osiris jets count is mostly airliners (KNOWN_RISKS #3). This counts aircraft that adsb.lol flags as military, in the same Gulf box. |

How Gulf events are picked from GDELT: an event counts when its action
location is inside the Gulf box (lat 22-30, lon 48-58) **or** its action
country is Iran, Bahrain, Qatar, UAE, Oman or Kuwait. The country match
matters because GDELT places country-level stories at the country centroid;
Iran's is about 32N, outside the box, which is the same flaw that zeroed the
Osiris gdelt component for weeks. Per export the poller stores all Gulf
events, QuadClass 4 "material conflict" events (CAMEO roots 14-20: protest,
force posture, reduce relations, coerce, assault, fight, mass violence), and
the narrower roots
18-20 that God's Eye View's Conflicts layer uses.

Both feeds run as **shadow components** in `scorer.py`: computed and stored
under `components.shadow` on every run but not added to the score.
`gdelt_v2` compares the last 6 h of material-conflict events with the 7-day
average 6 h total. `mil_jets` uses the same latest-vs-7-day-average rule as
`jets`. Once they have been compared against the Osiris-based components for
a while, switching over is a two-line change in `scorer.main()`.

Also in God's Eye View and worth adding later:

- **AISStream.io** live AIS vessels (free key): tanker traffic through
  Hormuz is probably a better shipping-risk signal than aircraft counts.
- **S2 Underground GhostMaps**: Iran and Yemen intel KMZ products.
- **USGS earthquakes**: separates a quake near Iranian nuclear sites from
  an explosion story.

## From awesome-osint

[jivoi/awesome-osint](https://github.com/jivoi/awesome-osint) is a curated
list of about 1,700 OSINT links, mostly web UIs for people investigations and
cyber threat intel; there is no code in it to run. Nothing from it is polled
yet. These are the entries in the list (checked 2026-11-16) that are relevant to a
Gulf/Hormuz risk score. Check each one's terms before polling it
automatically; most have no free API.

| Entry (section) | Possible use here |
| --- | --- |
| [Upsala Conflict Data Program](https://www.pcr.uu.se/research/UCDP) (Data and Statistics) | Researcher-coded conflict events with a free API (access token on request): the best available ground truth for checking the GDELT signal in `scripts/backtest.py`. |
| [VesselFinder](https://www.vesselfinder.com) (Maritime) | Manual check of tanker traffic in the Strait. Its API is paid; AISStream.io (above) is the free route to automated AIS counts. |
| [Phantom Tide](https://github.com/tg12/phantomtide) (Maritime) | Open-source vessel + airspace + notices dashboard; worth reading for how it combines maritime and airspace feeds. |
| [PortInsight.io](https://portinsight.io/ports) (Maritime) | Anchorage waiting times measured from AIS; useful only if it covers a Gulf port. |
| [World Monitor](https://www.worldmonitor.app) (Geospatial) | Military flights, vessels and GPS jamming on one site: a manual cross-check for the `mil_jets` reading. |
| [Liveuamap](https://liveuamap.com/) (Geospatial) | Human-curated conflict map; its paid API is also an optional source in God's Eye View. |
| [Pharos AI](https://conflicts.app) | Conflict-tracking dashboard; manual cross-check. |
| [Sentinel Hub](https://www.sentinel-hub.com/explore/sentinelplayground/) (Geospatial) | Satellite imagery to confirm a spike after the fact (e.g. smoke at a refinery). |
| [Overhead24](https://overhead24.com) (Geospatial) | Military satellites over conflict areas; context only. |

Suggested order: UCDP as backtest ground truth, then AISStream tanker counts
in the Strait (add the key to God's Eye View and read its `/api/vessels`).
