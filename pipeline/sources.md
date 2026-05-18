# Data Sources

This directory aggregates **publicly available** information about OZEV-authorised
commercial EV chargepoint installers in the UK. No private data, no scraping behind
logins, no cold outreach. The accuracy rule from `scrape-to-spreadsheet` applies:
**never guess or hallucinate — missing fields are `N/A`.**

## Primary source — GOV.UK OZEV authorised installer tool

- **URL:** https://www.gov.uk/electric-vehicle-chargepoint-installers
  (the page `https://www.gov.uk/government/publications/commercial-chargepoints-authorised-installers`
  now redirects here)
- **Operator:** Office for Zero Emission Vehicles (OZEV) / DfT, via GOV.UK.
- **Licence:** Open Government Licence v3.0 — content is explicitly free to reuse
  with attribution. Footer: *"All content is available under the Open Government
  Licence v3.0, except where otherwise stated."*
- **robots.txt (checked):** `/electric-vehicle-chargepoint-installers` is **not**
  disallowed. No general `Crawl-delay`. We self-impose ~1 request/sec and a
  descriptive User-Agent regardless.
- **Mechanism:** HTTP `POST` to the page URL with form fields:
  - `authenticity_token` — Rails CSRF token; must be read from a prior `GET` of
    the page (paired with the session cookie from that GET).
  - `postcode` — a UK postcode. Returns the **10 nearest** authorised installers.
- **Per-result fields available in the returned HTML:**
  `name` (h3), address lines, town, postcode, `lat`/`lon` (parsed from the
  embedded Google Maps `q=loc:LAT,LON` link), `website`, `email` (mailto),
  `phone`, and a service descriptor line — one of:
  *"Commercial and residential installations"*, *"Commercial installations only"*,
  *"Residential installations only"*.
- **Why this is the canonical source:** OZEV publishes no downloadable list and no
  browsable/filterable directory. The only access is this nearest-10-by-postcode
  tool. Aggregating it into a deduplicated, filterable directory is the entire
  value proposition — that artifact does not exist publicly.

## Coverage strategy

The tool only returns 10 results per postcode, so a single query is national-blind.
`extract.py` queries a UK-wide grid of anchor postcodes (every postcode area, denser
in urban areas) and deduplicates by normalised `(name, postcode)`. The scheduled
refresh widens the grid over time, so coverage monotonically improves.

## Filtering to the niche

Only records whose service descriptor contains **"Commercial"** are kept
(*"Commercial and residential…"* or *"Commercial installations only"*).
Residential-only installers are out of scope for a commercial/fleet directory.

## Enrichment (progressive, never fabricated)

Base records carry only what GOV.UK returns. Optional later enrichment from each
installer's **own public website** (services, accreditations, regions covered,
grant support) is added by the refresh job over time. Any field not found on a
public page stays `N/A`. Trading-status verification (optional) uses the public
**Companies House** register (open data).

## Explicitly out of scope

- EVCC (`electric-vehicle.org.uk`) — that register is for *home* chargepoints; not
  the commercial/fleet niche.
- Any paid lead database.
- Mass cold email / outreach using scraped contact data (the public contact email
  is displayed for buyer convenience and attribution only, exactly as GOV.UK shows it).

_Last reviewed: 2026-05-18._
