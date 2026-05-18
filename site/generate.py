"""
generate.py — Build the static directory site from data/installers.json.

Outputs to site/dist/:
  index.html                     filterable directory (server-rendered + JS filters)
  installers/<slug>/index.html   per-installer SEO page
  regions/<slug>/index.html      per-region SEO page
  guides/<topic>/index.html      grant/buyer SEO content (the traffic magnets)
  installers.js                  dataset for client-side filtering
  sitemap.xml, robots.txt, 404.html

No backend, no DB. Design follows the LeftClick style invariants (Inter font,
#0a0a0a dark / #f7fafc light, pill buttons). Affiliate slots are DISCLOSED and
left as clearly-marked placeholders — never fabricated (see MONETIZATION.md).
"""

from __future__ import annotations

import json
import os
import re
import sys
import datetime
import shutil
from pathlib import Path

# Windows consoles default to cp1252 and choke on — / → in status prints.
# Force UTF-8 so unattended/scheduled runs always exit cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DIST = ROOT / "site" / "dist"

SITE_NAME = "Commercial EV Charger Installers UK"
SITE_TAGLINE = "The independent directory of OZEV-authorised commercial & fleet EV charging installers"
# Live URL drives canonical tags + sitemap (critical for SEO — the whole point).
# Override per deploy target: set SITE_BASE_URL env var (no trailing slash).
BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://commercial-ev-installers.pages.dev"
).rstrip("/")
CONTACT_EMAIL = os.environ.get("SITE_CONTACT_EMAIL", "hello@example.com")
TODAY = datetime.date.today().isoformat()

REGIONS_ORDER = [
    "London", "South East", "South West", "East of England", "West Midlands",
    "East Midlands", "Yorkshire & Humber", "North West", "North East",
    "Scotland", "Wales", "Northern Ireland",
]


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "x"


