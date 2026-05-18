# Commercial EV Charger Installers UK — an auto-updating directory

A near-passive income asset: the only browsable, filterable directory of
**OZEV-authorised commercial & fleet EV charger installers** in the UK. Built
from public GOV.UK data (Open Government Licence v3.0). Monetised by disclosed
hardware/charging affiliate links + optional paid featured listings.

**Why it can work:** OZEV publishes no public installer list — only a
nearest-10-by-postcode tool. This aggregates it into the artifact that doesn't
exist, wraps it in grant/buyer SEO content, and keeps itself fresh automatically.
**Why it isn't a guarantee:** revenue is inbound/SEO — months to ramp, zero
up-front spend, compounding if it lands. Honest staged gates in `MONETIZATION.md`.

## How it works

```
pipeline/extract.py    scrape public OZEV tool over a UK postcode grid -> data/installers.json (+ .csv)
pipeline/validate.py   accuracy/dedup/"never guess" gate (blocks publish on failure)
site/generate.py       data + LeftClick-style templates -> site/dist/ (1000+ static pages)
.github/workflows/      weekly cron: extract -> validate -> generate -> commit (host auto-deploys)
```

No backend, no database, no server. ~£0 to run.

## Run locally

```
pip install -r requirements.txt
python pipeline/extract.py        # ~5 min, polite scrape (2s gap, 429 backoff)
python pipeline/validate.py
python site/generate.py
python -m http.server -d site/dist 8771   # preview at http://127.0.0.1:8771
```

## Going live & money

- **Deploy:** `deploy.md` — one credential-gated step, then self-updating forever.
- **Monetise:** `MONETIZATION.md` — exact affiliate-application pack + featured-
  listing setup. These need *your* identity/bank — they can't be automated.
- **Data provenance:** `pipeline/sources.md`.

## What's autonomous vs. what needs you

| Autonomous (done / scheduled) | Needs you (credential-bound, one-time) |
|---|---|
| Scrape, validate, rebuild, weekly refresh, diff report | Connect a host once (`deploy.md`) |
| 1000+ SEO pages, sitemap, structured data | Apply to affiliate programs (`MONETIZATION.md`) |
| Coverage widens each refresh | Stripe link for featured listings (optional) |
|  | Submit sitemap to Google Search Console |
