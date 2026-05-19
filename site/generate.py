"""
generate.py — Build the static directory site from data/installers.json.

Outputs to site/dist/ (no backend, no DB; all interactivity is client-side
localStorage/JS so it survives the weekly auto-rebuild):

  index.html                       filterable directory + near-me + shortlist tray
  installers/<slug>/index.html     per-installer page (quote CTA, trust, breadcrumb)
  towns/<slug>/index.html          town pages (>=3 installers — anti-thin threshold)
  regions/<slug>/index.html        region hub pages
  guides/<topic>/index.html        deep grant/buyer guides (FAQPage schema)
  calculator/index.html            static grant + install cost calculator
  shortlist/ , compare/            client-side, localStorage-driven
  about/, contact/, privacy/       disclosure, real removal channel, lawful basis
  sitemap.xml, robots.txt, 404.html

Privacy: scraped free-webmail and firstname.lastname personal emails are NOT
published as live mailto (UK GDPR/PECR). Raw contacts are written to a
git-ignored private CSV for the operator only.
"""

from __future__ import annotations

import json
import os
import re
import sys
import csv
import math
import datetime
import shutil
from pathlib import Path

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
BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://commercial-ev-installers.pages.dev"
).rstrip("/")
DEFAULT_BASE = "https://commercial-ev-installers.pages.dev"
CONTACT_EMAIL = os.environ.get("SITE_CONTACT_EMAIL", "hello@example.com")
# Google Search Console HTML-tag verification (set SITE_GSC_TOKEN as a deploy
# env var). Lets a .pages.dev site verify without DNS access. Empty = omitted.
GSC_TOKEN = os.environ.get("SITE_GSC_TOKEN", "").strip()
TODAY = datetime.date.today().isoformat()
TOWN_MIN = 3  # min installers for a town to get its own page (anti-thin-content)

REGIONS_ORDER = [
    "London", "South East", "South West", "East of England", "West Midlands",
    "East Midlands", "Yorkshire & Humber", "North West", "North East",
    "Scotland", "Wales", "Northern Ireland",
]

# Postcode-area -> region fallback for records the scraper left as "N/A"
# (notably the SO/Southampton gap the audit found). Belt-and-braces: even if a
# future scrape regresses, the site still classifies correctly.
AREA_REGION_FALLBACK = {
    "SO": "South East", "GU": "South East", "RG": "South East",
    "PO": "South East", "SP": "South West", "BA": "South West",
}

FREE_MAIL = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk",
    "outlook.com", "outlook.co.uk", "live.com", "live.co.uk", "yahoo.com",
    "yahoo.co.uk", "ymail.com", "btinternet.com", "icloud.com", "me.com",
    "mac.com", "aol.com", "aol.co.uk", "msn.com", "gmx.com", "gmx.co.uk",
    "protonmail.com", "proton.me", "sky.com", "talktalk.net",
    "virginmedia.com", "mail.com", "fastmail.com", "zoho.com",
}
ROLE_LOCAL = {
    "info", "sales", "enquiries", "enquiry", "hello", "admin", "contact",
    "office", "accounts", "support", "mail", "ev", "team", "reception",
    "post", "quotes", "service", "bookings", "hq",
}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s or "x"


def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_ACRONYMS = {"UK", "EV", "EC", "WC", "SE", "SW", "NW", "NE"}


def titlecase_town(town: str) -> str:
    if not town or town == "N/A":
        return "N/A"
    out = []
    for w in town.split():
        if w.upper() in _ACRONYMS or (len(w) <= 3 and w.isupper()):
            out.append(w.upper())
        elif "-" in w:
            out.append("-".join(p.capitalize() for p in w.split("-")))
        else:
            out.append(w.capitalize())
    return " ".join(out)


def clean_host(url: str) -> str:
    """Lowercase the host of a URL, preserve path case."""
    if not url or url == "N/A":
        return "N/A"
    m = re.match(r"^(https?://)([^/]+)(.*)$", url.strip(), re.I)
    if not m:
        return url.strip()
    return m.group(1).lower() + m.group(2).lower() + m.group(3)


def primary_phone(phone: str) -> str | None:
    """Source sometimes lists 'num1 / num2' — return a clean first number."""
    if not phone or phone == "N/A":
        return None
    first = re.split(r"[\/,]| or ", phone)[0]
    digits = re.sub(r"[^\d+]", "", first)
    return digits or None


def public_email(email: str):
    """Return a publishable business email, or None if it must be suppressed
    (free webmail or firstname.lastname personal data — GDPR/PECR)."""
    if not email or email == "N/A" or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    domain = domain.lower().strip()
    local = local.strip()
    if "." not in domain or domain.endswith("."):
        return None  # malformed
    if domain in FREE_MAIL:
        return None  # personal webmail — suppress
    ld = local.lower()
    if ld in ROLE_LOCAL:
        return email
    if re.fullmatch(r"[a-z]+\.[a-z]+", ld):
        return None  # firstname.lastname on a business domain — personal data
    return email  # generic local-part on a business domain — publishable


def haversine(a_lat, a_lon, b_lat, b_lon):
    try:
        a_lat, a_lon, b_lat, b_lon = map(
            float, (a_lat, a_lon, b_lat, b_lon)
        )
    except (TypeError, ValueError):
        return 1e9
    r = 6371.0
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat))
         * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))


def normalize(installers: list[dict]) -> list[dict]:
    """Clean the dataset for publication: fix regions, title-case towns,
    lowercase domains, suppress personal emails, assign collision-free slugs,
    and compute the publishable email policy. Idempotent."""
    seen_slugs: dict[str, int] = {}
    for inst in installers:
        # Region recovery
        if inst.get("region", "N/A") in ("N/A", "", None):
            area = re.match(r"^[A-Z]{1,2}", (inst.get("postcode") or "").upper())
            inst["region"] = AREA_REGION_FALLBACK.get(
                area.group(0) if area else "", "N/A"
            )
        inst["town"] = titlecase_town(inst.get("town", "N/A"))
        inst["website"] = clean_host(inst.get("website", "N/A"))
        inst["phone_primary"] = primary_phone(inst.get("phone", "N/A"))
        inst["email_raw"] = inst.get("email", "N/A")
        pub = public_email(inst.get("email", "N/A"))
        inst["email"] = pub or "N/A"  # public JSON carries only safe emails
        # Stable, collision-free slug — reused everywhere (links + sitemap)
        base = slugify(inst["name"]) + "-" + slugify(inst.get("postcode", "x"))
        if base in seen_slugs:
            seen_slugs[base] += 1
            base = f"{base}-{seen_slugs[base]}"
        else:
            seen_slugs[base] = 1
        inst["_slug"] = base
    return installers


# Town grouping (>= TOWN_MIN installers). Returns {townslug: {...}}.
def build_towns(installers):
    groups: dict[tuple, list] = {}
    for i in installers:
        t, r = i.get("town", "N/A"), i.get("region", "N/A")
        if t in ("N/A", "", None):
            continue
        groups.setdefault((t, r), []).append(i)
    towns = {}
    used = {}
    for (t, r), items in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(items) < TOWN_MIN:
            continue
        s = slugify(t)
        if s in used:
            s = f"{s}-{slugify(r)}"
        used[s] = 1
        towns[s] = {"town": t, "region": r,
                    "items": sorted(items, key=lambda x: x["name"].lower())}
    return towns


def map_data_js(installers):
    """Slim {slug:[lat,lon,name,town]} payload — one shared file, like
    shortlist-data.js. Skips bad coords defensively."""
    pts = {}
    for i in installers:
        try:
            la, lo = round(float(i["lat"]), 5), round(float(i["lon"]), 5)
        except (TypeError, ValueError, KeyError):
            continue
        pts[i["_slug"]] = [la, lo, i["name"], i.get("town", "")]
    return ("window.__MAP=" + json.dumps(pts, ensure_ascii=False,
                                         separators=(",", ":")) + ";")


# ONS mid-2022 regional population estimates (millions) — public, stable.
REGION_POP = {
    "London": 8.87, "South East": 9.38, "South West": 5.76,
    "East of England": 6.40, "West Midlands": 6.02, "East Midlands": 4.95,
    "Yorkshire & Humber": 5.54, "North West": 7.52, "North East": 2.65,
    "Scotland": 5.48, "Wales": 3.13, "Northern Ireland": 1.91,
}


def parse_refresh_report():
    """Pull added/removed/date from the pipeline's report. Safe if missing —
    must never break the unattended build."""
    f = DATA / "refresh_report.md"
    out = {"added": None, "removed": None, "date": None}
    try:
        txt = f.read_text(encoding="utf-8")
        for key, pat in (("added", r"Added since last run:\s*(\d+)"),
                         ("removed", r"Removed since last run:\s*(\d+)"),
                         ("date", r"Refresh report\s*[—-]\s*([\d-]+)")):
            m = re.search(pat, txt)
            if m:
                out[key] = m.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return out


def build_stats(installers):
    from collections import Counter
    n = len(installers)
    by_region = Counter(i["region"] for i in installers if i["region"] != "N/A")
    by_town = Counter(i["town"] for i in installers
                      if i.get("town") not in ("N/A", None))
    density = []
    for r, c in by_region.items():
        pop = REGION_POP.get(r)
        if pop:
            density.append((r, round(c / pop, 1)))
    density.sort(key=lambda x: -x[1])
    has_web = sum(1 for i in installers
                  if i.get("website") not in ("N/A", None))
    also_res = sum(1 for i in installers if "Residential" in i.get("services", []))
    return {
        "total": n,
        "regions": sorted(by_region.items(), key=lambda x: -x[1]),
        "density": density,
        "towns_covered": len(by_town),
        "single_towns": sum(1 for _, c in by_town.items() if c == 1),
        "top_towns": by_town.most_common(10),
        "web_pct": round(has_web / n * 100) if n else 0,
        "also_res_pct": round(also_res / n * 100) if n else 0,
        "growth": parse_refresh_report(),
    }