def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# --- Shared CSS (LeftClick palette/typography, directory-specific layout) -----
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--dark:#0a0a0a;--card-d:#141414;--bd-d:#1f1f1f;--light:#f7fafc;
--card-l:#fff;--bd-l:#e8edf3;--green:#16a34a;--ink:#0a0a0a;--mut:#5b6470}
html{scroll-behavior:smooth}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
color:var(--ink);background:#fff;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1140px;margin:0 auto;padding:0 24px}
.btn{display:inline-flex;align-items:center;gap:10px;padding:13px 22px;
border-radius:9999px;font-weight:600;font-size:15px;text-decoration:none;
border:0;cursor:pointer;transition:transform .15s}
.btn:hover{transform:translateY(-2px)}
.btn-g{background:var(--green);color:#fff}
.btn-d{background:#fff;color:var(--dark)}
.btn-o{background:transparent;color:#fff;border:1px solid #2a2a2a}
.arrow{width:24px;height:24px;border-radius:9999px;background:rgba(255,255,255,.18);
display:inline-flex;align-items:center;justify-content:center;font-size:13px}
.btn-g .arrow,.btn-d .arrow{background:rgba(0,0,0,.12)}
header.nav{position:sticky;top:0;z-index:50;background:rgba(10,10,10,.92);
backdrop-filter:blur(8px);border-bottom:1px solid var(--bd-d)}
.nav .wrap{display:flex;align-items:center;justify-content:space-between;height:64px}
.brand{color:#fff;font-weight:800;letter-spacing:-.5px;text-decoration:none;font-size:17px}
.brand span{color:var(--green)}
.nav nav{display:flex;gap:26px;align-items:center}
.nav nav a{color:#cfd3d8;text-decoration:none;font-size:14px;font-weight:500}
.nav nav a:hover{color:#fff}
.hero{background:var(--dark);color:#fff;padding:84px 0 72px}
.hero h1{font-size:52px;font-weight:800;line-height:1.04;letter-spacing:-2px;max-width:780px}
.hero p.sub{color:#aab0b8;font-size:19px;margin:22px 0 32px;max-width:620px}
.pill{display:inline-flex;gap:8px;align-items:center;background:rgba(22,163,74,.14);
color:#4ade80;border:1px solid rgba(22,163,74,.3);padding:7px 15px;border-radius:9999px;
font-size:13px;font-weight:600;margin-bottom:26px}
.stats{display:flex;gap:38px;margin-top:46px;flex-wrap:wrap}
.stat b{display:block;font-size:30px;font-weight:800;letter-spacing:-1px}
.stat span{color:#8b929b;font-size:13px}
section{padding:64px 0}
.sec-l{background:var(--light)}
h2.sh{font-size:38px;font-weight:800;letter-spacing:-1px;margin-bottom:10px}
.lead{color:var(--mut);font-size:17px;max-width:640px;margin-bottom:34px}
.filters{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:26px;
background:var(--card-l);border:1px solid var(--bd-l);border-radius:16px;padding:18px}
.filters input,.filters select{font-family:inherit;font-size:14px;padding:11px 14px;
border:1px solid var(--bd-l);border-radius:10px;background:#fff;color:var(--ink);min-width:170px}
.filters input{flex:1;min-width:220px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:18px}
.card{background:var(--card-l);border:1px solid var(--bd-l);border-radius:16px;
padding:22px;transition:transform .15s,box-shadow .15s;display:flex;flex-direction:column}
.card:hover{transform:translateY(-3px);box-shadow:0 12px 30px rgba(10,20,40,.08)}
.card.feat{border-color:var(--green);box-shadow:0 0 0 1px var(--green) inset}
.card .ftag{align-self:flex-start;background:var(--green);color:#fff;font-size:11px;
font-weight:700;padding:3px 10px;border-radius:9999px;margin-bottom:10px;letter-spacing:.4px}
.card h3{font-size:18px;font-weight:700;letter-spacing:-.4px;margin-bottom:6px}
.card h3 a{text-decoration:none}
.card .meta{color:var(--mut);font-size:13.5px;margin-bottom:14px}
.tags{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:16px}
.tag{font-size:11.5px;font-weight:600;padding:4px 10px;border-radius:9999px;
background:#eef2f7;color:#3a4452}
.tag.c{background:rgba(22,163,74,.12);color:#15803d}
.card .links{margin-top:auto;display:flex;gap:14px;font-size:13px;font-weight:600}
.card .links a{color:var(--green);text-decoration:none}
.muted{color:var(--mut)}
.note{font-size:12.5px;color:#8a93a0;margin-top:8px}
.guidegrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
.gcard{display:block;background:var(--card-d);border:1px solid var(--bd-d);
border-radius:16px;padding:24px;text-decoration:none;color:#fff;transition:transform .15s}
.gcard:hover{transform:translateY(-3px)}
.gcard h3{font-size:18px;font-weight:700;margin-bottom:8px}
.gcard p{color:#9aa1ab;font-size:14px}
.sec-d{background:var(--dark);color:#fff}
.sec-d h2.sh{color:#fff}
.sec-d .lead{color:#9aa1ab}
.prose{max-width:760px}
.prose h1{font-size:42px;font-weight:800;letter-spacing:-1.5px;margin-bottom:8px}
.prose .upd{color:var(--mut);font-size:13px;margin-bottom:30px}
.prose h2{font-size:25px;font-weight:800;letter-spacing:-.6px;margin:34px 0 12px}
.prose p{margin-bottom:15px;font-size:16.5px}
.prose ul{margin:0 0 16px 22px}.prose li{margin-bottom:8px}
.prose .box{background:var(--light);border:1px solid var(--bd-l);border-radius:14px;
padding:20px 22px;margin:22px 0}
.disc{background:#fff8e6;border:1px solid #f0d98a;color:#7a5c00;font-size:13px;
padding:12px 16px;border-radius:10px;margin:18px 0}
.aff{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:18px}
.aff a,.aff span{display:block;background:var(--card-d);border:1px dashed #3a3a3a;
border-radius:14px;padding:20px;color:#cfd3d8;text-decoration:none;font-size:14px}
footer{background:var(--dark);color:#8b929b;padding:54px 0;border-top:1px solid var(--bd-d)}
footer .wrap{display:flex;justify-content:space-between;gap:30px;flex-wrap:wrap}
footer a{color:#cfd3d8;text-decoration:none;font-size:14px;display:block;margin-bottom:9px}
footer h4{color:#fff;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-bottom:14px}
.crumb{font-size:13px;color:var(--mut);padding:18px 0}
.crumb a{color:var(--green);text-decoration:none}
@media(max-width:680px){.hero h1{font-size:36px}h2.sh{font-size:28px}
.nav nav{display:none}.prose h1{font-size:32px}}
"""

FAVICON = (
    '<link rel="icon" href="data:image/svg+xml,'
    "%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'%3E"
    "%3Crect%20width='32'%20height='32'%20rx='7'%20fill='%230a0a0a'/%3E"
    "%3Ctext%20x='16'%20y='22'%20font-family='Arial'%20font-size='17'%20"
    "font-weight='bold'%20fill='%2316a34a'%20text-anchor='middle'%3EEV%3C/text%3E"
    "%3C/svg%3E\">"
)

FONT = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">')


def head(title: str, desc: str, canonical: str, jsonld: str = "") -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website"><meta name="robots" content="index,follow">
{FAVICON}{FONT}<style>{CSS}</style>{jsonld}</head><body>"""


def navbar() -> str:
    return f"""<header class="nav"><div class="wrap">
<a class="brand" href="/">Commercial<span>EV</span>Installers</a>
<nav><a href="/#directory">Directory</a><a href="/guides/ev-charging-for-fleets/">Fleet guide</a>
<a href="/guides/workplace-charging-scheme/">WCS grant</a>
<a href="/guides/ev-infrastructure-grant/">Infrastructure grant</a></nav></div></header>"""


def footer() -> str:
    reg = "".join(
        f'<a href="/regions/{slugify(r)}/">{esc(r)}</a>' for r in REGIONS_ORDER[:8]
    )
    return f"""<footer><div class="wrap">
<div><h4>{esc(SITE_NAME)}</h4>
<p style="max-width:320px;font-size:13px">Independent directory built from the public
OZEV authorised-installer data (Open Government Licence v3.0). Not affiliated with OZEV
or any installer.</p></div>
<div><h4>Guides</h4><a href="/guides/ev-charging-for-fleets/">EV charging for fleets</a>
<a href="/guides/workplace-charging-scheme/">Workplace Charging Scheme</a>
<a href="/guides/ev-infrastructure-grant/">EV Infrastructure Grant</a>
<a href="/guides/grant-deadlines/">Grant deadlines</a></div>
<div><h4>Regions</h4>{reg}</div></div>
<div class="wrap" style="margin-top:34px;font-size:12.5px;border-top:1px solid #1f1f1f;padding-top:22px">
Data source: <a href="https://www.gov.uk/electric-vehicle-chargepoint-installers" style="display:inline">GOV.UK / OZEV</a>,
under the Open Government Licence v3.0. Last updated {TODAY}. &copy; {datetime.date.today().year}.
Some outbound links may be partner/affiliate links — these never affect listing order.</div></footer>"""


def card(inst: dict) -> str:
    sl = slugify(inst["name"]) + "-" + slugify(inst["postcode"])
    tags = "".join(
        f'<span class="tag c">{esc(s)}</span>' if s == "Commercial"
        else f'<span class="tag">{esc(s)}</span>'
        for s in inst["services"]
    )
    tags += '<span class="tag">OZEV authorised</span>'
    feat = "feat" if inst.get("featured") else ""
    ftag = '<span class="ftag">FEATURED</span>' if inst.get("featured") else ""
    loc = " · ".join(p for p in [inst.get("town"), inst.get("region")] if p and p != "N/A")
    web = ""
    if inst.get("website") and inst["website"] != "N/A":
        web = f'<a href="{esc(inst["website"])}" target="_blank" rel="nofollow noopener">Visit website →</a>'
    return f"""<article class="card {feat}" data-name="{esc(inst['name'].lower())}"
data-region="{esc(inst.get('region',''))}" data-services="{esc(','.join(inst['services']))}"
data-town="{esc((inst.get('town') or '').lower())}">
{ftag}<h3><a href="/installers/{sl}/">{esc(inst['name'])}</a></h3>
<div class="meta">{esc(loc) or 'United Kingdom'}</div>
<div class="tags">{tags}</div>
<div class="links"><a href="/installers/{sl}/">View details</a>{web}</div></article>"""


def page_index(installers: list[dict]) -> str:
    n = len(installers)
    regions = sorted({i["region"] for i in installers if i["region"] != "N/A"})
    feat = [i for i in installers if i.get("featured")]
    ordered = feat + [i for i in installers if not i.get("featured")]
    cards = "".join(card(i) for i in ordered)
    ropts = "".join(f'<option value="{esc(r)}">{esc(r)}</option>' for r in regions)
    jsonld = (
        '<script type="application/ld+json">'
        + json.dumps({
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": BASE_URL,
            "description": SITE_TAGLINE,
        })
        + "</script>"
    )
    return (
        head(
            f"{SITE_NAME} — OZEV-Authorised Directory",
            f"Find OZEV-authorised commercial & fleet EV charging point installers across the UK. {n} verified installers, filterable by region and service. Free, independent directory.",
            BASE_URL + "/",
            jsonld,
        )
        + navbar()
        + f"""<section class="hero"><div class="wrap">
<span class="pill">● {n} OZEV-authorised commercial installers</span>
<h1>Find a commercial EV charging installer that can actually do the job.</h1>
<p class="sub">{esc(SITE_TAGLINE)}. Every installer here is authorised by the Office
for Zero Emission Vehicles for commercial or fleet work — filterable the way the
official tool isn't.</p>
<a class="btn btn-g" href="#directory">Browse the directory <span class="arrow">→</span></a>
<a class="btn btn-o" href="/guides/ev-charging-for-fleets/" style="margin-left:12px">Fleet buyer's guide</a>
<div class="stats">
<div class="stat"><b>{n}</b><span>commercial installers</span></div>
<div class="stat"><b>{len(regions)}</b><span>UK regions covered</span></div>
<div class="stat"><b>£500</b><span>WCS grant / socket from Apr 2026</span></div>
<div class="stat"><b>OGL&nbsp;v3.0</b><span>official OZEV data</span></div></div>
</div></section>

<section id="directory"><div class="wrap">
<h2 class="sh">The directory</h2>
<p class="lead">Search and filter {n} OZEV-authorised installers that offer commercial
or fleet installations. Listing order is alphabetical (featured partners first) and is
never influenced by outbound links.</p>
<div class="filters">
<input id="q" type="search" placeholder="Search by installer name or town…" aria-label="Search">
<select id="fr" aria-label="Filter by region"><option value="">All regions</option>{ropts}</select>
<select id="fs" aria-label="Filter by service"><option value="">All services</option>
<option value="Commercial">Commercial</option><option value="Residential">Also residential</option></select>
</div>
<p id="count" class="note"></p>
<div id="grid" class="grid">{cards}</div>
<p id="empty" class="muted" style="display:none;padding:30px 0">No installers match
those filters. Try widening your search.</p>
</div></section>

<section class="sec-d"><div class="wrap">
<h2 class="sh">Grants &amp; buyer guides</h2>
<p class="lead">The money side, explained plainly — what's available, who qualifies,
and the deadlines that matter.</p>
<div class="guidegrid">
<a class="gcard" href="/guides/ev-charging-for-fleets/"><h3>EV charging for fleets</h3>
<p>How depot, workplace and fleet charging actually gets specified and costed.</p></a>
<a class="gcard" href="/guides/workplace-charging-scheme/"><h3>Workplace Charging Scheme</h3>
<p>The WCS voucher — eligibility, the £500/socket cap from April 2026, how to claim.</p></a>
<a class="gcard" href="/guides/ev-infrastructure-grant/"><h3>EV Infrastructure Grant</h3>
<p>Grant for staff &amp; fleet car parks — what it covers and how installers apply it.</p></a>
<a class="gcard" href="/guides/grant-deadlines/"><h3>Grant deadlines</h3>
<p>Every live EV charging grant deadline on one page, kept current.</p></a>
</div></div></section>"""
        + footer()
        + """<script src="/installers.js"></script><script>
(function(){var q=document.getElementById('q'),fr=document.getElementById('fr'),
fs=document.getElementById('fs'),g=document.getElementById('grid'),
em=document.getElementById('empty'),ct=document.getElementById('count'),
cards=[].slice.call(g.children);
function run(){var t=(q.value||'').toLowerCase().trim(),r=fr.value,s=fs.value,v=0;
cards.forEach(function(c){var ok=(!t||c.dataset.name.indexOf(t)>-1||c.dataset.town.indexOf(t)>-1)
&&(!r||c.dataset.region===r)&&(!s||c.dataset.services.indexOf(s)>-1);
c.style.display=ok?'':'none';if(ok)v++;});
em.style.display=v?'none':'';ct.textContent=v+' installer'+(v===1?'':'s')+' shown';}
q.addEventListener('input',run);fr.addEventListener('change',run);
fs.addEventListener('change',run);run();})();
</script></body></html>"""
    )


def page_installer(inst: dict, all_inst: list[dict]) -> str:
    sl = slugify(inst["name"]) + "-" + slugify(inst["postcode"])
    url = f"{BASE_URL}/installers/{sl}/"
    addr = ", ".join(
        p for p in [inst.get("street"), inst.get("town"), inst.get("postcode")]
        if p and p != "N/A"
    )
    nearby = [
        i for i in all_inst
        if i["region"] == inst["region"] and i["name"] != inst["name"]
    ][:6]
    jl = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": inst["name"],
        "description": f"OZEV-authorised commercial EV chargepoint installer. {inst.get('service_text','')}",
        "areaServed": inst.get("region", "United Kingdom"),
    }
    if addr:
        jl["address"] = {"@type": "PostalAddress", "addressCountry": "GB",
                         "addressLocality": inst.get("town", ""),
                         "postalCode": inst.get("postcode", ""),
                         "streetAddress": inst.get("street", "")}
    if inst.get("lat") not in (None, "N/A"):
        jl["geo"] = {"@type": "GeoCoordinates", "latitude": inst["lat"],
                     "longitude": inst["lon"]}
    if inst.get("website") and inst["website"] != "N/A":
        jl["url"] = inst["website"]
    if inst.get("phone") and inst["phone"] != "N/A":
        jl["telephone"] = inst["phone"]
    jsonld = '<script type="application/ld+json">' + json.dumps(jl) + "</script>"

    def row(label, val, link=None):
        if not val or val == "N/A":
            val = '<span class="muted">Not listed</span>'
        elif link:
            val = f'<a href="{esc(link)}" {"target=_blank rel=\"nofollow noopener\"" if link.startswith("http") else ""} style="color:var(--green)">{esc(val)}</a>'
        else:
            val = esc(val)
        return f'<p><strong>{label}:</strong> {val}</p>'

    maps = ""
    if inst.get("lat") not in (None, "N/A"):
        maps = (f'<p><a style="color:var(--green)" target="_blank" rel="noopener" '
                f'href="https://maps.google.com/maps?q=loc:{inst["lat"]},{inst["lon"]}">'
                f'View on Google Maps →</a></p>')
    near = "".join(card(i) for i in nearby)
    return (
        head(
            f"{inst['name']} — OZEV Commercial EV Charger Installer ({inst.get('region','UK')})",
            f"{inst['name']} is an OZEV-authorised commercial EV chargepoint installer "
            f"in {inst.get('town','the UK')}. Contact details, service area and grant context.",
            url, jsonld,
        )
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> ›
<a href="/regions/{slugify(inst.get('region','uk'))}/">{esc(inst.get('region','UK'))}</a> › {esc(inst['name'])}</div>
<section style="padding-top:8px"><div class="wrap prose">
<h1>{esc(inst['name'])}</h1>
<p class="upd">OZEV-authorised commercial EV chargepoint installer · data verified {esc(inst.get('last_verified',TODAY))}</p>
<div class="box">
{row('Services', inst.get('service_text'))}
{row('Service region', inst.get('region'))}
{row('Address', addr)}
{row('Website', None if inst.get('website')=='N/A' else inst.get('website'), inst.get('website'))}
{row('Phone', inst.get('phone'), 'tel:'+inst['phone'] if inst.get('phone') not in (None,'N/A') else None)}
{row('Email', inst.get('email'), 'mailto:'+inst['email'] if inst.get('email') not in (None,'N/A') else None)}
{row('Accreditation', ', '.join(inst.get('accreditations',[])))}
{maps}</div>
<p class="muted" style="font-size:13.5px">Listing compiled from the public GOV.UK OZEV
authorised-installer tool (Open Government Licence v3.0). Details change — confirm directly
with the installer before contracting. <a style="color:var(--green)" href="/contact/">Request a correction or removal</a>.</p>
<h2>Could this install be grant-funded?</h2>
<p>Commercial and fleet EV charging installs are frequently part-funded. See the
<a style="color:var(--green)" href="/guides/workplace-charging-scheme/">Workplace Charging Scheme</a>
(up to £500/socket from April 2026) and the
<a style="color:var(--green)" href="/guides/ev-infrastructure-grant/">EV Infrastructure Grant</a>
for staff &amp; fleet car parks before you commission work.</p>
</div></section>
<section class="sec-l"><div class="wrap"><h2 class="sh">Other installers in {esc(inst.get('region','the UK'))}</h2>
<div class="grid">{near or '<p class=muted>No other installers indexed in this region yet.</p>'}</div></div></section>"""
        + footer() + "</body></html>"
    )


def page_region(region: str, installers: list[dict]) -> str:
    items = sorted(
        [i for i in installers if i["region"] == region],
        key=lambda x: x["name"].lower(),
    )
    url = f"{BASE_URL}/regions/{slugify(region)}/"
    cards = "".join(card(i) for i in items)
    jl = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"Commercial EV charger installers in {region}",
        "numberOfItems": len(items),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": n + 1,
                "url": f"{BASE_URL}/installers/"
                f"{slugify(i['name'])}-{slugify(i['postcode'])}/",
                "name": i["name"],
            }
            for n, i in enumerate(items[:100])
        ],
    }
    jsonld = '<script type="application/ld+json">' + json.dumps(jl) + "</script>"
    return (
        head(
            f"Commercial EV Charger Installers in {region} — OZEV Authorised",
            f"{len(items)} OZEV-authorised commercial and fleet EV charging installers "
            f"in {region}. Independent, filterable directory.",
            url, jsonld,
        )
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> › {esc(region)}</div>
<section style="padding-top:8px"><div class="wrap">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">Commercial EV charger installers in {esc(region)}</h1>
<p class="lead" style="margin-top:14px">{len(items)} OZEV-authorised installers offering
commercial or fleet EV charging installation in {esc(region)}.</p>
<div class="grid">{cards or '<p class=muted>None indexed yet — coverage widens each refresh.</p>'}</div>
</div></section>""" + footer() + "</body></html>"
    )


GUIDES = {
    "ev-charging-for-fleets": {
        "title": "EV Charging for Fleets: The 2026 Buyer's Guide",
        "desc": "How UK businesses specify, cost and grant-fund depot, workplace and fleet EV charging — and how to choose an installer.",
        "body": """
<h2>Why fleet charging is its own discipline</h2>
<p>Charging a fleet is not "home chargers, but more of them". Depot and workplace
sites hit grid-capacity limits, need load management, back-office software, and
phased civils. The installer you pick has to think in megawatts and diversity
factors, not single sockets.</p>
<h2>The three site types</h2>
<ul><li><strong>Depot charging</strong> — vehicles return to base; overnight smart
charging with load balancing is usually the cheapest route.</li>
<li><strong>Workplace charging</strong> — staff and visitor vehicles; eligible for the
Workplace Charging Scheme voucher.</li>
<li><strong>Fleet-in-the-field</strong> — reliance on public/rapid networks; the
installer's job is site surveys for the depot, plus tariff strategy.</li></ul>
<h2>What to ask an installer before you sign</h2>
<ul><li>Have they done a DNO (grid) application for a site this size before?</li>
<li>Is load management included, or bolted on later at cost?</li>
<li>Who owns the charge-point management software and data?</li>
<li>Is the quote OZEV-grant-aware (WCS / Infrastructure Grant applied correctly)?</li></ul>
<div class="box"><strong>Use the directory:</strong> every installer listed here is
OZEV-authorised for commercial work. Filter by your region, shortlist three, and get
comparable quotes. <a style="color:var(--green)" href="/#directory">Open the directory →</a></div>
<h2>Grants change the maths</h2>
<p>Before commissioning, read the <a style="color:var(--green)" href="/guides/workplace-charging-scheme/">Workplace
Charging Scheme</a> and <a style="color:var(--green)" href="/guides/ev-infrastructure-grant/">EV
Infrastructure Grant</a> guides — together they can materially cut the per-socket cost.</p>
""",
    },
    "workplace-charging-scheme": {
        "title": "The Workplace Charging Scheme (WCS) Explained — 2026",
        "desc": "What the OZEV Workplace Charging Scheme covers, who's eligible, the £500-per-socket cap from April 2026, and how to claim.",
        "body": """
<h2>What the WCS is</h2>
<p>The Workplace Charging Scheme is an OZEV voucher that reduces the upfront cost of
buying and installing EV chargepoint sockets at a place of work. It is claimed
<em>through an OZEV-authorised installer</em> — you don't apply for the cash yourself.</p>
<h2>Who is eligible</h2>
<ul><li>Businesses, charities and public-sector organisations registered in the UK.</li>
<li>You must have dedicated off-street parking for staff or fleet.</li>
<li>Sockets must be installed by an OZEV-authorised installer.</li></ul>
<div class="box">From <strong>April 2026</strong> the contribution rises to <strong>up to
£500 per socket</strong> (subject to the scheme's per-applicant socket cap). This is a
strong reason to get quotes in now rather than defer.</div>
<h2>How the claim actually works</h2>
<ul><li>You apply online for a voucher and receive a code.</li>
<li>You give the code to your chosen OZEV-authorised installer.</li>
<li>The installer redeems it and discounts your invoice — the grant never touches
your bank account.</li></ul>
<h2>Next step</h2>
<p>Shortlist OZEV-authorised installers for your region in the
<a style="color:var(--green)" href="/#directory">directory</a> and ask each to quote
<em>with the WCS applied</em> so you compare like for like.</p>
""",
    },
    "ev-infrastructure-grant": {
        "title": "EV Infrastructure Grant for Staff & Fleets — Explained",
        "desc": "The OZEV EV Infrastructure Grant for staff and fleet car parks: what it funds (including supporting infrastructure), eligibility and how installers apply it.",
        "body": """
<h2>What it funds</h2>
<p>The EV Infrastructure Grant helps businesses with the <em>supporting</em>
infrastructure — the cabling, groundworks and capacity upgrades — needed for current
and future chargepoints at staff and fleet car parks. It is designed to be used
alongside the Workplace Charging Scheme, not instead of it.</p>
<h2>Why it matters</h2>
<p>On most commercial sites the expensive part isn't the chargers — it's the trenching,
the new supply and the DNO works. This grant attacks exactly that cost, which is why
fleet projects that looked unaffordable often aren't once it's applied correctly.</p>
<h2>Eligibility in brief</h2>
<ul><li>Small-to-medium businesses with eligible staff/fleet parking.</li>
<li>Work delivered by an OZEV-authorised installer.</li>
<li>Infrastructure must support a minimum number of sockets/parking bays.</li></ul>
<div class="box">The installer applies the grant for you. Pick OZEV-authorised
installers from the <a style="color:var(--green)" href="/#directory">directory</a> and
ask specifically whether they're applying the Infrastructure Grant <em>and</em> WCS.</div>
""",
    },
    "grant-deadlines": {
        "title": "UK EV Charging Grant Deadlines — Kept Current",
        "desc": "Every live UK EV charging grant deadline and rate change on one page, including the April 2026 WCS uplift.",
        "body": """
<h2>Why this page exists</h2>
<p>Grant rates and end-dates move, and missing a change can cost a fleet project
thousands. This page tracks the live position.</p>
<h2>Current position (reviewed regularly)</h2>
<ul>
<li><strong>Workplace Charging Scheme</strong> — contribution rises to up to
<strong>£500 per socket from April 2026</strong>. Scheme remains open; per-applicant
socket cap applies.</li>
<li><strong>EV Infrastructure Grant (staff &amp; fleets)</strong> — open; designed to
run alongside WCS for supporting infrastructure.</li>
<li><strong>Chargepoint grants for flats/landlords</strong> — open, separate scheme;
relevant if your "fleet" includes employee home charging.</li>
</ul>
<div class="disc">This summary is maintained for general guidance and is not financial
or legal advice. Always confirm current rates with your OZEV-authorised installer and
GOV.UK before you commit.</div>
<h2>What to do about it</h2>
<p>If a project is viable at today's rates, the deadlines are a reason to move now.
<a style="color:var(--green)" href="/#directory">Shortlist installers →</a></p>
""",
    },
}


def page_guide(slug: str, g: dict) -> str:
    url = f"{BASE_URL}/guides/{slug}/"
    jl = {"@context": "https://schema.org", "@type": "Article",
           "headline": g["title"], "description": g["desc"],
           "datePublished": TODAY, "dateModified": TODAY,
           "author": {"@type": "Organization", "name": SITE_NAME}}
    jsonld = '<script type="application/ld+json">' + json.dumps(jl) + "</script>"
    aff = """
<h2 style="color:#fff">Hardware &amp; partner options</h2>
<p style="color:#9aa1ab">Independent of the directory listings below. We may earn a
referral fee from some partners — it never changes who is listed or in what order.</p>
<div class="disc" style="background:#1a1607;border-color:#4a3c0a;color:#d8c98a">
Affiliate disclosure: links in this section may be partner links. See
<a style="color:#e0c558" href="/about/">About &amp; disclosure</a>.</div>
<div class="aff">
<span>Partner slot — pending affiliate approval (see MONETIZATION.md)</span>
<span>Partner slot — pending affiliate approval</span>
<span>Partner slot — pending affiliate approval</span></div>"""
    return (
        head(g["title"], g["desc"], url, jsonld)
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> › Guides › {esc(g['title'])}</div>
<section style="padding-top:8px"><div class="wrap prose">
<h1>{esc(g['title'])}</h1><p class="upd">Last reviewed {TODAY} · independent guidance</p>
{g['body']}</div></section>
<section class="sec-d"><div class="wrap">{aff}</div></section>"""
        + footer() + "</body></html>"
    )


def page_simple(title, desc, slug, body_html):
    url = f"{BASE_URL}/{slug}/"
    return (head(title, desc, url) + navbar()
            + f'<section style="padding-top:30px"><div class="wrap prose"><h1>{esc(title)}</h1>{body_html}</div></section>'
            + footer() + "</body></html>")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    src = DATA / "installers.json"
    if not src.exists():
        print("[generate] data/installers.json missing — run pipeline/extract.py first")
        return 1
    payload = json.loads(src.read_text(encoding="utf-8"))
    installers = payload["installers"]
    print(f"[generate] {len(installers)} installers")

    # Robust clean: rmtree can fail on Windows if a handle/cwd is open in dist.
    # Fall back to clearing children so unattended rebuilds never hard-fail.
    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
    if DIST.exists():
        for child in DIST.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    DIST.mkdir(parents=True, exist_ok=True)

    urls = ["/"]
    write(DIST / "index.html", page_index(installers))
    write(DIST / "installers.js",
          "window.__INSTALLERS=" + json.dumps(installers, ensure_ascii=False) + ";")

    for inst in installers:
        sl = slugify(inst["name"]) + "-" + slugify(inst["postcode"])
        write(DIST / "installers" / sl / "index.html",
              page_installer(inst, installers))
        urls.append(f"/installers/{sl}/")

    for region in sorted({i["region"] for i in installers if i["region"] != "N/A"}):
        write(DIST / "regions" / slugify(region) / "index.html",
              page_region(region, installers))
        urls.append(f"/regions/{slugify(region)}/")

    for slug, g in GUIDES.items():
        write(DIST / "guides" / slug / "index.html", page_guide(slug, g))
        urls.append(f"/guides/{slug}/")

    write(DIST / "about" / "index.html", page_simple(
        "About & Affiliate Disclosure", "How this directory is built, our data source, and our affiliate disclosure.",
        "about",
        f"""<p>{esc(SITE_NAME)} is an independent directory. Listings are compiled from
the public GOV.UK OZEV authorised-installer tool under the Open Government Licence v3.0.
We are not affiliated with OZEV, GOV.UK or any installer.</p>
<h2>How listings are ordered</h2><p>Alphabetically (featured partners first). Outbound
links never influence whether or where an installer appears.</p>
<h2>Affiliate disclosure</h2><p>Some outbound links to hardware or service partners may
be affiliate links, meaning we may earn a referral fee at no cost to you. This is
disclosed on the relevant pages and never affects listing order or inclusion.</p>
<h2>Corrections &amp; removal</h2><p>Installers can request a correction or removal via
the <a style="color:var(--green)" href="/contact/">contact page</a>.</p>"""))
    urls.append("/about/")

    write(DIST / "contact" / "index.html", page_simple(
        "Contact / Request a Correction", "Contact the directory to correct or remove a listing.",
        "contact",
        f"""<p>To correct or remove a listing, or for partnership enquiries, email
<a style="color:var(--green)" href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>
<p class="muted">Replace this address post-deploy (see MONETIZATION.md). A free
forwarding address is fine to start.</p>"""))
    urls.append("/contact/")

    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        pr = "1.0" if u == "/" else ("0.8" if u.startswith("/guides") else "0.6")
        sm.append(f"<url><loc>{BASE_URL}{u}</loc><lastmod>{now}</lastmod>"
                  f"<priority>{pr}</priority></url>")
    sm.append("</urlset>")
    write(DIST / "sitemap.xml", "\n".join(sm))
    write(DIST / "robots.txt",
          f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n")
    write(DIST / "404.html",
          head("Not found", "Page not found", BASE_URL + "/404")
          + navbar() + '<section style="padding:80px 0"><div class="wrap prose">'
          '<h1>Page not found</h1><p><a style="color:var(--green)" href="/">'
          'Back to the directory →</a></p></div></section>' + footer()
          + "</body></html>")

    print(f"[generate] DONE — {len(urls)} pages → {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