def svg_bar(rows, unit="", w=680, bar_h=26, gap=8):
    """Static inline-SVG horizontal bar chart — no JS, prints cleanly."""
    if not rows:
        return ""
    mx = max(v for _, v in rows) or 1
    h = len(rows) * (bar_h + gap)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" '
           f'style="width:100%;height:auto;font-family:Inter,sans-serif">']
    for n, (lab, v) in enumerate(rows):
        y = n * (bar_h + gap)
        bw = int((v / mx) * (w - 250))
        out.append(
            f'<text x="0" y="{y+bar_h*0.7:.0f}" font-size="13" fill="#5b6470">{esc(lab)}</text>'
            f'<rect x="155" y="{y}" width="{max(bw,2)}" height="{bar_h}" rx="4" fill="#16a34a"/>'
            f'<text x="{165+max(bw,2)}" y="{y+bar_h*0.7:.0f}" font-size="13" '
            f'font-weight="700" fill="#0a0a0a">{v}{unit}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- styling ----
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--dark:#0a0a0a;--card-d:#141414;--bd-d:#1f1f1f;--light:#f7fafc;
--card-l:#fff;--bd-l:#e8edf3;--green:#16a34a;--green-d:#15803d;--ink:#0a0a0a;
--mut:#5b6470;--mut2:#6b7280}
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
.btn-sm{padding:9px 16px;font-size:13.5px}
.arrow{width:24px;height:24px;border-radius:9999px;background:rgba(255,255,255,.18);
display:inline-flex;align-items:center;justify-content:center;font-size:13px}
.btn-g .arrow,.btn-d .arrow{background:rgba(0,0,0,.12)}
header.nav{position:sticky;top:0;z-index:50;background:rgba(10,10,10,.92);
backdrop-filter:blur(8px);border-bottom:1px solid var(--bd-d)}
.nav .wrap{display:flex;align-items:center;justify-content:space-between;height:64px}
.brand{color:#fff;font-weight:800;letter-spacing:-.5px;text-decoration:none;font-size:17px}
.brand span{color:var(--green)}
.nav nav{display:flex;gap:24px;align-items:center}
.nav nav a{color:#cfd3d8;text-decoration:none;font-size:14px;font-weight:500}
.nav nav a:hover{color:#fff}
.trust{background:#0e1a12;color:#9fe6b4;font-size:12.5px;text-align:center;
padding:8px 16px;border-bottom:1px solid #15301d}
.trust b{color:#fff}
.hero{background:var(--dark);color:#fff;padding:84px 0 72px}
.hero h1{font-size:52px;font-weight:800;line-height:1.04;letter-spacing:-2px;max-width:780px}
.hero p.sub{color:#aab0b8;font-size:19px;margin:22px 0 32px;max-width:620px}
.pill{display:inline-flex;gap:8px;align-items:center;background:rgba(22,163,74,.14);
color:#4ade80;border:1px solid rgba(22,163,74,.3);padding:7px 15px;border-radius:9999px;
font-size:13px;font-weight:600;margin-bottom:26px}
.stats{display:flex;gap:38px;margin-top:46px;flex-wrap:wrap}
.stat b{display:block;font-size:30px;font-weight:800;letter-spacing:-1px}
.stat span{color:#9aa1ab;font-size:13px}
section{padding:64px 0}
.sec-l{background:var(--light)}
h2.sh{font-size:38px;font-weight:800;letter-spacing:-1px;margin-bottom:10px}
.lead{color:var(--mut);font-size:17px;max-width:660px;margin-bottom:30px}
.filters{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;
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
.card .meta{color:var(--mut);font-size:13.5px;margin-bottom:6px}
.card .dist{color:var(--green-d);font-size:12.5px;font-weight:600;margin-bottom:10px}
.tags{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:16px}
.tag{font-size:11.5px;font-weight:600;padding:4px 10px;border-radius:9999px;
background:#eef2f7;color:#3a4452}
.tag.c{background:rgba(22,163,74,.12);color:var(--green-d)}
.tag.v{background:rgba(22,163,74,.12);color:var(--green-d)}
.card .links{margin-top:auto;display:flex;gap:14px;font-size:13px;font-weight:600;
align-items:center;flex-wrap:wrap}
.card .links a{color:var(--green-d);text-decoration:none}
.sl-btn{background:#eef2f7;border:1px solid var(--bd-l);color:#3a4452;font:inherit;
font-size:12.5px;font-weight:600;padding:6px 12px;border-radius:9999px;cursor:pointer}
.sl-btn[aria-pressed=true]{background:var(--green);color:#fff;border-color:var(--green)}
.muted{color:var(--mut)}
.note{font-size:12.5px;color:var(--mut2);margin:6px 0 16px}
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
.prose h3{font-size:18px;font-weight:700;margin:22px 0 8px}
.prose p{margin-bottom:15px;font-size:16.5px}
.prose ul{margin:0 0 16px 22px}.prose li{margin-bottom:8px}
.prose table{border-collapse:collapse;width:100%;margin:18px 0;font-size:14.5px}
.prose th,.prose td{border:1px solid var(--bd-l);padding:9px 12px;text-align:left}
.prose th{background:var(--light);font-weight:700}
.prose .box{background:var(--light);border:1px solid var(--bd-l);border-radius:14px;
padding:20px 22px;margin:22px 0}
.faq dt{font-weight:700;margin-top:18px}
.faq dd{margin:6px 0 0;color:#33404f}
.cta-row{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}
.disc{background:#fff8e6;border:1px solid #f0d98a;color:#7a5c00;font-size:13px;
padding:12px 16px;border-radius:10px;margin:18px 0}
.aff{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:18px}
.aff a,.aff span{display:block;background:var(--card-d);border:1px dashed #3a3a3a;
border-radius:14px;padding:20px;color:#cfd3d8;text-decoration:none;font-size:14px}
.calc{background:var(--card-l);border:1px solid var(--bd-l);border-radius:16px;
padding:26px;display:grid;grid-template-columns:1fr 1fr;gap:18px}
.calc label{display:block;font-size:13px;font-weight:600;margin-bottom:6px;color:#33404f}
.calc input,.calc select{width:100%;font:inherit;font-size:15px;padding:11px 13px;
border:1px solid var(--bd-l);border-radius:10px}
.calc .full{grid-column:1/-1}
.calc-out{grid-column:1/-1;background:var(--light);border-radius:12px;padding:20px;
font-size:15px}
.calc-out .big{font-size:30px;font-weight:800;color:var(--green-d);letter-spacing:-1px}
.tray{position:fixed;right:18px;bottom:18px;z-index:60;background:var(--dark);
color:#fff;border-radius:14px;padding:14px 18px;box-shadow:0 14px 40px rgba(0,0,0,.3);
display:none;align-items:center;gap:14px;font-size:14px}
.tray a{background:var(--green);color:#fff;padding:8px 14px;border-radius:9999px;
text-decoration:none;font-weight:600;font-size:13px}
.tray.show{display:flex}
footer{background:var(--dark);color:#9aa1ab;padding:54px 0;border-top:1px solid var(--bd-d)}
footer .wrap{display:flex;justify-content:space-between;gap:30px;flex-wrap:wrap}
footer a{color:#cfd3d8;text-decoration:none;font-size:14px;display:block;margin-bottom:9px}
footer h4{color:#fff;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-bottom:14px}
.crumb{font-size:13px;color:var(--mut);padding:18px 0}
.crumb a{color:var(--green-d);text-decoration:none}
#map{height:620px;border:1px solid var(--bd-l);border-radius:16px}
.minimap{height:340px;border:1px solid var(--bd-l);border-radius:14px;margin:18px 0}
.leaflet-popup-content{font-family:'Inter',sans-serif;font-size:13.5px}
.leaflet-popup-content a{color:var(--green-d);font-weight:600}
.leaflet-popup-content .sl-btn{margin-top:8px}
.bars{margin:18px 0}.bars svg{width:100%;height:auto}
.statgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:14px;margin:22px 0}
.statbox{background:var(--light);border:1px solid var(--bd-l);border-radius:14px;padding:18px}
.statbox b{display:block;font-size:28px;font-weight:800;letter-spacing:-1px;color:var(--green-d)}
.statbox span{font-size:12.5px;color:var(--mut)}
.cite{background:#0e1a12;border:1px solid #15301d;color:#cfe9d6;border-radius:12px;
padding:16px 18px;font-size:13.5px;margin:22px 0}
.cite code{display:block;background:#06100a;padding:10px 12px;border-radius:8px;
margin-top:8px;color:#9fe6b4;font-size:12.5px;white-space:pre-wrap}
.sharebar{background:#0e1a12;border:1px solid #15301d;color:#cfe9d6;border-radius:12px;
padding:14px 16px;margin:16px 0;font-size:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.sharebar button{font:inherit;font-size:13px;font-weight:600;padding:7px 14px;
border-radius:9999px;border:0;cursor:pointer;background:var(--green);color:#fff}
.pp-sheet{max-width:820px;margin:0 auto;background:#fff;border:1px solid var(--bd-l);
border-radius:14px;padding:40px}
.pp-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 26px;font-size:14px;margin:18px 0}
.pp-grid div{border-bottom:1px solid var(--bd-l);padding:7px 0}
.pp-grid b{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut)}
.pp-q{margin:14px 0 0 20px}.pp-q li{margin-bottom:9px;font-size:14.5px}
.pp-ed{border:1px dashed var(--bd-l);border-radius:8px;padding:10px 12px;font:inherit;
width:100%;margin:4px 0}
.recent{font-size:13px;color:var(--mut);border-top:1px solid var(--bd-l);
margin-top:30px;padding-top:16px}
.recent a{color:var(--green-d);text-decoration:none;font-weight:600}
@media(max-width:680px){.hero h1{font-size:34px}h2.sh{font-size:26px}
.nav nav{display:none}.prose h1{font-size:30px}.calc{grid-template-columns:1fr}
.stats{gap:24px}.pp-grid{grid-template-columns:1fr}#map{height:460px}}
@media print{header.nav,.trust,footer,.tray,.no-print,.btn,.sharebar{display:none!important}
body{background:#fff;color:#000;font-size:12pt}.wrap{max-width:none;padding:0}
.pp-sheet{box-shadow:none;border:0;padding:0}.pp-sheet h1{font-size:20pt}
table,.pp-q li{page-break-inside:avoid}a[href]:after{content:""}@page{margin:18mm}}
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

# Shared shortlist tray + handlers (localStorage, every page, no backend).
SHORTLIST_JS = """
<div class="tray" id="tray"><span id="trayc">0 shortlisted</span>
<a href="/shortlist/">View shortlist &amp; get quotes</a></div>
<script>
window.SL={k:'evdir_shortlist',get:function(){try{return JSON.parse(localStorage.getItem(this.k))||[]}catch(e){return[]}},
set:function(a){localStorage.setItem(this.k,JSON.stringify(a));this.render()},
toggle:function(s){var a=this.get(),i=a.indexOf(s);if(i>-1)a.splice(i,1);else a.push(s);this.set(a)},
has:function(s){return this.get().indexOf(s)>-1},
render:function(){var a=this.get(),t=document.getElementById('tray');
if(t){document.getElementById('trayc').textContent=a.length+' shortlisted';
t.className='tray'+(a.length?' show':'')}
document.querySelectorAll('[data-sl]').forEach(function(b){
var on=window.SL.has(b.getAttribute('data-sl'));
b.setAttribute('aria-pressed',on);b.textContent=on?'\\u2713 Shortlisted':'+ Shortlist';});}};
document.addEventListener('click',function(e){var b=e.target.closest('[data-sl]');
if(b){e.preventDefault();window.SL.toggle(b.getAttribute('data-sl'));}});
document.addEventListener('DOMContentLoaded',function(){window.SL.render()});
</script>"""

# Leaflet + markercluster from CDN (runtime only — generate.py never fetches
# these, so the unattended rebuild is unaffected). Leaflet has official SRI;
# markercluster degrades gracefully to plain pins via the try/catch in the JS.
LEAFLET_HEAD = (
    '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" '
    'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">'
    '<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" crossorigin="">'
    '<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" crossorigin="">'
)
LEAFLET_JS = (
    '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" '
    'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>'
    '<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js" crossorigin=""></script>'
)

# Share-a-shortlist via URL hash (#s=slug,slug). Same-device localStorage is the
# baseline; this lets a colleague open the same shortlist. Loaded on /shortlist/.
SHARE_JS = """<script>
(function(){var h=location.hash;if(h.indexOf('#s=')===0){var ids=h.slice(3).split(',')
.filter(Boolean);var D=window.__SLD||{};ids=ids.filter(function(s){return D[s]});
if(ids.length){var cur=window.SL.get();var add=ids.filter(function(s){return cur.indexOf(s)<0});
if(add.length){var bn=document.createElement('div');bn.className='sharebar';
bn.innerHTML='A colleague shared '+ids.length+' installer'+(ids.length>1?'s':'')+
'. <button id="shadd">Add to my shortlist</button><button id="sharep" '+
'style="background:#26323f">Replace mine</button>';
var a=document.querySelector('.prose');if(a)a.insertBefore(bn,a.children[2]||null);
document.getElementById('shadd').onclick=function(){window.SL.set(cur.concat(add));location.hash='';location.reload()};
document.getElementById('sharep').onclick=function(){window.SL.set(ids);location.hash='';location.reload()};}}
history.replaceState(null,'',location.pathname);}})();
</script>"""


def head(title, desc, canonical, jsonld="", noindex=False):
    robots = "noindex,follow" if noindex else "index,follow"
    gsc = (f'<meta name="google-site-verification" content="{esc(GSC_TOKEN)}">'
           if GSC_TOKEN else "")
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website"><meta name="robots" content="{robots}">{gsc}
{FAVICON}{FONT}<style>{CSS}</style>{jsonld}</head><body>"""


def trust_strip():
    return ('<div class="trust">Built from <b>official GOV.UK / OZEV</b> data '
            "(Open Government Licence v3.0) · Independent · "
            "<b>Listing order is never sold</b></div>")


def navbar():
    return f"""<header class="nav"><div class="wrap">
<a class="brand" href="/">Commercial<span>EV</span>Installers</a>
<nav><a href="/#directory">Directory</a><a href="/map/">Map</a>
<a href="/calculator/">Calculator</a><a href="/data/uk-ev-installer-landscape/">Data</a>
<a href="/guides/ev-charging-for-fleets/">Fleet guide</a>
<a href="/guides/workplace-charging-scheme/">WCS grant</a></nav></div></header>""" + trust_strip()


def breadcrumb_jsonld(trail):
    return '<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": n + 1, "name": name,
             "item": BASE_URL + path}
            for n, (name, path) in enumerate(trail)
        ],
    }) + "</script>"


def faq_jsonld(pairs):
    return '<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in pairs
        ],
    }) + "</script>"


def faq_html(pairs):
    items = "".join(f"<dt>{esc(q)}</dt><dd>{a}</dd>" for q, a in pairs)
    return f'<h2>Frequently asked questions</h2><dl class="faq">{items}</dl>'


def footer():
    reg = "".join(
        f'<a href="/regions/{slugify(r)}/">{esc(r)}</a>' for r in REGIONS_ORDER[:8]
    )
    return f"""<footer><div class="wrap">
<div><h4>{esc(SITE_NAME)}</h4>
<p style="max-width:330px;font-size:13px">Independent directory built from the public
GOV.UK OZEV authorised-installer data (Open Government Licence v3.0). Not affiliated
with OZEV or any installer. <a style="display:inline;color:#9fe6b4" href="/privacy/">Privacy &amp; data</a>.</p></div>
<div><h4>Tools &amp; guides</h4><a href="/calculator/">Grant + cost calculator</a>
<a href="/guides/ev-charging-for-fleets/">EV charging for fleets</a>
<a href="/guides/workplace-charging-scheme/">Workplace Charging Scheme</a>
<a href="/guides/grant-deadlines/">Grant deadlines</a></div>
<div><h4>Regions</h4>{reg}</div></div>
<div class="wrap" style="margin-top:34px;font-size:12.5px;border-top:1px solid #1f1f1f;padding-top:22px">
Data source: <a href="https://www.gov.uk/electric-vehicle-chargepoint-installers" style="display:inline">GOV.UK / OZEV</a>,
Open Government Licence v3.0. Last refreshed {TODAY}. &copy; {datetime.date.today().year}.
Featured partners are labelled and shown first; outbound/affiliate links never affect
who is listed. <a style="display:inline;color:#9fe6b4" href="/about/">About &amp; disclosure</a>.</div></footer>"""


def card(inst, distance=None):
    sl = inst["_slug"]
    tags = "".join(
        f'<span class="tag c">{esc(s)}</span>' if s == "Commercial"
        else f'<span class="tag">{esc(s)}</span>'
        for s in inst["services"]
    )
    tags += '<span class="tag v">✓ OZEV authorised</span>'
    feat = "feat" if inst.get("featured") else ""
    ftag = '<span class="ftag">FEATURED PARTNER</span>' if inst.get("featured") else ""
    loc = " · ".join(p for p in [inst.get("town"), inst.get("region")]
                     if p and p != "N/A")
    web = ""
    if inst.get("website") and inst["website"] != "N/A":
        web = (f'<a href="{esc(inst["website"])}" target="_blank" '
               f'rel="nofollow noopener">Visit website →</a>')
    dist = (f'<div class="dist">≈ {distance:.0f} km away</div>'
            if distance is not None else "")
    nm = esc(inst["name"])
    return f"""<article class="card {feat}" data-name="{esc(inst['name'].lower())}"
data-region="{esc(inst.get('region',''))}" data-services="{esc(','.join(inst['services']))}"
data-town="{esc((inst.get('town') or '').lower())}"
data-lat="{esc(inst.get('lat','N/A'))}" data-lon="{esc(inst.get('lon','N/A'))}">
{ftag}<h3><a href="/installers/{sl}/">{nm}</a></h3>
<div class="meta">{esc(loc) or 'United Kingdom'}</div>{dist}
<div class="tags">{tags}</div>
<div class="links"><a href="/installers/{sl}/">View details</a>{web}
<button class="sl-btn" data-sl="{sl}" aria-pressed="false" type="button">+ Shortlist</button></div></article>"""


def page_index(installers):
    n = len(installers)
    regions = sorted({i["region"] for i in installers if i["region"] != "N/A"})
    feat = [i for i in installers if i.get("featured")]
    ordered = feat + [i for i in installers if not i.get("featured")]
    cards = "".join(card(i) for i in ordered)
    ropts = "".join(f'<option value="{esc(r)}">{esc(r)}</option>' for r in regions)
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "WebSite",
        "name": SITE_NAME, "url": BASE_URL, "description": SITE_TAGLINE,
    }) + "</script>")
    return (
        head(f"{SITE_NAME} — OZEV-Authorised Directory",
             f"Find OZEV-authorised commercial & fleet EV charging point installers across the UK. {n} verified installers, filterable by region, service and distance. Free, independent.",
             BASE_URL + "/", jsonld)
        + navbar()
        + f"""<section class="hero"><div class="wrap">
<span class="pill">● {n} OZEV-authorised commercial installers · all 12 UK regions</span>
<h1>Find a commercial EV charging installer that can actually do the job.</h1>
<p class="sub">{esc(SITE_TAGLINE)}. Every installer is authorised by the Office for
Zero Emission Vehicles for commercial or fleet work — filterable and comparable the
way the official tool isn't.</p>
<a class="btn btn-g" href="#directory">Browse the directory <span class="arrow">→</span></a>
<a class="btn btn-o" href="/calculator/" style="margin-left:12px">Grant + cost calculator</a>
<div class="stats">
<div class="stat"><b>{n}</b><span>commercial installers</span></div>
<div class="stat"><b>{len(regions)}</b><span>UK regions covered</span></div>
<div class="stat"><b>£500</b><span>WCS grant / socket (from Apr 2026)</span></div>
<div class="stat"><b>£0</b><span>cost to use — independent</span></div></div>
</div></section>

<section id="directory"><div class="wrap">
<h2 class="sh">The directory</h2>
<p class="lead">Search and filter {n} OZEV-authorised installers offering commercial
or fleet installations. Shortlist several and request quotes in one go. Featured
partners are labelled and shown first; nothing else affects order.</p>
<div class="filters">
<input id="q" type="search" placeholder="Search by installer name or town…" aria-label="Search by name or town">
<select id="fr" aria-label="Filter by region"><option value="">All regions</option>{ropts}</select>
<select id="fs" aria-label="Filter by service"><option value="">All services</option>
<option value="Commercial">Commercial</option><option value="Residential">Also residential</option></select>
<button class="btn btn-g btn-sm" id="near" type="button">📍 Near me</button>
</div>
<p id="count" class="note">{n} installers — use the filters or “Near me” to narrow down</p>
<div id="grid" class="grid">{cards}</div>
<p id="empty" class="muted" style="display:none;padding:30px 0">No installers match
those filters. Try widening your search.</p>
</div></section>

<section class="sec-d"><div class="wrap">
<h2 class="sh">Work out the numbers first</h2>
<p class="lead">Most commercial installs are part grant-funded. Estimate your cost
and grant before you talk to anyone.</p>
<a class="btn btn-g" href="/calculator/">Open the grant + cost calculator <span class="arrow">→</span></a>
<div class="guidegrid" style="margin-top:34px">
<a class="gcard" href="/guides/ev-charging-for-fleets/"><h3>EV charging for fleets</h3>
<p>Depot vs workplace vs destination — what each costs and which grant applies.</p></a>
<a class="gcard" href="/guides/workplace-charging-scheme/"><h3>Workplace Charging Scheme</h3>
<p>£350 → £500/socket from 1 Apr 2026, 75% cap, 40-socket limit, ends 31 Mar 2027.</p></a>
<a class="gcard" href="/guides/ev-infrastructure-grant/"><h3>EV Infrastructure Grant</h3>
<p>The grant that pays for the expensive groundworks and DNO supply.</p></a>
<a class="gcard" href="/guides/grant-deadlines/"><h3>Grant deadlines</h3>
<p>Every live deadline and rate change on one page.</p></a>
</div></div></section>"""
        + footer() + SHORTLIST_JS
        + """<script>
(function(){var q=document.getElementById('q'),fr=document.getElementById('fr'),
fs=document.getElementById('fs'),g=document.getElementById('grid'),
em=document.getElementById('empty'),ct=document.getElementById('count'),
nb=document.getElementById('near'),cards=[].slice.call(g.children),total=cards.length;
function run(){var t=(q.value||'').toLowerCase().trim(),r=fr.value,s=fs.value,v=0;
cards.forEach(function(c){var ok=(!t||c.dataset.name.indexOf(t)>-1||c.dataset.town.indexOf(t)>-1)
&&(!r||c.dataset.region===r)&&(!s||c.dataset.services.indexOf(s)>-1);
c.style.display=ok?'':'none';if(ok)v++;});
em.style.display=v?'none':'';
ct.textContent=v+' of '+total+' installer'+(v===1?'':'s')+' shown';}
q.addEventListener('input',run);fr.addEventListener('change',run);
fs.addEventListener('change',run);
function hav(a,b,c,d){function r(x){return x*Math.PI/180}var R=6371,
p=r(c-a),l=r(d-b),h=Math.sin(p/2)*Math.sin(p/2)+Math.cos(r(a))*Math.cos(r(c))*
Math.sin(l/2)*Math.sin(l/2);return 2*R*Math.asin(Math.sqrt(h));}
nb.addEventListener('click',function(){if(!navigator.geolocation){
ct.textContent='Location not available in this browser.';return;}
ct.textContent='Locating…';navigator.geolocation.getCurrentPosition(function(pos){
var la=pos.coords.latitude,lo=pos.coords.longitude;
cards.forEach(function(c){var cl=parseFloat(c.dataset.lat),cn=parseFloat(c.dataset.lon);
var d=(isNaN(cl)||isNaN(cn))?1e9:hav(la,lo,cl,cn);c._d=d;
var old=c.querySelector('.dist');if(old)old.remove();
if(d<1e8){var e=document.createElement('div');e.className='dist';
e.textContent='\\u2248 '+d.toFixed(0)+' km away';
c.insertBefore(e,c.querySelector('.tags'));}});
cards.sort(function(a,b){return a._d-b._d}).forEach(function(c){g.appendChild(c);});
ct.textContent='Sorted by distance from you — nearest first';
},function(){ct.textContent='Couldn\\'t get your location (permission denied).';});});
run();})();
</script></body></html>"""
    )


def _contact_block(inst):
    """Primary 'request a quote' CTA respecting the email-suppression policy."""
    web = inst.get("website")
    has_web = web and web != "N/A"
    email = inst.get("email")  # already public-policy-filtered in normalize()
    phone = inst.get("phone_primary")
    subject = f"EV charging install enquiry (via the OZEV directory)"
    body = (
        "Hello,%0D%0A%0D%0AI found you on the independent OZEV commercial EV "
        "installer directory. I'd like a quote for a commercial/fleet EV "
        "charging installation.%0D%0A%0D%0ASite postcode:%0D%0AApprox. number "
        "of sockets:%0D%0ASite type (workplace / depot / fleet):%0D%0ATimescale:"
        "%0D%0A%0D%0APlease let me know what else you need. Thanks."
    )
    if email and email != "N/A":
        primary = (f'<a class="btn btn-g" href="mailto:{esc(email)}'
                   f'?subject={subject}&body={body}">Request a quote '
                   f'<span class="arrow">→</span></a>')
    elif has_web:
        primary = (f'<a class="btn btn-g" href="{esc(web)}" target="_blank" '
                   f'rel="nofollow noopener">Contact via website '
                   f'<span class="arrow">→</span></a>')
    elif phone:
        primary = f'<a class="btn btn-g" href="tel:{esc(phone)}">Call {esc(phone)}</a>'
    else:
        primary = ('<a class="btn btn-d" href="/contact/">Details limited — '
                   'request via us</a>')
    sec = ""
    if has_web and (email and email != "N/A"):
        sec = (f'<a class="btn btn-o" style="border-color:#cfd6df;color:#0a0a0a" '
               f'href="{esc(web)}" target="_blank" rel="nofollow noopener">Visit website</a>')
    return primary, sec


def page_installer(inst, by_slug, all_inst):
    sl = inst["_slug"]
    url = f"{BASE_URL}/installers/{sl}/"
    addr = ", ".join(p for p in [inst.get("street"), inst.get("town"),
                                 inst.get("postcode")] if p and p != "N/A")
    # Nearest others by distance (more useful than "same region")
    others = [i for i in all_inst if i["name"] != inst["name"]]
    if inst.get("lat") not in (None, "N/A"):
        others.sort(key=lambda i: haversine(
            inst["lat"], inst["lon"], i.get("lat"), i.get("lon")))
    nearby = others[:6]
    jl = {"@context": "https://schema.org", "@type": "LocalBusiness",
          "name": inst["name"],
          "description": f"OZEV-authorised commercial EV chargepoint installer. {inst.get('service_text','')}",
          "areaServed": inst.get("region", "United Kingdom")}
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
    if inst.get("phone_primary"):
        jl["telephone"] = inst["phone_primary"]
    trail = [("Directory", "/"),
             (inst.get("region", "UK"),
              f"/regions/{slugify(inst.get('region','uk'))}/"),
             (inst["name"], f"/installers/{sl}/")]
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>" + breadcrumb_jsonld(trail))
    primary, sec = _contact_block(inst)

    def row(label, val, link=None):
        if not val or val == "N/A":
            disp = '<span class="muted">Not listed</span>'
        elif link:
            ext = 'target="_blank" rel="nofollow noopener"' if link.startswith("http") else ""
            disp = f'<a href="{esc(link)}" {ext} style="color:var(--green-d)">{esc(val)}</a>'
        else:
            disp = esc(val)
        return f"<p><strong>{label}:</strong> {disp}</p>"

    web = inst.get("website")
    web_val = None if web == "N/A" else web
    email_pub = inst.get("email")
    email_row = (row("Email", email_pub, "mailto:" + email_pub)
                 if email_pub and email_pub != "N/A"
                 else '<p><strong>Email:</strong> <span class="muted">Use “Request '
                      'a quote” — direct address withheld for privacy</span></p>')
    maps = ""
    if inst.get("lat") not in (None, "N/A"):
        maps = (f'<p><a style="color:var(--green-d)" target="_blank" rel="noopener" '
                f'href="https://maps.google.com/maps?q=loc:{inst["lat"]},{inst["lon"]}">'
                f'View on Google Maps →</a></p>')
    near = "".join(card(i) for i in nearby)
    faqs = [
        (f"Is {inst['name']} OZEV-authorised for commercial work?",
         f"Yes. {inst['name']} appears on the official GOV.UK OZEV authorised "
         f"installer list for commercial/fleet installations as of {esc(inst.get('last_verified',TODAY))}. "
         "Always confirm current status directly before contracting."),
        ("Can I get a grant towards this installation?",
         "Commercial and fleet installs are frequently part-funded by the "
         "Workplace Charging Scheme (up to £500/socket from 1 April 2026) and "
         "the EV Infrastructure Grant. The installer applies these for you."),
        (f"How do I get a quote from {inst['name']}?",
         "Use the “Request a quote” button on this page, or add them to your "
         "shortlist and request quotes from several installers at once."),
    ]
    return (
        head(f"{inst['name']} — OZEV Commercial EV Charger Installer ({inst.get('region','UK')})",
             f"{inst['name']} is an OZEV-authorised commercial EV chargepoint installer in {inst.get('town','the UK')}. Service area, grant context and how to request a quote.",
             url, jsonld + faq_jsonld(faqs))
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> ›
<a href="/regions/{slugify(inst.get('region','uk'))}/">{esc(inst.get('region','UK'))}</a> › {esc(inst['name'])}</div>
<section style="padding-top:8px"><div class="wrap prose">
<h1>{esc(inst['name'])}</h1>
<p class="upd">OZEV-authorised commercial EV chargepoint installer · data refreshed {esc(inst.get('last_verified',TODAY))}</p>
<div class="cta-row">{primary}{sec}
<button class="sl-btn" data-sl="{sl}" aria-pressed="false" type="button"
style="padding:13px 22px;border-radius:9999px">+ Add to shortlist</button></div>
<div class="box">
{row('Services', inst.get('service_text'))}
{row('Service region', inst.get('region'))}
{row('Address', addr)}
{row('Website', web_val, web_val)}
{row('Phone', inst.get('phone_primary'), 'tel:'+inst['phone_primary'] if inst.get('phone_primary') else None)}
{email_row}
{row('Accreditation', ', '.join(inst.get('accreditations',[])))}
{maps}</div>
<p class="muted" style="font-size:13.5px">Compiled from the public GOV.UK OZEV
authorised-installer tool (Open Government Licence v3.0). Details change — confirm
directly before contracting. <a style="color:var(--green-d)" href="/contact/">Request a correction or removal</a>.</p>
<h2>Could this install be grant-funded?</h2>
<p>Most commercial and fleet installs are. Run the numbers in the
<a style="color:var(--green-d)" href="/calculator/">grant + cost calculator</a>, then
read the <a style="color:var(--green-d)" href="/guides/workplace-charging-scheme/">Workplace
Charging Scheme</a> and <a style="color:var(--green-d)" href="/guides/ev-infrastructure-grant/">EV
Infrastructure Grant</a> guides before you commission work.</p>
{faq_html(faqs)}
</div></section>
<section class="sec-l"><div class="wrap"><h2 class="sh">Nearest other OZEV installers</h2>
<div class="grid">{near or '<p class=muted>No other installers indexed nearby yet.</p>'}</div></div></section>"""
        + footer() + SHORTLIST_JS + "</body></html>"
    )


def page_region(region, installers):
    items = sorted([i for i in installers if i["region"] == region],
                   key=lambda x: x["name"].lower())
    url = f"{BASE_URL}/regions/{slugify(region)}/"
    towns = sorted({i["town"] for i in items if i.get("town") not in ("N/A", None)})
    cards = "".join(card(i) for i in items)
    jl = {"@context": "https://schema.org", "@type": "ItemList",
          "name": f"Commercial EV charger installers in {region}",
          "numberOfItems": len(items),
          "itemListElement": [
              {"@type": "ListItem", "position": n + 1,
               "url": f"{BASE_URL}/installers/{i['_slug']}/", "name": i["name"]}
              for n, i in enumerate(items[:100])]}
    trail = [("Directory", "/"), (region, f"/regions/{slugify(region)}/")]
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>" + breadcrumb_jsonld(trail))
    townlinks = " · ".join(
        f'<a style="color:var(--green-d)" href="/towns/{slugify(t)}/">{esc(t)}</a>'
        for t in towns[:40]) if towns else ""
    return (
        head(f"Commercial EV Charger Installers in {region} — OZEV Authorised",
             f"{len(items)} OZEV-authorised commercial and fleet EV charging installers in {region}. Independent, filterable, free.",
             url, jsonld)
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> › {esc(region)}</div>
<section style="padding-top:8px"><div class="wrap">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">Commercial EV charger installers in {esc(region)}</h1>
<p class="lead" style="margin-top:14px">{len(items)} OZEV-authorised installers offering
commercial or fleet EV charging installation across {esc(region)}.</p>
{f'<p class="note">Towns: {townlinks}</p>' if townlinks else ''}
<div class="grid">{cards or '<p class=muted>None indexed yet — coverage widens each refresh.</p>'}</div>
</div></section>""" + footer() + SHORTLIST_JS + "</body></html>"
    )


def page_town(slug, t):
    town, region, items = t["town"], t["region"], t["items"]
    url = f"{BASE_URL}/towns/{slug}/"
    cards = "".join(card(i) for i in items)
    jl = {"@context": "https://schema.org", "@type": "ItemList",
          "name": f"Commercial EV charger installers in {town}",
          "numberOfItems": len(items),
          "itemListElement": [
              {"@type": "ListItem", "position": n + 1,
               "url": f"{BASE_URL}/installers/{i['_slug']}/", "name": i["name"]}
              for n, i in enumerate(items[:100])]}
    trail = [("Directory", "/"),
             (region, f"/regions/{slugify(region)}/"),
             (town, f"/towns/{slug}/")]
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>" + breadcrumb_jsonld(trail))
    faqs = [
        (f"How many OZEV-authorised commercial EV installers are in {town}?",
         f"This directory lists {len(items)} OZEV-authorised installer"
         f"{'s' if len(items)!=1 else ''} offering commercial or fleet EV "
         f"charging installation in or around {town}."),
        (f"Is there a grant for commercial EV charging in {town}?",
         "Yes — the Workplace Charging Scheme (up to £500/socket from 1 April "
         "2026) and the EV Infrastructure Grant apply UK-wide, including "
         f"{town}. Your installer applies them to your quote."),
        ("How do I choose between them?",
         "Shortlist three, then use the “request quotes” flow to ask each for "
         "a like-for-like quote with the grant applied."),
    ]
    return (
        head(f"Commercial EV Charger Installers in {town} — OZEV Authorised",
             f"{len(items)} OZEV-authorised commercial & fleet EV charger installers in {town} ({region}). Compare and request quotes — independent, free.",
             url, jsonld + faq_jsonld(faqs))
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> ›
<a href="/regions/{slugify(region)}/">{esc(region)}</a> › {esc(town)}</div>
<section style="padding-top:8px"><div class="wrap">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">Commercial EV charger installers in {esc(town)}</h1>
<p class="lead" style="margin-top:14px">{len(items)} OZEV-authorised installer{'s' if len(items)!=1 else ''}
covering commercial and fleet EV charging in {esc(town)}, {esc(region)}. Shortlist
and request quotes in one go, or estimate your grant first with the
<a style="color:var(--green-d)" href="/calculator/">cost calculator</a>.</p>
<div class="grid">{cards}</div>
<div class="prose" style="margin-top:40px;max-width:760px">{faq_html(faqs)}</div>
</div></section>""" + footer() + SHORTLIST_JS + "</body></html>"
    )


# ------------------------------------------------------------ calculator ----
def page_calculator():
    url = f"{BASE_URL}/calculator/"
    faqs = [
        ("How accurate is this estimate?",
         "It is an indicative range only, using public grant rates and typical "
         "UK price bands. Real cost depends on groundworks, DNO supply and site "
         "specifics — always get itemised quotes from OZEV-authorised installers."),
        ("What is the Workplace Charging Scheme worth?",
         "Up to £350 per socket until 31 March 2026, rising to up to £500 per "
         "socket from 1 April 2026, covering up to 75% of total cost, capped at "
         "40 sockets per applicant. The scheme runs until 31 March 2027."),
        ("Can I claim more than one grant?",
         "Yes — the Workplace Charging Scheme and the EV Infrastructure Grant "
         "are designed to be used together. Your installer applies both."),
    ]
    jl = {"@context": "https://schema.org", "@type": "WebApplication",
          "name": "EV charging grant + cost calculator",
          "applicationCategory": "BusinessApplication",
          "operatingSystem": "Web", "url": url,
          "offers": {"@type": "Offer", "price": "0",
                     "priceCurrency": "GBP"}}
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>" + faq_jsonld(faqs)
              + breadcrumb_jsonld([("Directory", "/"),
                                   ("Cost calculator", "/calculator/")]))
    return (
        head("EV Charging Grant + Install Cost Calculator (UK, 2026)",
             "Free calculator: estimate commercial/fleet EV charger install cost and your Workplace Charging Scheme grant (up to £500/socket from April 2026). Indicative UK ranges.",
             url, jsonld)
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> › Cost calculator</div>
<section style="padding-top:8px"><div class="wrap" style="max-width:860px">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">EV charging grant + cost calculator</h1>
<p class="lead" style="margin-top:14px">An indicative estimate of a commercial /
fleet EV charging install and the grant you could claim. Numbers are public UK
ranges — get itemised quotes before you commit.</p>
<div class="calc">
<div class="full"><label for="pc">Site postcode (optional — used for your project pack)</label>
<input id="pc" type="text" maxlength="8" placeholder="e.g. M1 4AB" style="text-transform:uppercase"></div>
<div><label for="sk">Number of charge sockets</label>
<input id="sk" type="number" min="1" max="200" value="6"></div>
<div><label for="ct">Charger type</label><select id="ct">
<option value="fast">Fast AC 7–22 kW (workplace / depot)</option>
<option value="rapid">Rapid DC 50–100 kW</option>
<option value="ultra">Ultra-rapid 100 kW+</option></select></div>
<div><label for="st">Site type</label><select id="st">
<option value="wp">Workplace car park</option>
<option value="depot">Fleet depot</option>
<option value="dest">Destination / customer</option></select></div>
<div><label for="gr">Apply Workplace Charging Scheme?</label><select id="gr">
<option value="1">Yes — eligible (off-street staff/fleet parking)</option>
<option value="0">No / not eligible</option></select></div>
<div class="calc-out" id="out"></div>
</div>
<p class="note" style="margin-top:14px">Indicative only — not a quote, not financial
advice. WCS: up to £350/socket now, £500/socket from 1 Apr 2026, ≤75% of cost, max
40 sockets, scheme ends 31 Mar 2027. Always confirm on
<a style="color:var(--green-d)" href="https://www.gov.uk/government/publications/workplace-charging-scheme-guidance-for-applicants">GOV.UK</a>.</p>
<div class="cta-row"><a class="btn btn-g" href="/#directory">See OZEV installers who can quote this <span class="arrow">→</span></a>
<a class="btn btn-d" href="/project-pack/">Turn this into a project pack →</a></div>
<div class="prose" style="margin-top:40px">{faq_html(faqs)}</div>
</div></section>""" + footer() + SHORTLIST_JS
        + """<script>
(function(){var pc=document.getElementById('pc'),sk=document.getElementById('sk'),
ct=document.getElementById('ct'),st=document.getElementById('st'),
gr=document.getElementById('gr'),out=document.getElementById('out');
try{var sv=JSON.parse(localStorage.getItem('evdir_project'));if(sv){
if(sv.pc)pc.value=sv.pc;if(sv.sk)sk.value=sv.sk;if(sv.ct)ct.value=sv.ct;
if(sv.st)st.value=sv.st;if(sv.gr!=null)gr.value=sv.gr;}}catch(e){}
var band={fast:[1200,3000],rapid:[12000,35000],ultra:[35000,80000]};
var civ={wp:[600,2500],depot:[1500,9000],dest:[800,3000]};
function money(n){return '£'+Math.round(n).toLocaleString('en-GB');}
function calc(){var n=Math.max(1,Math.min(200,parseInt(sk.value)||1));
var b=band[ct.value],c=civ[st.value];
var lo=n*b[0]+c[0], hi=n*b[1]+c[1];
var now=new Date(), apr26=new Date('2026-04-01');
var per=(now>=apr26)?500:350, rate=(now>=apr26)?'£500':'£350';
var sock=Math.min(n,40);
var grant=gr.value==='1'?Math.min(sock*per, hi*0.75):0;
var nlo=Math.max(0,lo-grant), nhi=Math.max(0,hi-grant);
out.innerHTML='<div>Estimated install (before grant)</div>'+
'<div class=big>'+money(lo)+' – '+money(hi)+'</div>'+
(grant>0?'<div style=\"margin-top:10px\">Workplace Charging Scheme ('+rate+
'/socket × '+sock+') ≈ <strong>−'+money(grant)+'</strong></div>'+
'<div style=\"margin-top:6px\">Estimated net cost</div>'+
'<div class=big>'+money(nlo)+' – '+money(nhi)+'</div>':
'<div style=\"margin-top:10px\" class=muted>No WCS applied. Eligible workplaces can claim up to '+rate+'/socket.</div>')+
'<div style=\"margin-top:12px;font-size:12.5px\" class=muted>Plus possible DNO/grid upgrade (£4,500–£50,000+ for higher-power sites) and £10–£50/charger/month for management software. Indicative only.</div>';
try{localStorage.setItem('evdir_project',JSON.stringify({
pc:(pc.value||'').trim().toUpperCase(),sk:n,ct:ct.value,st:st.value,gr:gr.value,
lo:lo,hi:hi,grant:grant,nlo:nlo,nhi:nhi,rate:rate,sock:sock,
ts:new Date().toISOString().slice(0,10)}));}catch(e){}}
[pc,sk,ct,st,gr].forEach(function(e){e.addEventListener('input',calc);e.addEventListener('change',calc);});
calc();})();
</script></body></html>"""
    )


def page_shortlist():
    url = f"{BASE_URL}/shortlist/"
    return (
        head("Your shortlist — request EV installer quotes",
             "Your shortlisted OZEV-authorised commercial EV charger installers. Request quotes from several at once.",
             url, "", noindex=True)
        + navbar()
        + """<div class="wrap crumb"><a href="/">Directory</a> › Shortlist</div>
<section style="padding-top:8px"><div class="wrap prose">
<h1>Your shortlist</h1>
<p class="upd">Saved on this device only — nothing is sent anywhere until you choose to.</p>
<div id="sl"></div>
<div id="empty" class="muted">Your shortlist is empty. Browse the
<a style="color:var(--green-d)" href="/#directory">directory</a> and tap “+ Shortlist”.</div>
<div id="act" class="cta-row" style="display:none">
<a class="btn btn-g" href="/project-pack/">Build my project pack (printable RFQ) →</a>
<button class="btn btn-d" id="brief" type="button">Copy a quote brief</button>
<button class="btn btn-d" id="share" type="button">Copy share link</button></div>
<p class="note" id="msg"></p>
<div class="box" style="margin-top:24px"><strong>How to get quotes:</strong> open each
installer below, hit “Request a quote” (a pre-filled email opens), and paste the brief.
Three good quotes beats one — that's the whole point of a shortlist.</div>
</div></section>""" + footer() + SHORTLIST_JS
        + """<script src="/shortlist-data.js"></script><script>
(function(){var box=document.getElementById('sl'),em=document.getElementById('empty'),
act=document.getElementById('act'),msg=document.getElementById('msg');
var ids=window.SL.get(),D=window.__SLD||{};
if(ids.length){em.style.display='none';act.style.display='';
box.innerHTML=ids.map(function(s){var d=D[s];if(!d)return '';
return '<div class=box><strong>'+d.n+'</strong><br><span class=muted>'+
(d.t||'')+(d.r?' · '+d.r:'')+'</span><br><a style=\"color:var(--green-d)\" href=\"/installers/'+s+
'/\">Open & request a quote →</a> &nbsp; <button class=sl-btn data-sl=\"'+s+
'\">Remove</button></div>';}).join('');}
var brief="Hello,\\n\\nI found you via the independent OZEV commercial EV installer "+
"directory and I'm requesting a quote for a commercial/fleet EV charging install.\\n\\n"+
"Site postcode:\\nApprox. sockets:\\nSite type (workplace/depot/fleet):\\nTimescale:\\n\\nThanks.";
document.getElementById('brief').addEventListener('click',function(){
navigator.clipboard.writeText(brief).then(function(){
msg.textContent='Brief copied — paste it into each installer\\'s quote email.';},
function(){msg.textContent=brief;});});
document.getElementById('share').addEventListener('click',function(){
var u=location.origin+'/shortlist/#s='+window.SL.get().join(',');
navigator.clipboard.writeText(u).then(function(){
msg.textContent='Share link copied — send it to a colleague to open the same shortlist.';},
function(){msg.textContent=u;});});
window.SL.render();})();
</script>""" + SHARE_JS + "</body></html>"
    )


def page_map():
    url = f"{BASE_URL}/map/"
    return (
        head("UK Map of OZEV Commercial EV Charger Installers",
             "Interactive map of every OZEV-authorised commercial & fleet EV charger installer in the UK. Click a pin for details and to shortlist.",
             url, LEAFLET_HEAD)
        + navbar()
        + """<div class="wrap crumb"><a href="/">Directory</a> › Map</div>
<section style="padding-top:8px"><div class="wrap">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">UK installer map</h1>
<p class="lead" style="margin-top:14px">Every OZEV-authorised commercial installer in
the directory, mapped. Click a pin for details and to add to your shortlist.</p>
<div id="map"></div>
<p class="note">Map data © OpenStreetMap contributors. Pin positions are approximate
(based on installer-supplied postcodes).</p>
</div></section>""" + footer() + SHORTLIST_JS + LEAFLET_JS
        + '<script src="/map-data.js"></script><script>'
        + """(function(){if(!window.L){return;}
var m=L.map('map',{scrollWheelZoom:false}).setView([54.5,-3.0],6);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
{maxZoom:18,attribution:'&copy; OpenStreetMap'}).addTo(m);
var D=window.__MAP||{},layer;
try{layer=L.markerClusterGroup({chunkedLoading:true});}
catch(e){layer=L.layerGroup();}
Object.keys(D).forEach(function(s){var d=D[s];
var mk=L.marker([d[0],d[1]]);
mk.bindPopup('<strong>'+d[2]+'</strong><br>'+(d[3]||'')+
'<br><a href="/installers/'+s+'/">View details &rarr;</a><br>'+
'<button class="sl-btn" data-sl="'+s+'" type="button">+ Shortlist</button>');
layer.addLayer(mk);});
m.addLayer(layer);
m.on('popupopen',function(){window.SL.render();});})();
</script></body></html>"""
    )


def page_data_landscape(installers, stats):
    url = f"{BASE_URL}/data/uk-ev-installer-landscape/"
    g = stats["growth"]
    growth_line = ""
    if g["added"] is not None:
        growth_line = (f'<p><strong>Latest refresh ({esc(g.get("date") or TODAY)}):'
                       f'</strong> +{g["added"]} added, −{g["removed"] or 0} removed '
                       f'since the previous update. The dataset rebuilds weekly.</p>')
    region_rows = [(r, c) for r, c in stats["regions"]]
    dens_rows = [(r, v) for r, v in stats["density"]]
    top_rows = "".join(
        f"<tr><td>{esc(t)}</td><td>{c}</td></tr>" for t, c in stats["top_towns"])
    citation = (f"{SITE_NAME}. UK commercial EV charger installer landscape, "
                f"{TODAY}. Derived from GOV.UK OZEV data under the Open "
                f"Government Licence v3.0. {url}")
    jl = {"@context": "https://schema.org", "@type": "Dataset",
          "name": "UK commercial EV charger installer landscape",
          "description": "Counts and density of OZEV-authorised commercial EV "
                         "charger installers across the UK, by region and town.",
          "license": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
          "creator": {"@type": "Organization", "name": SITE_NAME},
          "temporalCoverage": TODAY, "url": url,
          "isAccessibleForFree": True}
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>"
              + breadcrumb_jsonld([("Directory", "/"),
                                   ("Data", "/data/uk-ev-installer-landscape/")]))
    return (
        head("The State of UK Commercial EV Charging Installers (2026 Data)",
             f"How many OZEV-authorised commercial EV charger installers are in the UK and where: {stats['total']} installers across {len(stats['regions'])} regions, density per capita, best-served and underserved areas. Free, OGL-licensed data.",
             url, jsonld)
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> › Data</div>
<section style="padding-top:8px"><div class="wrap prose">
<h1>The state of UK commercial EV charging installers</h1>
<p class="upd">Updated {TODAY} · derived from official GOV.UK / OZEV data (OGL v3.0)</p>
<p>This is the picture the official OZEV tool doesn't give you: how many
authorised <strong>commercial &amp; fleet</strong> EV charger installers operate
in the UK, and how unevenly they're spread. {growth_line}</p>
<div class="statgrid">
<div class="statbox"><b>{stats['total']}</b><span>OZEV commercial installers</span></div>
<div class="statbox"><b>{len(stats['regions'])}</b><span>UK regions covered</span></div>
<div class="statbox"><b>{stats['towns_covered']}</b><span>towns with ≥1 installer</span></div>
<div class="statbox"><b>{stats['web_pct']}%</b><span>have a working website</span></div></div>
<h2>Installers by region</h2>
<div class="bars">{svg_bar(region_rows)}</div>
<h2>Installers per million people (the real coverage picture)</h2>
<p>Raw counts favour big regions. Per-capita density shows where commercial EV
buyers actually have the least choice — the “installer deserts”.</p>
<div class="bars">{svg_bar(dens_rows, unit="")}</div>
<h2>Best-served towns</h2>
<table><tr><th>Town</th><th>OZEV commercial installers</th></tr>{top_rows}</table>
<p>{stats['single_towns']} towns have only a single listed installer — thin
coverage where buyer choice is limited. {stats['also_res_pct']}% of commercial
installers also offer residential work.</p>
<div class="cite">Free to reuse with attribution (data under the Open Government
Licence v3.0). Suggested citation:<code>{esc(citation)}</code></div>
<div class="cta-row"><a class="btn btn-g" href="/#directory">Browse the directory</a>
<a class="btn btn-o" style="border-color:#cfd6df;color:#0a0a0a" href="/methodology/">How this data is built</a></div>
</div></section>""" + footer() + SHORTLIST_JS + "</body></html>"
    )


def page_project_pack():
    url = f"{BASE_URL}/project-pack/"
    return (
        head("Your EV charging project pack (printable RFQ)",
             "Turn your calculator estimate and shortlist into a printable request-for-quote brief to send to installers.",
             url, "", noindex=True)
        + navbar()
        + """<div class="wrap crumb"><a href="/">Directory</a> › Project pack</div>
<section style="padding-top:8px"><div class="wrap">
<div class="no-print" style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px">
<button class="btn btn-g" onclick="window.print()" type="button">Print / Save as PDF</button>
<a class="btn btn-d" href="/calculator/">Edit on the calculator</a>
<a class="btn btn-d" href="/shortlist/">Edit shortlist</a></div>
<div id="pp-empty" class="prose" style="display:none"><p class="muted">Nothing to
build a pack from yet. Use the <a style="color:var(--green-d)" href="/calculator/">cost
calculator</a> and <a style="color:var(--green-d)" href="/#directory">shortlist a few
installers</a> first — your project pack assembles automatically from this device.</p></div>
<div class="pp-sheet" id="pp">
<h1 style="font-size:26px;font-weight:800;letter-spacing:-1px">EV charging — request for quotation</h1>
<p class="note" id="pp-date"></p>
<div class="pp-grid">
<div><b>Your company</b><input class="pp-ed" id="ed-co" placeholder="Company name"></div>
<div><b>Contact</b><input class="pp-ed" id="ed-ct" placeholder="Name / email"></div>
<div><b>Quotes due by</b><input class="pp-ed" id="ed-due" placeholder="e.g. in 2 weeks"></div>
<div><b>Notes</b><input class="pp-ed" id="ed-nt" placeholder="Anything else"></div></div>
<h2 style="font-size:18px;margin:24px 0 8px">Project specification</h2>
<div class="pp-grid" id="pp-spec"></div>
<h2 style="font-size:18px;margin:24px 0 8px">Shortlisted installers</h2>
<div id="pp-firms"></div>
<h2 style="font-size:18px;margin:24px 0 8px">Questions to ask every installer</h2>
<ol class="pp-q">
<li>Itemised fixed quote, or day-rate? What's included/excluded?</li>
<li>Is the DNO / grid-connection application included, and who manages it?</li>
<li>Who applies for the Workplace Charging Scheme and EV Infrastructure Grant?</li>
<li>Load management and headroom for future expansion?</li>
<li>Warranty, SLA and fault response time?</li>
<li>Back-office/charge-point software cost and contract length?</li>
<li>OZEV authorisation reference and recent comparable installs?</li>
<li>Site survey lead time and overall programme?</li>
<li>Ownership model — capex, or charging-as-a-service?</li></ol>
<p class="note">Indicative project brief — not a quote or financial advice.
Built on this device from your calculator inputs and shortlist.</p>
</div></div></section>""" + footer() + SHORTLIST_JS
        + """<script src="/shortlist-data.js"></script><script>
(function(){var P;try{P=JSON.parse(localStorage.getItem('evdir_project'))}catch(e){}
var ids=window.SL.get(),D=window.__SLD||{};
if(!P&&!ids.length){document.getElementById('pp-empty').style.display='';
document.getElementById('pp').style.display='none';return;}
var ctL={fast:'Fast AC 7–22 kW',rapid:'Rapid DC 50–100 kW',ultra:'Ultra-rapid 100 kW+'};
var stL={wp:'Workplace car park',depot:'Fleet depot',dest:'Destination / customer'};
function m(n){return '£'+Math.round(n).toLocaleString('en-GB');}
document.getElementById('pp-date').textContent='Prepared '+(new Date().toLocaleDateString('en-GB'))+
(P&&P.ts?' · estimate dated '+P.ts:'');
if(P){var g=[['Site postcode',P.pc||'—'],['Sockets',P.sk],
['Charger type',ctL[P.ct]||P.ct],['Site type',stL[P.st]||P.st],
['Indicative install (before grant)',m(P.lo)+' – '+m(P.hi)],
['WCS grant assumption',P.gr=='1'?(P.rate+'/socket × '+P.sock):'not applied'],
['Indicative net cost',m(P.nlo)+' – '+m(P.nhi)]];
document.getElementById('pp-spec').innerHTML=g.map(function(x){
return '<div><b>'+x[0]+'</b>'+x[1]+'</div>';}).join('');}
else{document.getElementById('pp-spec').innerHTML='<div><b>Spec</b>Open the calculator to add your project spec</div>';}
var fb=document.getElementById('pp-firms');
if(ids.length){fb.innerHTML='<table><tr><th>Installer</th><th>Area</th><th>Listing</th></tr>'+
ids.map(function(s){var d=D[s];if(!d)return '';
return '<tr><td>'+d.n+'</td><td>'+(d.t||'')+(d.r?', '+d.r:'')+
'</td><td>'+location.origin+'/installers/'+s+'/</td></tr>';}).join('')+'</table>';}
else{fb.innerHTML='<p class=muted>No installers shortlisted yet — add some from the directory.</p>';}
['co','ct','due','nt'].forEach(function(k){var el=document.getElementById('ed-'+k);
if(P&&P['f_'+k])el.value=P['f_'+k];
el.addEventListener('input',function(){var Q;try{Q=JSON.parse(localStorage.getItem('evdir_project'))||{}}catch(e){Q={}}
Q['f_'+k]=el.value;localStorage.setItem('evdir_project',JSON.stringify(Q));});});
})();
</script></body></html>"""
    )


GUIDES = {
    "ev-charging-for-fleets": {
        "title": "EV Charging for Fleets: The 2026 Buyer's Guide",
        "desc": "How UK businesses specify, cost and grant-fund depot, workplace and fleet EV charging — with real price ranges and how to choose an OZEV installer.",
        "faqs": [
            ("How much does commercial EV charging cost?",
             "Indicatively: fast AC 7–22kW units £1,200–£3,000 each installed for "
             "basic workplace; rapid 50–100kW DC £12,000–£35,000; ultra-rapid "
             "100kW+ £35,000–£80,000; plus civils and possible DNO/grid upgrade "
             "(£4,500–£50,000+ at higher power). Use the calculator for a range."),
            ("Depot, workplace or destination — what's the difference?",
             "Depot: vehicles return to base, overnight smart-charging with load "
             "balancing is cheapest. Workplace: staff/visitor parking, WCS-eligible. "
             "Destination: customer dwell-time charging, often part-public."),
            ("Do I need a DNO application?",
             "For anything beyond a few fast chargers, usually yes. A good "
             "installer scopes the grid connection early — it's the item that "
             "most often blows budgets if discovered late."),
        ],
        "body": """
<h2>Why fleet charging is its own discipline</h2>
<p>Charging a fleet is not "home chargers, but more of them". Depot and workplace
sites hit grid-capacity limits and need load management, back-office software and
phased civils. The installer you pick has to think in diversity factors and DNO
applications, not single sockets.</p>
<h2>Indicative costs (UK, 2026)</h2>
<table><tr><th>Item</th><th>Typical range</th></tr>
<tr><td>Fast AC 7–22 kW (per socket, installed, basic workplace)</td><td>£1,200 – £3,000</td></tr>
<tr><td>Rapid DC 50–100 kW (per unit)</td><td>£12,000 – £35,000</td></tr>
<tr><td>Ultra-rapid 100 kW+ (per unit)</td><td>£35,000 – £80,000</td></tr>
<tr><td>Groundworks / civils (per site)</td><td>£600 – £9,000</td></tr>
<tr><td>DNO / grid supply upgrade</td><td>£4,500 – £50,000+</td></tr>
<tr><td>Charge-point management software</td><td>£10 – £50 / charger / month</td></tr></table>
<p><a style="color:var(--green-d)" href="/calculator/">Estimate your project →</a>
Ranges only — itemised quotes always vary by site.</p>
<h2>The three site types</h2>
<ul><li><strong>Depot charging</strong> — vehicles return to base; overnight smart
charging with load balancing is usually the cheapest route.</li>
<li><strong>Workplace charging</strong> — staff and visitor vehicles; eligible for the
Workplace Charging Scheme voucher.</li>
<li><strong>Destination / fleet-in-the-field</strong> — customer dwell-time or public
network reliance; the installer's job is the depot survey plus tariff strategy.</li></ul>
<h2>What to ask an installer before you sign</h2>
<ul><li>Have they done a DNO (grid) application for a site this size before?</li>
<li>Is load management included, or bolted on later at cost?</li>
<li>Who owns the charge-point management software and data?</li>
<li>Is the quote OZEV-grant-aware (WCS <em>and</em> Infrastructure Grant applied)?</li></ul>
<div class="box"><strong>Use the directory:</strong> every installer here is
OZEV-authorised for commercial work. Shortlist three, get comparable quotes.
<a style="color:var(--green-d)" href="/#directory">Open the directory →</a></div>
""",
    },
    "workplace-charging-scheme": {
        "title": "The Workplace Charging Scheme (WCS) Explained — 2026",
        "desc": "OZEV Workplace Charging Scheme: up to £500/socket from 1 April 2026, 75% cap, 40-socket limit, scheme ends 31 March 2027. Eligibility and how to claim.",
        "faqs": [
            ("How much is the Workplace Charging Scheme worth?",
             "Up to £350 per socket until 31 March 2026, then up to £500 per "
             "socket from 1 April 2026 — covering a maximum of 75% of total "
             "purchase and installation cost, capped at 40 sockets per applicant."),
            ("When does the Workplace Charging Scheme end?",
             "The scheme is currently funded to 31 March 2027. Rates improve on "
             "1 April 2026, so there is no cost penalty to acting sooner."),
            ("Who is eligible for the WCS?",
             "UK-registered businesses, charities and public-sector bodies with "
             "dedicated off-street parking for staff or fleet, where installation "
             "is by an OZEV-authorised installer. You must own the site or have "
             "landlord consent."),
            ("Do I apply for the grant myself?",
             "You apply online for a voucher code and give it to your "
             "OZEV-authorised installer, who redeems it and discounts your "
             "invoice. The grant never touches your bank account."),
        ],
        "body": """
<h2>What the WCS is</h2>
<p>The Workplace Charging Scheme is an OZEV voucher that cuts the upfront cost of
buying and installing EV chargepoint sockets at a place of work. It is claimed
<em>through an OZEV-authorised installer</em> — you don't receive cash yourself.</p>
<h2>What it's worth (and the 1 April 2026 change)</h2>
<table><tr><th></th><th>Until 31 Mar 2026</th><th>From 1 Apr 2026</th></tr>
<tr><td>Per socket</td><td>up to £350</td><td>up to £500</td></tr>
<tr><td>Max % of total cost</td><td>75%</td><td>75%</td></tr>
<tr><td>Max sockets / applicant</td><td>40</td><td>40</td></tr>
<tr><td>Scheme end date</td><td colspan="2">31 March 2027</td></tr></table>
<p>The rate <em>rises</em> in April 2026, so quoting now and scheduling around the
change can be worth real money. <a style="color:var(--green-d)" href="/calculator/">Model it →</a></p>
<h2>Who is eligible</h2>
<ul><li>UK-registered businesses, charities and public-sector organisations.</li>
<li>Dedicated off-street parking for staff or fleet (not customer parking).</li>
<li>You own the property or have landlord consent.</li>
<li>Installation by an OZEV-authorised installer.</li></ul>
<h2>How the claim works</h2>
<ul><li>Apply online for a voucher → receive a code.</li>
<li>Give the code to your chosen OZEV-authorised installer.</li>
<li>They redeem it and discount your invoice directly.</li></ul>
<div class="box">Shortlist OZEV-authorised installers in the
<a style="color:var(--green-d)" href="/#directory">directory</a> and ask each to
quote <em>with the WCS applied</em> so you compare like for like.</div>
""",
    },
    "ev-infrastructure-grant": {
        "title": "EV Infrastructure Grant for Staff & Fleets — Explained (2026)",
        "desc": "The OZEV EV Infrastructure Grant for staff and fleet car parks: what it funds (cabling, groundworks, DNO supply), eligibility, and how it stacks with the WCS.",
        "faqs": [
            ("What does the EV Infrastructure Grant cover?",
             "The supporting infrastructure — cabling, groundworks, and capacity/"
             "DNO supply upgrades — needed for current and future chargepoints at "
             "staff and fleet car parks. It is the grant aimed at the expensive "
             "civils, not the chargers themselves."),
            ("Can it be combined with the Workplace Charging Scheme?",
             "Yes. The Infrastructure Grant is explicitly designed to be used "
             "alongside the WCS — one funds the groundworks, the other the "
             "sockets. A good installer applies both."),
        ],
        "body": """
<h2>What it funds</h2>
<p>The EV Infrastructure Grant helps businesses with the <em>supporting</em>
infrastructure — cabling, groundworks and capacity upgrades — for current and
future chargepoints at staff and fleet car parks. It is meant to be used
alongside the Workplace Charging Scheme, not instead of it.</p>
<h2>Why it matters</h2>
<p>On most commercial sites the expensive part isn't the chargers — it's the
trenching, the new supply and the DNO works. This grant attacks exactly that
cost, which is why fleet projects that looked unaffordable often aren't once it's
applied correctly. See the cost table in the
<a style="color:var(--green-d)" href="/guides/ev-charging-for-fleets/">fleet guide</a>.</p>
<h2>Eligibility in brief</h2>
<ul><li>Small-to-medium businesses with eligible staff/fleet parking.</li>
<li>Work delivered by an OZEV-authorised installer.</li>
<li>Infrastructure must support a minimum number of sockets/parking bays.</li></ul>
<div class="box">The installer applies the grant for you. Pick OZEV-authorised
installers from the <a style="color:var(--green-d)" href="/#directory">directory</a>
and ask specifically whether they're applying the Infrastructure Grant <em>and</em> WCS.</div>
""",
    },
    "grant-deadlines": {
        "title": "UK EV Charging Grant Deadlines & Rate Changes (2026–2027)",
        "desc": "Every live UK EV charging grant deadline and rate change on one page: the 1 April 2026 WCS uplift to £500/socket and the 31 March 2027 scheme end date.",
        "faqs": [
            ("What is the most important upcoming EV grant date?",
             "1 April 2026: the Workplace Charging Scheme per-socket contribution "
             "rises from up to £350 to up to £500. The scheme is funded to "
             "31 March 2027."),
            ("Should I wait until April 2026 for the higher rate?",
             "Not necessarily — quote now, and your installer can schedule around "
             "the change. Waiting risks installer capacity and grid lead times; "
             "the rate change can often be captured without delaying the project."),
        ],
        "body": """
<h2>Why this page exists</h2>
<p>Grant rates and end-dates move, and missing a change can cost a fleet project
thousands. This tracks the live position.</p>
<h2>Current position</h2>
<table><tr><th>Scheme</th><th>Status / key dates</th></tr>
<tr><td>Workplace Charging Scheme</td><td>Open. Up to £350/socket → <strong>up to
£500/socket from 1 Apr 2026</strong>. ≤75% of cost, max 40 sockets. <strong>Scheme
ends 31 Mar 2027.</strong></td></tr>
<tr><td>EV Infrastructure Grant (staff &amp; fleets)</td><td>Open; designed to run
alongside the WCS for supporting infrastructure.</td></tr>
<tr><td>Chargepoint grant — flats/landlords</td><td>Open; separate scheme, relevant
if your fleet includes employee home charging.</td></tr></table>
<div class="disc">Maintained for general guidance — not financial or legal advice.
Always confirm current rates on GOV.UK and with your OZEV-authorised installer
before you commit.</div>
<h2>What to do about it</h2>
<p>If a project is viable at today's rates, the deadlines are a reason to move.
<a style="color:var(--green-d)" href="/calculator/">Estimate cost + grant →</a> then
<a style="color:var(--green-d)" href="/#directory">shortlist installers →</a></p>
""",
    },
}


def page_guide(slug, g):
    url = f"{BASE_URL}/guides/{slug}/"
    faqs = g.get("faqs", [])
    jl = {"@context": "https://schema.org", "@type": "Article",
          "headline": g["title"], "description": g["desc"],
          "datePublished": "2026-05-18", "dateModified": TODAY,
          "author": {"@type": "Organization", "name": SITE_NAME}}
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>"
              + breadcrumb_jsonld([("Directory", "/"), ("Guides", "/#directory"),
                                   (g["title"], f"/guides/{slug}/")])
              + (faq_jsonld(faqs) if faqs else ""))
    aff = """
<h2 style="color:#fff">Hardware &amp; partner options</h2>
<p style="color:#9aa1ab">Independent of the directory listings. We may earn a
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
{g['body']}
{faq_html(faqs) if faqs else ''}
<div class="cta-row"><a class="btn btn-g" href="/calculator/">Grant + cost calculator</a>
<a class="btn btn-o" style="border-color:#cfd6df;color:#0a0a0a" href="/#directory">Browse installers</a></div>
</div></section>
<section class="sec-d"><div class="wrap">{aff}</div></section>"""
        + footer() + SHORTLIST_JS + "</body></html>"
    )


def page_simple(title, desc, slug, body_html, noindex=False):
    url = f"{BASE_URL}/{slug}/"
    return (head(title, desc, url, "", noindex) + navbar()
            + f'<section style="padding-top:30px"><div class="wrap prose"><h1>{esc(title)}</h1>{body_html}</div></section>'
            + footer() + SHORTLIST_JS + "</body></html>")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    src = DATA / "installers.json"
    if not src.exists():
        print("[generate] data/installers.json missing — run pipeline/extract.py first")
        return 1
    payload = json.loads(src.read_text(encoding="utf-8"))
    installers = normalize(payload["installers"])
    print(f"[generate] {len(installers)} installers (normalized)")

    # Contact-channel guard: a directory that republishes third-party (and some
    # personal) data MUST have a working removal channel. If a real base URL is
    # configured (i.e. we're deploying) but the contact email is still the
    # placeholder, refuse to build.
    placeholder = CONTACT_EMAIL.endswith("example.com")
    deploying = BASE_URL != DEFAULT_BASE
    if placeholder and deploying:
        print("[generate] FATAL: SITE_CONTACT_EMAIL is still a placeholder but "
              "SITE_BASE_URL is set for deploy. A real removal channel is "
              "legally required. Set SITE_CONTACT_EMAIL and rebuild.")
        return 1
    if placeholder:
        print("[generate] WARNING: contact email is a placeholder — fine for "
              "local preview, MUST be set before deploy (see deploy.md).")

    # Rewrite the public JSON with only publication-safe emails; dump the full
    # raw contacts to a git-ignored private file for the operator only.
    safe = []
    for i in installers:
        c = {k: v for k, v in i.items() if not k.startswith("_")
             and k not in ("email_raw", "phone_primary")}
        safe.append(c)
    payload["installers"] = safe
    payload["count"] = len(safe)
    src.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    with (DATA / "contacts_private.csv").open("w", newline="",
                                              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Name", "Town", "Region", "Postcode", "Website",
                    "Phone (raw)", "Email (raw)", "Slug"])
        for i in installers:
            w.writerow([i["name"], i.get("town"), i.get("region"),
                        i.get("postcode"), i.get("website"),
                        i.get("phone"), i.get("email_raw"), i["_slug"]])

    by_slug = {i["_slug"]: i for i in installers}
    towns = build_towns(installers)

    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
    if DIST.exists():
        for ch in DIST.iterdir():
            shutil.rmtree(ch, ignore_errors=True) if ch.is_dir() else ch.unlink()
    DIST.mkdir(parents=True, exist_ok=True)

    stats = build_stats(installers)
    urls = ["/", "/calculator/", "/map/", "/data/uk-ev-installer-landscape/",
            "/about/", "/contact/", "/privacy/", "/methodology/"]
    write(DIST / "index.html", page_index(installers))
    write(DIST / "calculator" / "index.html", page_calculator())
    write(DIST / "map" / "index.html", page_map())
    write(DIST / "map-data.js", map_data_js(installers))
    write(DIST / "data" / "uk-ev-installer-landscape" / "index.html",
          page_data_landscape(installers, stats))
    write(DIST / "shortlist" / "index.html", page_shortlist())
    write(DIST / "project-pack" / "index.html", page_project_pack())
    # tiny lookup so the shortlist page can show names without shipping all data
    sld = {i["_slug"]: {"n": i["name"], "t": i.get("town", ""),
                        "r": i.get("region", "")} for i in installers}
    write(DIST / "shortlist-data.js",
          "window.__SLD=" + json.dumps(sld, ensure_ascii=False) + ";")

    for inst in installers:
        write(DIST / "installers" / inst["_slug"] / "index.html",
              page_installer(inst, by_slug, installers))
        urls.append(f"/installers/{inst['_slug']}/")

    for region in sorted({i["region"] for i in installers
                          if i["region"] != "N/A"}):
        write(DIST / "regions" / slugify(region) / "index.html",
              page_region(region, installers))
        urls.append(f"/regions/{slugify(region)}/")

    for tslug, t in towns.items():
        write(DIST / "towns" / tslug / "index.html", page_town(tslug, t))
        urls.append(f"/towns/{tslug}/")

    for slug, g in GUIDES.items():
        write(DIST / "guides" / slug / "index.html", page_guide(slug, g))
        urls.append(f"/guides/{slug}/")

    write(DIST / "about" / "index.html", page_simple(
        "About & Affiliate Disclosure",
        "How this directory is built, our data source, and our affiliate disclosure.",
        "about",
        f"""<p>{esc(SITE_NAME)} is an independent directory. Listings are compiled
from the public GOV.UK OZEV authorised-installer tool under the Open Government
Licence v3.0. We are not affiliated with OZEV, GOV.UK or any installer.</p>
<h2>How listings are ordered</h2><p>Alphabetically, with clearly-labelled featured
partners shown first. Whether an installer appears, and where, is never sold or
influenced by outbound/affiliate links.</p>
<h2>Affiliate disclosure</h2><p>Some outbound links to hardware or service partners
may be affiliate links — we may earn a referral fee at no cost to you. This is
disclosed on the relevant pages and never affects listing inclusion or order.</p>
<h2>Data &amp; corrections</h2><p>See our <a style="color:var(--green-d)"
href="/privacy/">privacy &amp; data page</a>. Installers can request a correction
or removal via the <a style="color:var(--green-d)" href="/contact/">contact page</a>.</p>"""))

    write(DIST / "privacy" / "index.html", page_simple(
        "Privacy & Data", "How this directory sources data, lawful basis, and how to request removal.",
        "privacy",
        f"""<p>This site republishes business listing information from the public
GOV.UK OZEV authorised-installer tool (Open Government Licence v3.0) so buyers can
find OZEV-authorised commercial installers — a public-interest aggregation the
official tool does not provide in browsable form.</p>
<h2>Personal data</h2><p>We deliberately do <strong>not</strong> publish scraped
personal (firstname.lastname) or free-webmail email addresses as clickable links.
Where only such an address exists, we show a “request a quote” route instead.</p>
<h2>Lawful basis</h2><p>Legitimate interests (helping businesses find authorised
installers; helping installers receive relevant enquiries), balanced against the
limited, already-public nature of the data.</p>
<h2>Removal &amp; correction</h2><p>Any installer can have their listing corrected
or removed, no questions asked, via <a style="color:var(--green-d)"
href="/contact/">the contact page</a>. Requests are actioned on the next rebuild.</p>"""))

    write(DIST / "methodology" / "index.html", page_simple(
        "Methodology & Data Transparency",
        "Exactly how this OZEV commercial EV installer dataset is built, refreshed, deduplicated and licensed.",
        "methodology",
        f"""<p>Transparency about how the numbers on the
<a style="color:var(--green-d)" href="/data/uk-ev-installer-landscape/">data page</a>
and directory are produced.</p>
<h2>Source</h2><p>The public GOV.UK “find an EV chargepoint installer” / OZEV
authorised-installer tool, reused under the Open Government Licence v3.0.</p>
<h2>Collection</h2><p>The tool is queried across a UK-wide postcode grid; only
installers offering <strong>commercial</strong> work are kept. Requests are
rate-limited and polite. Re-run automatically every week.</p>
<h2>Deduplication</h2><p>Records are de-duplicated on a normalised
name + postcode key; collision-safe page slugs are assigned at build.</p>
<h2>What we deliberately exclude</h2><p>Scraped personal (firstname.lastname)
and free-webmail email addresses are not published as links — a privacy choice,
documented on the <a style="color:var(--green-d)" href="/privacy/">privacy page</a>.</p>
<h2>Accuracy</h2><p>Fields that aren't in the source are shown as “Not listed”,
never guessed. Data reflects the source on the last refresh date shown; always
confirm with the installer before contracting.</p>
<h2>Reuse</h2><p>The derived statistics are free to reuse with attribution under
the OGL v3.0. A suggested citation is on the
<a style="color:var(--green-d)" href="/data/uk-ev-installer-landscape/">data page</a>.</p>"""))

    write(DIST / "contact" / "index.html", page_simple(
        "Contact / Request a Correction",
        "Contact the directory to correct or remove a listing.",
        "contact",
        (f"""<p>To correct or remove a listing, or for partnership enquiries, email
<a style="color:var(--green-d)" href="mailto:{esc(CONTACT_EMAIL)}">{esc(CONTACT_EMAIL)}</a>.
Removal requests are actioned on the next rebuild, no questions asked.</p>"""
         + ('<p class="disc">⚠ This is a placeholder address — it must be set via '
            'SITE_CONTACT_EMAIL before going live (see deploy.md).</p>'
            if placeholder else ""))))

    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        if u.startswith(("/shortlist", "/contact", "/project-pack")):
            continue  # noindex/interactive — keep out of sitemap
        pr = ("1.0" if u == "/" else
              "0.9" if u in ("/calculator/", "/map/",
                             "/data/uk-ev-installer-landscape/") else
              "0.8" if u.startswith(("/guides", "/towns")) else "0.6")
        sm.append(f"<url><loc>{BASE_URL}{u}</loc><lastmod>{now}</lastmod>"
                  f"<priority>{pr}</priority></url>")
    sm.append("</urlset>")
    write(DIST / "sitemap.xml", "\n".join(sm))
    write(DIST / "robots.txt",
          f"User-agent: *\nAllow: /\nDisallow: /shortlist/\n"
          f"Disallow: /project-pack/\n"
          f"Sitemap: {BASE_URL}/sitemap.xml\n")
    write(DIST / "404.html",
          head("Not found", "Page not found", BASE_URL + "/404", noindex=True)
          + navbar() + '<section style="padding:80px 0"><div class="wrap prose">'
          '<h1>Page not found</h1><p><a style="color:var(--green-d)" href="/">'
          'Back to the directory →</a></p></div></section>' + footer()
          + "</body></html>")

    print(f"[generate] DONE — {len(urls)} pages, {len(towns)} town pages → {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
