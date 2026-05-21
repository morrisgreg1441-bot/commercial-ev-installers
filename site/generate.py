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


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _safe_mean(items, key):
    vals = []
    for i in items:
        try:
            vals.append(float(i[key]))
        except (TypeError, ValueError, KeyError):
            pass
    return round(sum(vals) / len(vals), 5) if vals else None


def _haversine_mi(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return float("inf")
    r = 3958.7613  # mean Earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


# Town grouping (>= TOWN_MIN installers) + computed enrichment fields.
# Every value below is derived from data/installers.json; no fabrication.
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

    # Pre-compute enrichment fields used by page_town().
    region_installer_totals: dict[str, int] = {}
    for i in installers:
        r = i.get("region")
        if r and r != "N/A":
            region_installer_totals[r] = region_installer_totals.get(r, 0) + 1
    by_region: dict[str, list] = {}
    for slug, t in towns.items():
        by_region.setdefault(t["region"], []).append((slug, len(t["items"])))
    region_rank = {}
    for r, lst in by_region.items():
        lst.sort(key=lambda x: -x[1])
        for idx, (slug, _) in enumerate(lst, 1):
            region_rank[slug] = idx
    national = sorted(towns.items(), key=lambda kv: -len(kv[1]["items"]))
    nat_rank = {slug: idx for idx, (slug, _) in enumerate(national, 1)}
    qual_in_region = {r: len(lst) for r, lst in by_region.items()}

    for slug, t in towns.items():
        items = t["items"]
        n = len(items)
        n_res = sum(1 for i in items if "Residential" in i.get("services", []))
        n_web = sum(1 for i in items
                    if i.get("website") not in ("N/A", None, ""))
        pc_areas = {}
        for i in items:
            pc = (i.get("postcode") or "").strip()
            m = re.match(r"^([A-Z]+)", pc.upper())
            if m:
                pc_areas[m.group(1)] = pc_areas.get(m.group(1), 0) + 1
        dom_area = max(pc_areas, key=pc_areas.get) if pc_areas else None
        rt = region_installer_totals.get(t["region"], n)
        t.update({
            "count": n,
            "n_residential": n_res,
            "n_commercial_only": n - n_res,
            "n_with_web": n_web,
            "pct_residential": n_res / n,
            "pct_with_web": n_web / n,
            "region_rank": region_rank[slug],
            "national_rank": nat_rank[slug],
            "region_total_installers": rt,
            "share_of_region": n / max(rt, 1),
            "qual_towns_in_region": qual_in_region.get(t["region"], 1),
            "postcode_area": dom_area,
            "lat_centre": _safe_mean(items, "lat"),
            "lon_centre": _safe_mean(items, "lon"),
        })

    # Nearest hubs cross-link (computed AFTER lat_centres are set on every town).
    for slug, t in towns.items():
        if t["lat_centre"] is None:
            t["nearest_hubs"] = []
            continue
        cands = []
        for o_slug, o in towns.items():
            if o_slug == slug or o["lat_centre"] is None:
                continue
            d = _haversine_mi(t["lat_centre"], t["lon_centre"],
                              o["lat_centre"], o["lon_centre"])
            if d <= 100:
                cands.append((d, o_slug, o))
        cands.sort(key=lambda x: x[0])
        t["nearest_hubs"] = [
            {"slug": s, "town": o["town"], "region": o["region"],
             "count": o["count"], "miles": round(d)}
            for d, s, o in cands[:3]
        ]
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

# Cloudflare Web Analytics — privacy-first, no cookies, one tiny beacon. The
# only third-party script on the site. Token is per-site and PUBLIC.
CFWA_BEACON = (
    '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
    'data-cf-beacon=\'{"token": "3e86387c426449cb8de25c0861a97e68"}\'></script>'
)

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
{FAVICON}{FONT}{CFWA_BEACON}<style>{CSS}</style>{jsonld}</head><body>"""


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
<a href="/guides/grant-deadlines/">Grant deadlines</a>
<a href="/glossary/">Glossary (UK EV charging terms)</a>
<a href="/methodology/">Methodology &amp; data</a></div>
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
        + f"""<aside style="background:#fff7d6;border-bottom:1px solid #f1e6a8;
color:#3a2f00;font-size:14px;text-align:center;padding:10px 16px">
<strong>New:</strong>
<a style="color:#15803d;font-weight:700;text-decoration:underline"
   href="/data/{SNAPSHOT_SLUG}/">May 2026 UK Installer Landscape — open data
   snapshot</a> ({n} installers, regional + postcode-area breakdown, OGL v3.0).
</aside>
<section class="hero"><div class="wrap">
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
<div class="stat"><b>£500</b><span>WCS grant / socket (since Apr 2026)</span></div>
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
<p>£500/socket since 1 Apr 2026 (was £350), 75% cap, 40-socket limit, ends 31 Mar 2027.</p></a>
<a class="gcard" href="/guides/ev-infrastructure-grant/"><h3>EV Infrastructure Grant</h3>
<p>Closed to new applicants 31 Mar 2026 — the Depot Charging Scheme is the 2026 replacement.</p></a>
<a class="gcard" href="/guides/grant-deadlines/"><h3>Grant deadlines</h3>
<p>Every live deadline and rate change on one page.</p></a>
<a class="gcard" href="/tools/uk-ev-grant-eligibility/"><h3>Grant eligibility wizard</h3>
<p>Answer 6 quick questions — see which UK 2026 grant(s) you qualify for.</p></a>
<a class="gcard" href="/tools/ev-charger-cost-calculator/"><h3>Cost &amp; grant calculator</h3>
<p>Indicative hardware, civils and DNO cost — plus WCS &amp; Depot Charging Scheme — for your project.</p></a>
<a class="gcard" href="/glossary/"><h3>Glossary</h3>
<p>OZEV, WCS, G99, OCPP, CCS2, kVA — every UK commercial EV charging term, defined plainly.</p></a>
</div></div></section>

<section class="sec-l"><div class="wrap">
<h2 class="sh">Find installers by service</h2>
<p class="lead">Same OZEV-authorised pool, four buyer lenses — pick the page
that matches your project type.</p>
<div class="guidegrid" style="margin-top:24px">
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/services/fleet-charging-installers/"><h3 style="color:var(--ink)">Fleet charging installers</h3>
<p style="color:var(--mut)">Vans, HGVs, company cars. WCS + Depot Charging Scheme grant routes.</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/services/workplace-charging-installers/"><h3 style="color:var(--ink)">Workplace charging installers</h3>
<p style="color:var(--mut)">Staff and office car parks. Up to £500/socket under the WCS.</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/services/depot-rapid-charging-installers/"><h3 style="color:var(--ink)">Depot rapid DC installers</h3>
<p style="color:var(--mut)">Logistics, bus and coach depots. 70% Depot Charging Scheme funding.</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/services/public-car-park-ev-installers/"><h3 style="color:var(--ink)">Public car-park installers</h3>
<p style="color:var(--mut)">Retail, hospitality, council. Commercial / charging-as-a-service.</p></a>
</div></div></section>

<section class="sec-l" id="industries"><div class="wrap">
<h2 class="sh">Find installers by industry</h2>
<p class="lead">Same OZEV-authorised pool, viewed through a sector lens —
pick the page that matches who you are buying for.</p>
<div class="guidegrid" style="margin-top:24px">
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/industries/hotels-hospitality/"><h3 style="color:var(--ink)">Hotels &amp; hospitality</h3>
<p style="color:var(--mut)">Destination charging for guest car parks. WCS limits and CaaS realities.</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/industries/logistics-haulage/"><h3 style="color:var(--ink)">Logistics &amp; haulage</h3>
<p style="color:var(--mut)">Fleet depots, HGV charging. Depot Charging Scheme (70%, up to £1m).</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/industries/local-authority-public-sector/"><h3 style="color:var(--ink)">Local authority &amp; public sector</h3>
<p style="color:var(--mut)">LEVI Fund, RM6213 framework, on-street and council car parks.</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/industries/property-management-multi-tenant/"><h3 style="color:var(--ink)">Property &amp; multi-tenant</h3>
<p style="color:var(--mut)">Landlords, MUDs, multi-let estates. Approved Document S (Building Regs Part S).</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/industries/car-dealerships/"><h3 style="color:var(--ink)">Car dealerships</h3>
<p style="color:var(--mut)">Customer test-drive bays + workshop dwell + staff fleet. Brand-spec realities.</p></a>
<a class="gcard" style="background:#fff;border-color:var(--bd-l);color:var(--ink)"
 href="/industries/nhs-healthcare/"><h3 style="color:var(--ink)">NHS &amp; healthcare</h3>
<p style="color:var(--mut)">Greener NHS targets, staff parking, blue-light fleets, hospital resilience.</p></a>
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
         "Workplace Charging Scheme (up to £500/socket, the rate in force since "
         "1 April 2026) and, for fleet depots, the 2026 Depot Charging Scheme "
         "(70% of chargepoint + civil costs, up to £1m per organisation). The "
         "installer applies these for you. The older EV Infrastructure Grant "
         "for Staff and Fleets closed to new applicants on 31 March 2026."),
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
Charging Scheme</a> and <a style="color:var(--green-d)" href="/guides/ev-infrastructure-grant/">Depot
Charging Scheme (which replaced the EV Infrastructure Grant)</a> guides, or run the
<a style="color:var(--green-d)" href="/tools/uk-ev-grant-eligibility/">grant eligibility wizard</a>,
before you commission work.</p>
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


def _town_intro(t: dict) -> str:
    """2-3 sentence intro built from data only. No fabrication — if the data
    says nothing standout, sentence 2 is omitted entirely."""
    n = t["count"]
    s1 = (f"{esc(t['town'])} has {n} OZEV-authorised commercial EV installer"
          f"{'s' if n != 1 else ''}, the {_ordinal(t['region_rank'])}-largest "
          f"concentration in {esc(t['region'])}")
    if t["national_rank"] <= 20:
        s1 += f" and the {_ordinal(t['national_rank'])}-largest in the UK."
    else:
        s1 += "."

    s2 = None
    pct_res, pct_w = t["pct_residential"], t["pct_with_web"]
    if t["share_of_region"] >= 0.20:
        s2 = (f"{esc(t['town'])}'s installers account for "
              f"{round(t['share_of_region']*100)}% of all commercial EV "
              f"installers in {esc(t['region'])}.")
    elif pct_res <= 0.25 and n >= 5:
        s2 = (f"{t['n_commercial_only']} of the {n} list commercial-only work "
              "— an unusually high share; most UK installers also do residential.")
    elif pct_res >= 0.85 and n >= 5:
        s2 = (f"All but {t['n_commercial_only']} also do residential work, "
              "so most are dual-trade rather than fleet specialists.")
    elif pct_w <= 0.40 and n >= 5:
        s2 = (f"Only {t['n_with_web']} of the {n} publish a website — "
              "expect to contact several by phone.")

    pa = t.get("postcode_area")
    s3 = (f"All {n} are listed by their registered office address"
          + (f" in the {pa} postcode area" if pa else "")
          + "; service radius is usually wider — confirm with each installer.")
    return " ".join(p for p in (s1, s2, s3) if p)


def _town_extra_faqs(t: dict) -> list:
    """Extra computed FAQs. Always emits the 'nearest hub' question; emits a
    second standout-specific FAQ only when the data warrants one."""
    out = []
    nh = t.get("nearest_hubs") or []
    if nh:
        n0 = nh[0]
        ans = (f"{esc(n0['town'])}, {esc(n0['region'])} — about {n0['miles']} "
               f"miles away, with {n0['count']} OZEV-authorised commercial "
               f"installers.")
        if n0["miles"] > 50:
            ans += (" Most installers serve a wider radius than their office "
                    f"postcode suggests, so the {esc(t['town'])} list may "
                    "still be your best starting point.")
        out.append((f"What's the nearest other commercial EV installer hub to {esc(t['town'])}?", ans))
    else:
        out.append((f"What's the nearest other commercial EV installer hub to {esc(t['town'])}?",
                    f"There is no other town with three or more listed OZEV "
                    f"commercial installers within 100 miles of {esc(t['town'])}. "
                    f"The full {esc(t['region'])} regional list is your "
                    "next-widest option."))

    n = t["count"]
    if t["share_of_region"] >= 0.20:
        out.append((f"Do {esc(t['town'])}'s installers really cover that much of {esc(t['region'])}?",
                    f"Yes — {round(t['share_of_region']*100)}% of the region's "
                    f"{t['region_total_installers']} listings have a "
                    f"{esc(t['town'])} office address. They typically still "
                    f"travel across {esc(t['region'])}."))
    elif t["pct_residential"] <= 0.25 and n >= 5:
        out.append((f"Why are most installers in {esc(t['town'])} commercial-only?",
                    f"We can't infer the reason from the public OZEV list — only "
                    f"the labels. {t['n_commercial_only']} of {n} have chosen "
                    "not to register for residential work, which is unusual."))
    elif t["pct_with_web"] <= 0.40 and n >= 5:
        out.append((f"Why do so few {esc(t['town'])} installers have websites?",
                    "We don't know — many smaller electrical contractors "
                    f"operate on referrals and phone enquiries. {t['n_with_web']} "
                    f"of {n} listed installers publish a website."))
    return out


def page_town(slug, t):
    town, region, items = t["town"], t["region"], t["items"]
    url = f"{BASE_URL}/towns/{slug}/"
    cards = "".join(card(i) for i in items)

    intro = _town_intro(t)

    # Generic 3 FAQs + computed extras
    faqs = [
        (f"How many OZEV-authorised commercial EV installers are in {esc(town)}?",
         f"This directory lists {t['count']} OZEV-authorised installer"
         f"{'s' if t['count']!=1 else ''} offering commercial or fleet EV "
         f"charging installation in or around {esc(town)}."),
        (f"Is there a grant for commercial EV charging in {esc(town)}?",
         "Yes — the Workplace Charging Scheme (up to £500/socket since 1 April "
         "2026, capped at 75% and 40 sockets per applicant, scheme runs to "
         "31 March 2027) applies UK-wide, including " + esc(town) +
         ". Fleet depots may also qualify for the 2026 Depot Charging Scheme "
         "(70% of chargepoint + civil costs up to £1m per organisation). "
         "Your installer applies them to your quote."),
        ("How do I choose between them?",
         "Shortlist three, then use the “request quotes” flow to ask each for "
         "a like-for-like quote with grants applied."),
    ] + _town_extra_faqs(t)

    # JSON-LD: ItemList + Breadcrumb + FAQPage + Place
    jl_list = {"@context": "https://schema.org", "@type": "ItemList",
               "name": f"Commercial EV charger installers in {town}",
               "numberOfItems": len(items),
               "itemListElement": [
                   {"@type": "ListItem", "position": n + 1,
                    "url": f"{BASE_URL}/installers/{i['_slug']}/",
                    "name": i["name"]} for n, i in enumerate(items[:100])]}
    trail = [("Directory", "/"),
             (region, f"/regions/{slugify(region)}/"),
             (town, f"/towns/{slug}/")]
    place_jl = ""
    if t.get("lat_centre") is not None:
        place_jl = ('<script type="application/ld+json">' + json.dumps({
            "@context": "https://schema.org", "@type": "Place",
            "name": town,
            "address": {"@type": "PostalAddress",
                        "addressLocality": town,
                        "addressRegion": region,
                        "addressCountry": "GB"},
            "geo": {"@type": "GeoCoordinates",
                    "latitude": round(t["lat_centre"], 4),
                    "longitude": round(t["lon_centre"], 4)},
        }) + "</script>")
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl_list)
              + "</script>" + breadcrumb_jsonld(trail) + faq_jsonld(faqs)
              + place_jl)

    # Nearest hubs section
    hubs_html = ""
    if t.get("nearest_hubs"):
        rows = "".join(
            f'<li><a style="color:var(--green-d)" href="/towns/{h["slug"]}/">'
            f'{esc(h["town"])}</a> — {h["miles"]} mi · {esc(h["region"])} · '
            f'{h["count"]} installer{"s" if h["count"]!=1 else ""}</li>'
            for h in t["nearest_hubs"])
        hubs_html = (f'<h2 style="font-size:22px;font-weight:700;letter-spacing:-.4px;margin-top:34px">'
                     f'Nearest other commercial EV installer hubs</h2>'
                     f'<ul style="margin:12px 0 0 22px;line-height:1.7">{rows}</ul>')
    elif t.get("lat_centre") is not None:
        hubs_html = ('<p class="muted" style="margin-top:28px;font-size:13.5px">'
                     'No other town with three or more listed installers within '
                     '100 miles. The regional list is your next-widest option.</p>')

    # Local context
    ctx = (f'<h2 style="font-size:22px;font-weight:700;letter-spacing:-.4px;margin-top:34px">'
           f'Local context</h2><ul style="margin:12px 0 0 22px;line-height:1.7">')
    if t.get("postcode_area"):
        ctx += f"<li>Postcode area: {t['postcode_area']}</li>"
    ctx += (f"<li>{esc(town)}'s share of {esc(region)}: {t['count']} of "
            f"{t['region_total_installers']} "
            f"({round(t['share_of_region']*100)}%), ranked "
            f"{_ordinal(t['region_rank'])} of {t['qual_towns_in_region']} "
            f"qualifying towns</li>")
    ctx += "</ul>"

    # Coverage caveat — trust-building disclosure
    caveat = (f'<div class="box" style="margin-top:32px"><strong>About these '
              f'addresses.</strong> All {t["count"]} installers above are shown '
              f'at their <strong>registered office postcode</strong>, which is '
              f'what OZEV publishes. Most service a wider area — often the '
              f'whole of {esc(region)} and sometimes nationally. Ring or email '
              'two or three to confirm they cover your postcode before requesting '
              'a full quote.</div>')

    return (
        head(f"Commercial EV Charger Installers in {town} — OZEV Authorised",
             f"{t['count']} OZEV-authorised commercial & fleet EV charger installers in {town} ({region}). Compare and request quotes — independent, free.",
             url, jsonld)
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> ›
<a href="/regions/{slugify(region)}/">{esc(region)}</a> › {esc(town)}</div>
<section style="padding-top:8px"><div class="wrap">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">Commercial EV charger installers in {esc(town)}</h1>
<p class="lead" style="margin-top:14px;max-width:760px">{intro}</p>
<div class="grid">{cards}</div>
{caveat}
<div class="prose" style="margin-top:8px;max-width:760px">{ctx}{hubs_html}{faq_html(faqs)}</div>
<div class="cta-row" style="margin-top:22px"><a class="btn btn-g" href="/calculator/">Estimate cost + grant</a>
<a class="btn btn-o" style="border-color:#cfd6df;color:#0a0a0a" href="/#directory">All UK installers</a></div>
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
         "Up to £500 per socket since 1 April 2026 (the previous rate was £350 "
         "per socket up to 31 March 2026), covering up to 75% of total cost, "
         "capped at 40 sockets per applicant. The scheme runs until 31 March 2027."),
        ("Can I claim more than one grant?",
         "The Workplace Charging Scheme covers workplace sockets; the 2026 Depot "
         "Charging Scheme covers fleet-depot chargepoints and civils. They are "
         "not generally stacked on the same sockets — a good installer applies "
         "whichever fits your site type. The older EV Infrastructure Grant for "
         "Staff and Fleets closed to new applicants on 31 March 2026."),
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
             "Free calculator: estimate commercial/fleet EV charger install cost and your Workplace Charging Scheme grant (up to £500/socket, the rate in force since April 2026). Indicative UK ranges.",
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
<option value="ultra">Ultra-rapid 150 kW+</option></select></div>
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
advice. WCS: up to £500/socket since 1 Apr 2026 (was £350/socket up to 31 Mar 2026),
≤75% of cost, max 40 sockets, scheme ends 31 Mar 2027. Always confirm on
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
var band={fast:[1200,3000],rapid:[14000,35000],ultra:[35000,80000]};
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
'<div style=\"margin-top:12px;font-size:12.5px\" class=muted>Plus possible DNO/grid upgrade (a few hundred pounds for a small notification, into £50,000+ for LV reinforcement at higher-power sites) and £10–£50/charger/month for management software. Indicative only.</div>';
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


# ---- May 2026 dated snapshot: a separate, link-bait data-journalism page ----
SNAPSHOT_SLUG = "uk-ev-installer-landscape-may-2026"
SNAPSHOT_TITLE = ("UK OZEV-Authorised Commercial Installer Landscape — "
                  "May 2026 Snapshot")


def _snapshot_compute(installers, towns):
    from collections import Counter
    n = len(installers)
    by_region = Counter(i["region"] for i in installers
                        if i.get("region") not in ("N/A", None, ""))
    by_pc_area: Counter = Counter()
    pc_area_dominant_town: dict[str, Counter] = {}
    for i in installers:
        pc = (i.get("postcode") or "").strip().upper()
        m = re.match(r"^([A-Z]+)", pc)
        if not m:
            continue
        a = m.group(1)
        by_pc_area[a] += 1
        t = i.get("town")
        if t and t not in ("N/A", "", None):
            pc_area_dominant_town.setdefault(a, Counter())[t] += 1
    town_to_slug = {t["town"]: slug for slug, t in towns.items()}
    top_pc = []
    for area, count in by_pc_area.most_common(10):
        link_slug = None
        link_town = None
        if area in pc_area_dominant_town:
            for town, _ in pc_area_dominant_town[area].most_common():
                if town in town_to_slug:
                    link_slug = town_to_slug[town]
                    link_town = town
                    break
        top_pc.append({"area": area, "count": count,
                       "link_slug": link_slug, "link_town": link_town})
    commercial_only = sum(
        1 for i in installers
        if "Commercial" in i.get("services", [])
        and "Residential" not in i.get("services", []))
    commercial_and_res = sum(
        1 for i in installers
        if "Commercial" in i.get("services", [])
        and "Residential" in i.get("services", []))
    region_ranked = sorted(by_region.items(), key=lambda x: -x[1])
    bottom3 = region_ranked[-3:][::-1] if len(region_ranked) >= 3 else region_ranked
    return {
        "total": n,
        "regions_ranked": region_ranked,
        "top_pc_areas": top_pc,
        "bottom_regions": bottom3,
        "commercial_only": commercial_only,
        "commercial_and_res": commercial_and_res,
    }


def _snapshot_svg_table(rows, caption, value_label, label_label="Region"):
    if not rows:
        return ""
    svg = svg_bar(rows)
    svg = svg.replace(
        '<svg ',
        f'<svg aria-hidden="true" focusable="false" aria-label="{esc(caption)}" ', 1)
    body = "".join(
        f"<tr><td>{esc(str(lab))}</td><td>{v}</td></tr>" for lab, v in rows)
    return (
        f'<figure class="bars" role="group" aria-label="{esc(caption)}">'
        f'{svg}'
        f'<figcaption class="sr-fb"><table class="snap-tbl">'
        f'<caption>{esc(caption)}</caption>'
        f'<tr><th>{esc(label_label)}</th><th>{esc(value_label)}</th></tr>'
        f'{body}</table></figcaption></figure>'
    )


def page_data_landscape_snapshot(installers, towns):
    s = _snapshot_compute(installers, towns)
    url = f"{BASE_URL}/data/{SNAPSHOT_SLUG}/"
    json_url = f"{BASE_URL}/data/installers.json"
    csv_url = f"{BASE_URL}/data/installers.csv"
    title = SNAPSHOT_TITLE
    desc = (
        f"May 2026 snapshot: {s['total']} OZEV-authorised commercial EV "
        f"charger installers across the UK, ranked by region and postcode "
        f"area, with coverage-gap analysis. Open data under OGL v3.0."
    )

    region_rows_chart = list(s["regions_ranked"])
    region_table_rows = "".join(
        f'<tr><td><a href="/regions/{slugify(r)}/">{esc(r)}</a></td>'
        f"<td>{c}</td>"
        f"<td>{c / s['total'] * 100:.1f}%</td></tr>"
        for r, c in s["regions_ranked"]
    )
    region_chart_html = _snapshot_svg_table(
        region_rows_chart,
        "Installers per UK region (raw count)",
        "Installers", "Region")

    pc_table_rows = []
    pc_chart_rows = []
    for row in s["top_pc_areas"]:
        a, c = row["area"], row["count"]
        if row["link_slug"]:
            label = (f'<a href="/towns/{row["link_slug"]}/">{esc(a)} — '
                     f'{esc(row["link_town"])}</a>')
        elif row["link_town"]:
            label = f'{esc(a)} — {esc(row["link_town"])}'
        else:
            label = esc(a)
        pc_table_rows.append(f"<tr><td>{label}</td><td>{c}</td></tr>")
        pc_chart_rows.append((a, c))
    pc_chart_html = _snapshot_svg_table(
        pc_chart_rows,
        "Top 10 UK postcode areas by OZEV commercial installer count",
        "Installers", "Postcode area")

    gap_rows = "".join(
        f'<tr><td><a href="/regions/{slugify(r)}/">{esc(r)}</a></td>'
        f"<td>{c}</td></tr>"
        for r, c in s["bottom_regions"]
    )

    ts_rows = [
        ("Commercial only", s["commercial_only"]),
        ("Commercial + Residential", s["commercial_and_res"]),
    ]
    ts_chart_html = _snapshot_svg_table(
        ts_rows,
        "Trading status: commercial-only vs commercial+residential",
        "Installers", "Trading status")

    citation = (
        f"{SITE_NAME}. UK OZEV-Authorised Commercial Installer Landscape — "
        f"May 2026 Snapshot. Published {TODAY}. Derived from the GOV.UK / "
        f"OZEV register under the Open Government Licence v3.0. {url}"
    )

    dataset_jl = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": title, "description": desc,
        "license": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "creator": {"@type": "Organization", "name": SITE_NAME, "url": BASE_URL},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": BASE_URL},
        "url": url, "isAccessibleForFree": True,
        "dateModified": TODAY, "datePublished": TODAY,
        "temporalCoverage": f"2026-05/{TODAY}",
        "keywords": ["OZEV", "EV charging", "UK", "commercial installers",
                     "open data"],
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json",
             "contentUrl": json_url},
            {"@type": "DataDownload", "encodingFormat": "text/csv",
             "contentUrl": csv_url},
        ],
    }
    article_jl = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": title,
        "author": {"@type": "Organization", "name": SITE_NAME},
        "publisher": {"@type": "Organization", "name": SITE_NAME,
                      "url": BASE_URL},
        "datePublished": TODAY, "dateModified": TODAY,
        "mainEntityOfPage": url, "url": url,
    }
    jsonld = (
        '<script type="application/ld+json">' + json.dumps(dataset_jl)
        + '</script>'
        '<script type="application/ld+json">' + json.dumps(article_jl)
        + '</script>'
        + breadcrumb_jsonld([
            ("Directory", "/"),
            ("Data", "/data/uk-ev-installer-landscape/"),
            ("May 2026 snapshot", f"/data/{SNAPSHOT_SLUG}/"),
        ])
    )

    og_meta = (
        f'<meta property="og:url" content="{url}">'
        f'<meta property="og:site_name" content="{esc(SITE_NAME)}">'
        f'<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:title" content="{esc(title)}">'
        f'<meta name="twitter:description" content="{esc(desc)}">'
        f'<meta name="article:published_time" content="{TODAY}">'
        f'<meta name="article:modified_time" content="{TODAY}">'
    )
    jsonld = og_meta + jsonld

    extra_css = """<style>
.snap-wrap .lede{font-size:18px;color:var(--mut);max-width:720px;margin:8px 0 28px}
.snap-wrap h2{margin-top:42px;font-size:26px;letter-spacing:-.5px}
.snap-wrap h3{margin-top:22px;font-size:18px}
.snap-wrap table{width:100%;border-collapse:collapse;margin:14px 0 22px;font-size:14.5px}
.snap-wrap th,.snap-wrap td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--bd-l)}
.snap-wrap th{background:#f3f6fa;font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
.snap-wrap .sr-fb{margin:8px 0 0}
.snap-wrap .sr-fb caption{caption-side:top;text-align:left;font-size:12.5px;color:var(--mut);padding:4px 0}
.snap-wrap .snap-tbl{font-size:13.5px}
.snap-wrap .statgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:18px 0 26px}
.snap-wrap .statbox{background:#fff;border:1px solid var(--bd-l);border-radius:10px;padding:16px}
.snap-wrap .statbox b{display:block;font-size:30px;font-weight:800;letter-spacing:-1px;color:var(--ink)}
.snap-wrap .statbox span{color:var(--mut);font-size:13px}
.snap-wrap .callout{background:#f7fafc;border-left:3px solid var(--green);padding:14px 18px;border-radius:0 6px 6px 0;margin:18px 0;font-size:14.5px;color:var(--ink)}
.snap-wrap .cite{background:#0a0a0a;color:#e7ecef;padding:18px;border-radius:10px;margin:22px 0;font-size:14px}
.snap-wrap .cite code{display:block;background:rgba(255,255,255,.06);padding:10px 12px;border-radius:6px;margin-top:8px;color:#9fe6b4;font-size:13px;word-break:break-word;white-space:normal}
.snap-wrap .use{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}
.snap-wrap .use a{background:#fff;border:1px solid var(--bd-l);border-radius:8px;padding:12px 16px;text-decoration:none;color:var(--ink);font-weight:600;font-size:14px}
.snap-wrap .use a:hover{border-color:var(--green);color:var(--green-d)}
.snap-wrap .caveat{font-size:14.5px;color:var(--mut)}
.snap-wrap .caveat li{margin:6px 0}
.snap-wrap .upd{color:var(--mut);font-size:13.5px}
</style>"""

    body = f"""<div class="wrap crumb"><a href="/">Directory</a> ›
<a href="/data/uk-ev-installer-landscape/">Data</a> › May 2026 snapshot</div>
<section style="padding-top:8px"><div class="wrap prose snap-wrap">
<h1>{esc(title)}</h1>
<p class="upd">Published {TODAY} · derived from GOV.UK / OZEV data
(Open Government Licence v3.0)</p>
<p class="lede">A dated, citation-ready snapshot of the OZEV-authorised
commercial EV charger installer landscape across the UK. Every figure below
is computed from the public OZEV register at build time; the underlying
dataset is available as JSON and CSV.</p>

<div class="statgrid">
  <div class="statbox"><b>{s['total']}</b>
    <span>OZEV-authorised commercial installers (UK total)</span></div>
  <div class="statbox"><b>{len(s['regions_ranked'])}</b>
    <span>UK regions with at least one installer</span></div>
  <div class="statbox"><b>{s['commercial_only']}</b>
    <span>Commercial-only firms (no residential)</span></div>
  <div class="statbox"><b>{s['commercial_and_res']}</b>
    <span>Commercial &amp; residential firms</span></div>
</div>

<h2>1 — Installers by UK region</h2>
<p>Every region of the UK is represented in the OZEV register, but the
distribution is highly uneven. Each region links to the regional directory
page.</p>
{region_chart_html}
<table>
  <tr><th>Region</th><th>OZEV commercial installers</th><th>Share of UK total</th></tr>
  {region_table_rows}
</table>

<h2>2 — Top 10 postcode areas by installer count</h2>
<p>Postcode areas are the alpha prefix of the outward code (for example,
<code>SW</code>, <code>M</code>, <code>B</code>). Where the dominant town for
a postcode area has a directory page, the row links to that page.</p>
{pc_chart_html}
<table>
  <tr><th>Postcode area</th><th>OZEV commercial installers</th></tr>
  {''.join(pc_table_rows)}
</table>

<h2>3 — Coverage gap: the three regions with the fewest installers</h2>
<div class="callout"><strong>Honesty note:</strong> this is a <em>raw count</em>
ranking, not a per-capita one. We do not publish a per-capita figure here
because we are not republishing an official ONS population table verbatim on
this page. The raw bottom-three is still the cleanest defensible signal of
where buyer choice is thinnest.</div>
<table>
  <tr><th>Region (bottom 3 by raw count)</th><th>Installers</th></tr>
  {gap_rows}
</table>

<h2>4 — Trading status: commercial-only vs commercial + residential</h2>
<p>From the <code>services</code> field on each OZEV record. A firm is counted
as &ldquo;commercial-only&rdquo; when its OZEV entry lists commercial work
but not residential.</p>
{ts_chart_html}
<table>
  <tr><th>Trading status</th><th>Installers</th><th>Share</th></tr>
  <tr><td>Commercial only</td><td>{s['commercial_only']}</td>
      <td>{s['commercial_only'] / s['total'] * 100:.1f}%</td></tr>
  <tr><td>Commercial + Residential</td><td>{s['commercial_and_res']}</td>
      <td>{s['commercial_and_res'] / s['total'] * 100:.1f}%</td></tr>
</table>

<h2>5 — Methodology</h2>
<p>The dataset is the public GOV.UK OZEV authorised-installer register,
queried across a UK-wide postcode grid and de-duplicated on a normalised
name + postcode key. Records keep only installers that list commercial
work. Full pipeline and refresh cadence on the
<a href="/methodology/">methodology page</a>. The raw JSON used to build
this page is at
<a href="/data/installers.json"><code>/data/installers.json</code></a>.</p>

<h2>6 — Caveats &amp; known limitations of the OZEV register</h2>
<ul class="caveat">
  <li>The OZEV register is a list of <em>authorised</em> installers — it
      does not certify capacity, current trading status or recent project
      history.</li>
  <li>Region is taken from each installer's listed postcode. A national
      installer with a single registered office appears once, in that
      office's region, even if they work UK-wide.</li>
  <li>Postcode-area counts measure where installers are <em>registered</em>,
      not where they have completed installations.</li>
  <li>The register is refreshed by GOV.UK on its own cadence; this snapshot
      reflects what was visible on the date stamped above.</li>
  <li>&ldquo;Commercial-only&rdquo; vs &ldquo;commercial + residential&rdquo;
      reflects what each firm has elected to advertise via OZEV, not the
      actual mix of work delivered.</li>
</ul>

<h2>7 — Use this data</h2>
<p>All derived statistics on this page are free to reuse with attribution
under the Open Government Licence v3.0.</p>
<div class="use">
  <a href="/data/installers.json">Download JSON →</a>
  <a href="/data/installers.csv">Download CSV →</a>
  <a href="/methodology/">Methodology →</a>
</div>

<h2>Cite this snapshot</h2>
<div class="cite">Suggested citation (Open Government Licence v3.0):
  <code>{esc(citation)}</code></div>

<div class="cta-row">
  <a class="btn btn-g" href="/#directory">Browse the directory</a>
  <a class="btn btn-o" style="border-color:#cfd6df;color:#0a0a0a"
     href="/data/uk-ev-installer-landscape/">Evergreen landscape page →</a>
</div>

</div></section>"""

    return (
        head(title, desc, url, extra_css + jsonld)
        + navbar()
        + body
        + footer()
        + SHORTLIST_JS
        + "</body></html>"
    )


def _write_public_open_data(installers):
    """Emit publication-safe JSON + CSV under dist/data/ so the snapshot
    page's 'use this data' links resolve. CSV is a clean public-friendly
    subset (no scraped personal emails)."""
    out_dir = DIST / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    src = (DATA / "installers.json").read_text(encoding="utf-8")
    (out_dir / "installers.json").write_text(src, encoding="utf-8")
    with (out_dir / "installers.csv").open("w", newline="",
                                           encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "town", "region", "postcode", "services",
                    "website", "phone", "lat", "lon", "last_verified"])
        for i in installers:
            w.writerow([
                i.get("name", ""),
                i.get("town", ""),
                i.get("region", ""),
                i.get("postcode", ""),
                "; ".join(i.get("services", []) or []),
                i.get("website", "") if i.get("website") not in ("N/A", None) else "",
                i.get("phone", "") if i.get("phone") not in ("N/A", None) else "",
                i.get("lat", ""),
                i.get("lon", ""),
                i.get("last_verified", ""),
            ])


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
<li>Who applies for the Workplace Charging Scheme and (if applicable) the Depot Charging Scheme?</li>
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
var ctL={fast:'Fast AC 7–22 kW',rapid:'Rapid DC 50–100 kW',ultra:'Ultra-rapid 150 kW+'};
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


_COSTS_GUIDE_BODY = """
<h2>Why this page exists</h2>
<p>Most "commercial EV charger cost" pages on the open web are lead-generation
copy with prices that haven't been updated since 2022. This one isn't. Every
figure below is sourced to a public 2026 reference — OZEV, GOV.UK, trade press,
manufacturer rate cards or installer-published guide prices. If a number looks
low, it's because we've stripped marketing optimism out. If it looks high,
it's because the worst-case (deep civils, DNO reinforcement, ultra-rapid
hardware) is the case that quietly kills projects.</p>
<p>We've written it for the person who has to sign the PO: fleet manager, FD,
facilities lead. The aim is that you can take this page into a quote meeting
and ask better questions than the salesperson is expecting.</p>

<h2>Itemised costs, by charger tier (UK, 2026)</h2>
<p>Three tiers cover almost every commercial project. Within each tier, what
moves you to the high end of the range is usually one of three things: distance
from the existing supply, whether you need an OCPP back-office, and whether
the DNO has to reinforce upstream of your meter.</p>

<h3>Fast AC, 7–22 kW</h3>
<table>
<tr><th>Item</th><th>Typical 2026 range (per socket)</th><th>What pushes you high</th></tr>
<tr><td>Hardware (untethered, smart, OCPP 1.6J)</td><td>£550 – £1,400</td><td>22 kW three-phase + payment terminal</td></tr>
<tr><td>Installation labour</td><td>£400 – £900</td><td>Bollards, second-fix, commissioning across multiple bays</td></tr>
<tr><td>Cabling &amp; minor civils (per socket, shared trench)</td><td>£250 – £700</td><td>Concrete or paved car park vs. soft ground</td></tr>
<tr><td>All-in installed, basic workplace</td><td><strong>£1,200 – £3,000</strong></td><td>Long cable runs, full reinstatement, three-phase</td></tr>
</table>
<p>22 kW only delivers 22 kW if your supply is three-phase and the vehicle
accepts it. Most fleet cars (e.g. ID.3, Model 3 SR) accept 11 kW AC. Spec
22 kW only where the duty cycle genuinely needs it — otherwise 7 kW with
load management is cheaper and grant-efficient.</p>

<h3>Rapid DC, 50–100 kW</h3>
<table>
<tr><th>Item</th><th>Typical 2026 range (per unit)</th><th>What pushes you high</th></tr>
<tr><td>Hardware (dual-gun CCS/CHAdeMO, OCPP, contactless)</td><td>£10,000 – £24,000</td><td>Dual-output, payment terminal, ISO 15118 plug-and-charge</td></tr>
<tr><td>Installation &amp; commissioning</td><td>£2,000 – £5,000</td><td>Crane lift, kerbside install, traffic management</td></tr>
<tr><td>Civils &amp; ducting (per unit, shared trench)</td><td>£2,000 – £6,000</td><td>Long run from intake; tarmac reinstatement</td></tr>
<tr><td>All-in installed, per unit</td><td><strong>£14,000 – £35,000</strong></td><td>New LV supply, off-grid location</td></tr>
</table>

<h3>Ultra-rapid DC, 150 kW+</h3>
<table>
<tr><th>Item</th><th>Typical 2026 range (per unit)</th><th>What pushes you high</th></tr>
<tr><td>Hardware (150–350 kW, liquid-cooled cables)</td><td>£30,000 – £55,000</td><td>350 kW, dual-gun, energy storage option</td></tr>
<tr><td>Installation &amp; commissioning</td><td>£3,000 – £8,000</td><td>HV switchgear, transformer placement</td></tr>
<tr><td>Civils, plinths, transformer compound</td><td>£2,000 – £17,000</td><td>New HV substation on site</td></tr>
<tr><td>All-in installed, per unit</td><td><strong>£35,000 – £80,000</strong></td><td>New HV connection, rural site</td></tr>
</table>

<h3>Site-level costs that sit on top</h3>
<ul>
<li><strong>Trenching:</strong> roughly £30/m in soft ground, £60–£80/m through paving or tarmac with reinstatement (Checkatrade, 2026). On a 200-bay car park, run-length is the single biggest civils variable.</li>
<li><strong>DNO grid connection / upgrade:</strong> from a few hundred pounds for a notification on a domestic-scale upgrade to <strong>£50,000+ for an LV reinforcement</strong>, and well into seven figures (£3–5m has been cited) for a full HV connection at a logistics depot. Under Ofgem's Access SCR rules (April 2023) the DNO absorbs deep reinforcement costs — but the customer still pays for the connection works, the assets up to the meter, and any non-contestable supply works.</li>
<li><strong>Charge-point management software (CPMS / back-office):</strong> £10–£50 per charger per month, depending on whether you need OCPI roaming, RFID/group billing, dynamic load balancing, and fleet telematics integration.</li>
<li><strong>Maintenance &amp; warranty:</strong> budget 8–12% of hardware cost per year after the warranty period; rapid/ultra-rapid units carry the bigger long-tail bill (contactor wear, liquid-cooling pumps).</li>
</ul>

<h2>Three worked examples (real UK numbers, 2026)</h2>

<h3>(a) 12-bay workplace car park — mid-sized employer, suburban</h3>
<p>Twelve 7 kW AC sockets across two banks of six, shared cable trench, three-phase supply already at the meter room, modest groundworks, OCPP-managed.</p>
<table>
<tr><th>Line</th><th>£</th></tr>
<tr><td>Hardware: 12 × 7 kW smart units @ £750</td><td>9,000</td></tr>
<tr><td>Labour &amp; commissioning</td><td>7,200</td></tr>
<tr><td>Civils (35 m shared trench, paved)</td><td>2,800</td></tr>
<tr><td>Bollards, bay markings, signage</td><td>1,500</td></tr>
<tr><td>Distribution board upgrade</td><td>2,200</td></tr>
<tr><td>DNO notification (G99, no reinforcement)</td><td>600</td></tr>
<tr><td>CPMS setup &amp; first year (12 × £20/mo)</td><td>2,880</td></tr>
<tr><td><strong>Gross total</strong></td><td><strong>£26,180</strong></td></tr>
<tr><td>WCS grant (12 sockets × £500, capped at 75%)</td><td>-6,000</td></tr>
<tr><td><strong>Net after grant</strong></td><td><strong>£20,180</strong></td></tr>
</table>
<p>Payback is a function of utilisation and tariff strategy: at 4,500 kWh/socket/yr and a 10p/kWh margin vs. cost recovery, the gross margin pool is about £5,400/yr. Most workplaces don't run this as a profit centre — the real ROI is staff retention and salary-sacrifice scheme support.</p>

<h3>(b) Fleet depot — 20 vans, overnight charging</h3>
<p>20 × 11 kW AC bays, all charging in a 10-hour overnight window. The supply needs to be sized for diversified load (20 × 11 kW = 220 kW peak, but dynamic load balancing brings it down). Assume a 100 kVA LV upgrade is needed.</p>
<table>
<tr><th>Line</th><th>£</th></tr>
<tr><td>Hardware: 20 × 11 kW load-managed units @ £850</td><td>17,000</td></tr>
<tr><td>Labour &amp; commissioning</td><td>11,500</td></tr>
<tr><td>Civils (110 m trench, mostly tarmac, reinstatement)</td><td>8,600</td></tr>
<tr><td>New sub-main, switchgear, LV panel</td><td>14,000</td></tr>
<tr><td>DNO LV reinforcement &amp; new connection</td><td>22,000</td></tr>
<tr><td>Dynamic load management + CPMS year 1</td><td>6,400</td></tr>
<tr><td>Bollards, bays, signage, fencing</td><td>3,500</td></tr>
<tr><td><strong>Gross total</strong></td><td><strong>£83,000</strong></td></tr>
<tr><td>Depot Charging Scheme: 70% of eligible chargepoint + civil costs (capped at £1m)</td><td>-44,000</td></tr>
<tr><td><strong>Net after grant</strong></td><td><strong>£39,000</strong></td></tr>
</table>
<p>This is the case where the 2026 <a style="color:var(--green-d)" href="https://find-government-grants.service.gov.uk/grants/depot-charging-scheme-1">Depot Charging Scheme</a> transforms the maths. Before it existed, fleet operators were quoted £80k+ and walked. With 70% of chargepoints and civils funded, the same project lands inside a normal capex envelope.</p>

<h3>(c) Retail park — 4 rapid DC bays, customer-facing</h3>
<p>4 × 75 kW dual-gun DC rapids, contactless payment, MID-compliant metering, public-facing OCPI back-office. Site has spare 11 kV capacity but needs a new 500 kVA transformer pad.</p>
<table>
<tr><th>Line</th><th>£</th></tr>
<tr><td>Hardware: 4 × 75 kW dual-gun rapids @ £18,500</td><td>74,000</td></tr>
<tr><td>Installation, commissioning, traffic management</td><td>15,000</td></tr>
<tr><td>Civils, plinths, ducting, ANPR</td><td>22,000</td></tr>
<tr><td>HV/LV transformer &amp; switchgear</td><td>48,000</td></tr>
<tr><td>DNO works (connection + non-contestable)</td><td>35,000</td></tr>
<tr><td>Back-office, payment, OCPI roaming year 1</td><td>4,800</td></tr>
<tr><td>Branding, signage, lighting</td><td>6,000</td></tr>
<tr><td><strong>Gross total</strong></td><td><strong>£204,800</strong></td></tr>
<tr><td>Grants applicable</td><td>0 (public-access retail not eligible for WCS or Depot Scheme)</td></tr>
<tr><td><strong>Net</strong></td><td><strong>£204,800</strong></td></tr>
</table>
<p>Public retail is funded commercially. Typical revenue at 79p/kWh public price, 40% utilisation across the day at 30 kW average session, gives £62k–£80k gross/year per bay before electricity cost. Payback is usually modelled at 3–5 years; the variables that move it are tariff differential and uptime.</p>

<h2>The grant maths, correctly</h2>
<p>There are <em>two</em> live grants that matter for commercial work in 2026, and a third that recently closed. Get the names right or your finance team will reject the business case.</p>
<h3>Workplace Charging Scheme (WCS)</h3>
<ul>
<li><strong>Up to £500/socket</strong> since 1 April 2026 (rate applies to installations completed on or after that date; the previous £350/socket rate applied to completions up to 31 March 2026).</li>
<li>Capped at <strong>75% of total purchase + installation cost</strong>.</li>
<li>Maximum <strong>40 sockets per applicant</strong>, across all sites.</li>
<li>Scheme funded to <strong>31 March 2027</strong> — no confirmed successor.</li>
<li>Claimed <em>through</em> an OZEV-authorised installer, who deducts it from your invoice. It never touches your bank account.</li>
</ul>

<h3>Depot Charging Scheme (new, 2026)</h3>
<ul>
<li>Funds <strong>70% of chargepoint and civil costs</strong> at fleet depots — including <em>trenching, cabling and electrical upgrades</em>.</li>
<li>Capped at <strong>£1 million per organisation</strong> across all sites.</li>
<li>First application window: <strong>25 March – 30 June 2026</strong>. Works to be completed by 31 March 2027.</li>
<li>Aimed at fleets adopting zero-emission HGVs, vans and coaches. Does <em>not</em> fund the vehicles themselves, nor the DNO's own reinforcement costs.</li>
</ul>

<h3>What closed on 31 March 2026</h3>
<p>The <em>Staff &amp; Fleets Infrastructure Grant</em>, the <em>Commercial Landlord Chargepoint Grant</em>, and the <em>Residential Landlord Infrastructure Grant</em> all closed to new applications on 31 March 2026. The claim deadline for existing vouchers was 26 May 2026. If a quote you're reading mentions "EV Infrastructure Grant for Staff and Fleets" as if it's still open — it isn't.</p>

<h2>The DNO supply problem (the one nobody quotes upfront)</h2>
<p>The Distribution Network Operator for your region (UKPN, SSEN, Northern Powergrid, SP Energy Networks, Electricity North West, or National Grid Electricity Distribution) is the gatekeeper on every project beyond a handful of 7 kW sockets. Three flavours of cost:</p>
<ul>
<li><strong>Contestable works</strong> — what a competing Independent Connection Provider (ICP) can do (cable, ducting up to the cut-out). On a real fleet project, you save 15–25% by shopping around.</li>
<li><strong>Non-contestable works</strong> — only the DNO can do these (jointing, final connection, asset adoption). Take it or leave it.</li>
<li><strong>Reinforcement</strong> — upgrading the network upstream. Since Ofgem's Access SCR (April 2023), DNOs socialise this cost across all users. Fleet News documented a case where this dropped a £640k project to ~£130k. Many quotes still don't reflect it.</li>
</ul>
<p>A 12-socket workplace on existing three-phase often needs only a £400–£1,200 G99. A 20-bay depot at 100 kVA upgrade is typically £15,000–£35,000 in connection works. A 4-bay ultra-rapid retail site with a new transformer is £30,000–£90,000+. Always get the DNO budget estimate before signing for hardware.</p>

<h2>What to ask installers (with the right answers)</h2>
<ul>
<li><strong>"Have you applied for a DNO upgrade of this size before? Show me a recent connection offer letter for a comparable site."</strong> Right answer: yes, with two redacted examples.</li>
<li><strong>"Is the DNO budget estimate in the quote, or excluded?"</strong> Right answer: included as a separate line, with a stated assumption.</li>
<li><strong>"What does dynamic load management cost as an add-on vs. baked in?"</strong> Right answer: baked in.</li>
<li><strong>"Who owns the back-office data, and what's the exit clause if I switch CPMS in year 3?"</strong> Right answer: you own the data, hardware is OCPP 1.6J/2.0.1, no lock-in.</li>
<li><strong>"Are you OZEV-authorised, and are you applying the WCS and (if applicable) Depot Charging Scheme?"</strong> Right answer: yes, with the voucher value or 70% line shown explicitly on the quote.</li>
<li><strong>"What's the response SLA for a faulty rapid unit, and what's the uptime guarantee?"</strong> Right answer: 4-hour remote diagnosis, 24–48h on-site for rapids, 98%+ contractual uptime.</li>
<li><strong>"Who carries the G99 paperwork — you or me?"</strong> Right answer: them.</li>
</ul>

<h2>DIY vs. broker vs. OZEV end-to-end installer</h2>
<table>
<tr><th>Route</th><th>When it works</th><th>When it doesn't</th></tr>
<tr><td><strong>DIY (you contract trades direct)</strong></td><td>You have an in-house property/facilities team and existing relationships with M&amp;E contractors. Single-site, simple supply.</td><td>Multi-site, grant-funded, or anything requiring G99.</td></tr>
<tr><td><strong>Broker / aggregator</strong></td><td>Multi-site rollouts where you want one contract and one invoice across regions.</td><td>Single sites — you'll pay a 5–15% margin for coordination you didn't need.</td></tr>
<tr><td><strong>OZEV-authorised end-to-end installer</strong></td><td>Most fleet and workplace projects, 6–40 sockets. They carry the grant claim, G99 paperwork, civils sub-contracts and warranty on one PO.</td><td>Mega-projects (50+ rapid bays, HV) where you need an EPC contractor with HV credentials.</td></tr>
</table>
<p>The honest summary: for the vast majority of UK businesses installing between 4 and 40 sockets, an OZEV-authorised end-to-end installer is cheaper in total cost of ownership than DIY <em>and</em> faster than a broker.</p>

<h2>"What should this cost?" — quick decision tree</h2>
<ul>
<li><strong>1–6 fast AC sockets, existing supply OK:</strong> £1,500–£3,000/socket installed. WCS covers up to 75%. No DNO drama.</li>
<li><strong>8–20 fast AC sockets, may need supply upgrade:</strong> £1,800–£4,500/socket. WCS up to £500/socket; G99 application required; £5k–£25k DNO budget on top.</li>
<li><strong>Fleet depot 10–40 vehicles, overnight AC:</strong> £2,500–£5,500/socket installed including load mgmt. Depot Charging Scheme covers 70% of chargepoints + civils.</li>
<li><strong>2–6 rapid DC 50–100 kW, off-street commercial:</strong> £15k–£35k/unit installed; DNO works often £15k–£50k on top. WCS not applicable for public-access bays.</li>
<li><strong>Ultra-rapid 150 kW+, retail or trunk-road:</strong> £40k–£80k/unit; HV connection £30k–£150k+; only viable with strong utilisation forecast.</li>
</ul>

<div class="box"><strong>Use this guide with the directory.</strong> Every installer listed is OZEV-authorised for commercial work. Shortlist three, ask each the seven questions above, and compare quotes with the WCS and Depot Scheme lines shown explicitly. <a style="color:var(--green-d)" href="/#directory">Open the directory →</a> · <a style="color:var(--green-d)" href="/calculator/">Estimate cost + grant →</a></div>

<div class="disc">Figures collated from public 2026 sources including GOV.UK (Workplace Charging Scheme, Depot Charging Scheme), Ofgem (Access SCR), Fleet News, Motor Transport, Checkatrade, Northern Powergrid guide prices, and installer-published rate cards. Provided for general guidance — not financial advice. Confirm current rates on GOV.UK and obtain itemised written quotes from OZEV-authorised installers before committing.</div>
"""


GUIDES = {
    "ev-charging-for-fleets": {
        "title": "EV Charging for Fleets: The 2026 Buyer's Guide",
        "desc": "How UK businesses specify, cost and grant-fund depot, workplace and fleet EV charging — with real price ranges and how to choose an OZEV installer.",
        "faqs": [
            ("How much does commercial EV charging cost?",
             "Indicatively: fast AC 7–22 kW units £1,200–£3,000 each installed for "
             "basic workplace; rapid DC 50–100 kW £14,000–£35,000 per unit; "
             "ultra-rapid 150 kW+ £35,000–£80,000; plus civils (£600–£9,000+) and "
             "a possible DNO/grid upgrade — a few hundred pounds for a notification "
             "up to £50,000+ for LV reinforcement at higher power. See the costs "
             "guide for the worked examples."),
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
<tr><td>Rapid DC 50–100 kW (per unit)</td><td>£14,000 – £35,000</td></tr>
<tr><td>Ultra-rapid 150 kW+ (per unit)</td><td>£35,000 – £80,000</td></tr>
<tr><td>Groundworks / civils (per site)</td><td>£600 – £9,000+</td></tr>
<tr><td>DNO / grid supply upgrade</td><td>A few hundred £ (notification) up to £50,000+ (LV reinforcement); HV new connection can run into six and seven figures</td></tr>
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
<li>Is the quote OZEV-grant-aware (WCS for workplace sockets <em>and/or</em> the 2026 Depot Charging Scheme for fleet-depot chargepoints and civils)?</li></ul>
<div class="box"><strong>Use the directory:</strong> every installer here is
OZEV-authorised for commercial work. Shortlist three, get comparable quotes.
<a style="color:var(--green-d)" href="/#directory">Open the directory →</a></div>
""",
    },
    "workplace-charging-scheme": {
        "title": "The Workplace Charging Scheme (WCS) Explained — 2026",
        "desc": "OZEV Workplace Charging Scheme: up to £500/socket since 1 April 2026, 75% cap, 40-socket limit, scheme ends 31 March 2027. Eligibility and how to claim.",
        "faqs": [
            ("How much is the Workplace Charging Scheme worth?",
             "Up to £500 per socket since 1 April 2026 (the previous rate was "
             "£350/socket for installations completed up to 31 March 2026) — "
             "covering a maximum of 75% of total purchase and installation cost, "
             "capped at 40 sockets per applicant."),
            ("When does the Workplace Charging Scheme end?",
             "The scheme is currently funded to 31 March 2027 with no confirmed "
             "successor. Plan for the queue that typically builds ahead of a "
             "scheme end date."),
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
<h2>What it's worth (current rate since 1 April 2026)</h2>
<table><tr><th></th><th>Up to 31 Mar 2026 (historic)</th><th>Since 1 Apr 2026 (current)</th></tr>
<tr><td>Per socket</td><td>up to £350</td><td>up to £500</td></tr>
<tr><td>Max % of total cost</td><td>75%</td><td>75%</td></tr>
<tr><td>Max sockets / applicant</td><td>40</td><td>40</td></tr>
<tr><td>Scheme end date</td><td colspan="2">31 March 2027</td></tr></table>
<p>The £500/socket rate has been in force since 1 April 2026 and applies to any
installation completed on or after that date.
<a style="color:var(--green-d)" href="/calculator/">Model it →</a></p>
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
        "title": "EV Infrastructure Grant for Fleets — What Replaced It in 2026",
        "desc": "The OZEV EV Infrastructure Grant closed to new applications on 31 March 2026. The Depot Charging Scheme replaces it — 70% of chargepoint + civil costs, up to £1m per organisation.",
        "faqs": [
            ("Is the EV Infrastructure Grant still open in 2026?",
             "No — the Staff & Fleets variant of the EV Infrastructure Grant "
             "closed to new applications on 31 March 2026. The claim deadline "
             "for existing vouchers was 26 May 2026."),
            ("What replaced it?",
             "The Depot Charging Scheme — funded 70% of chargepoint and civil "
             "costs at fleet depots, capped at £1 million per organisation. "
             "First application window: 25 March – 30 June 2026, works to be "
             "completed by 31 March 2027."),
            ("What does the Depot Charging Scheme actually fund?",
             "Chargepoints PLUS the civil works — trenching, cabling, electrical "
             "upgrades on the customer side of the meter. It does NOT fund the "
             "vehicles, nor the DNO's own network reinforcement (which since "
             "Ofgem's 2023 Access SCR reforms the DNO largely absorbs anyway)."),
        ],
        "body": """
<h2>Important update — the grant landscape changed in 2026</h2>
<p>If a quote you're reading still talks about the "EV Infrastructure Grant for
Staff and Fleets" as if it's open for new applicants — it isn't. That scheme
closed to new applications on <strong>31 March 2026</strong>, with the claim
deadline for existing vouchers on <strong>26 May 2026</strong>.</p>
<p>The replacement for fleet sites is the <strong>Depot Charging Scheme</strong>,
launched in 2026 as part of a £170m multi-year programme to 2030. It is more
generous than the old Infrastructure Grant for the depot use case.</p>
<h2>Depot Charging Scheme — the headline facts</h2>
<ul>
<li><strong>70% funded</strong> on chargepoints and civil costs (trenching,
cabling, electrical upgrades).</li>
<li>Capped at <strong>£1 million per organisation</strong> across all sites.</li>
<li>First application window: <strong>25 March – 30 June 2026</strong> (currently open).</li>
<li>Works must be completed by <strong>31 March 2027</strong>.</li>
<li>Aimed at fleets adopting zero-emission HGVs, vans and coaches. Doesn't fund
vehicles or DNO reinforcement.</li>
</ul>
<p>Source: <a style="color:var(--green-d)" href="https://find-government-grants.service.gov.uk/grants/depot-charging-scheme-1">GOV.UK — Depot Charging Scheme</a>.</p>
<h2>How it stacks with the Workplace Charging Scheme</h2>
<p>The WCS (which is still very much open — see the
<a style="color:var(--green-d)" href="/guides/workplace-charging-scheme/">WCS guide</a>)
covers up to £500/socket (the rate in force since 1 April 2026) for workplace sites. The Depot Charging
Scheme is the fleet-depot analogue. A good installer applies whichever scheme fits
your site type — they are not generally stacked on the same sockets.</p>
<div class="box">For a worked example showing a 20-van depot project's net cost
with the Depot Charging Scheme applied (£83k gross → £39k net), see the
<a style="color:var(--green-d)" href="/guides/ev-charger-installation-costs-uk/">commercial
EV charger installation costs guide</a>.</div>
""",
    },
    "grant-deadlines": {
        "title": "UK EV Charging Grant Deadlines & Rate Changes (2026–2027)",
        "desc": "Every live UK EV charging grant deadline and rate change on one page: the £500/socket WCS rate in force since 1 April 2026 and the 31 March 2027 scheme end date.",
        "faqs": [
            ("What is the most important live EV grant date?",
             "31 March 2027: the Workplace Charging Scheme is currently funded "
             "only to that date with no confirmed successor. The per-socket "
             "contribution rose from up to £350 to up to £500 on 1 April 2026."),
            ("What's the live grant position right now?",
             "The Workplace Charging Scheme has been at up to £500/socket since "
             "1 April 2026 (capped at 75% of cost, max 40 sockets per applicant) "
             "and runs to 31 March 2027. The Depot Charging Scheme launched in "
             "2026 and is open — first application window 25 March – 30 June 2026."),
            ("What's the most consequential 2026 grant change?",
             "The launch of the Depot Charging Scheme on 25 March 2026 — it "
             "funds 70% of chargepoint and civil costs at fleet depots, up to "
             "£1m per organisation. For depot operators, this is a bigger deal "
             "than the WCS uplift."),
        ],
        "body": """
<h2>Why this page exists</h2>
<p>Grant rates and end-dates move, and missing a change can cost a fleet project
thousands. This tracks the live position.</p>
<h2>Current position</h2>
<table><tr><th>Scheme</th><th>Status / key dates</th></tr>
<tr><td>Workplace Charging Scheme</td><td><strong>OPEN.</strong> Up to £500/socket
since 1 Apr 2026 (previously £350). ≤75% of cost, max 40 sockets per applicant.
<strong>Scheme ends 31 Mar 2027.</strong></td></tr>
<tr><td>Depot Charging Scheme (new, 2026)</td><td><strong>OPEN.</strong> First
application window 25 Mar – 30 Jun 2026 (currently open). Funds 70% of chargepoint
+ civil costs (trenching, cabling, electrical upgrades) up to £1m per organisation.
Works to be completed by 31 Mar 2027.</td></tr>
<tr><td>EV Infrastructure Grant (Staff &amp; Fleets)</td><td><strong>CLOSED to new
applications on 31 Mar 2026.</strong> Claim deadline for existing vouchers was
26 May 2026. Replaced by the Depot Charging Scheme for fleet sites.</td></tr>
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
    "ev-charger-installation-costs-uk": {
        "title": "Commercial EV Charger Installation Costs UK — The Real 2026 Numbers",
        "desc": "Itemised UK commercial EV charger installation costs for 2026 — fast AC, rapid DC and ultra-rapid — with worked fleet examples, OZEV grant maths and DNO realities.",
        "faqs": [
            ("What does a commercial EV charger actually cost to install in the UK in 2026?",
             "Installed, per socket: fast AC 7–22 kW around £1,200–£3,000; rapid DC 50–100 kW around £14,000–£35,000; ultra-rapid 150 kW+ around £35,000–£80,000. Site-wide civils add £600–£9,000+ and a DNO grid upgrade can add anywhere from a few hundred pounds to £50,000+ at higher power. Software is £10–£50 per charger per month."),
            ("Is the Workplace Charging Scheme really £500 per socket now?",
             "Yes — since 1 April 2026 the OZEV WCS has paid up to £500 per socket (up from £350), capped at 75% of total cost and a maximum of 40 sockets per applicant. The scheme is currently funded only to 31 March 2027."),
            ("Is there still a grant for the civils and grid upgrade?",
             "Not as a standalone scheme. The old Staff and Fleets Infrastructure Grant closed to new applications on 31 March 2026. For fleet depots, the new Depot Charging Scheme funds 70% of chargepoints and civil works (trenching, cabling, electrical upgrades) up to £1 million per organisation, with works to be completed by 31 March 2027."),
            ("Why do DNO grid upgrades blow up so many EV projects?",
             "Because they are scoped last and quoted by a monopoly. Anything beyond a handful of 7 kW points usually needs a G99 application and often a transformer or LV reinforcement. Under Ofgem's Access SCR rules (April 2023), DNOs absorb the reinforcement cost, but the customer still pays the connection works and faces 6–18 month lead times. A good installer scopes the DNO position before quoting hardware."),
            ("Should I go through a broker, an OZEV-authorised installer, or DIY the project?",
             "For anything above 6–8 sockets, an OZEV-authorised end-to-end installer is usually cheapest in total cost of ownership. Brokers add a 5–15% margin but can be worth it for multi-site rollouts where you need one contract. Pure DIY (you contract the electrician, the civils firm and the DNO yourself) only makes sense if you have an in-house property team — otherwise the grant claim, G99 paperwork and warranties fall through the cracks."),
            ("What single question separates a good installer from a bad one?",
             "'Have you applied for a DNO upgrade of this size before, and can you show me a recent connection offer letter for a comparable site?' If they hesitate, walk away. Grid is where projects die."),
            ("Is the £500/socket WCS rate already in force?",
             "Yes. Since 1 April 2026 every completed WCS installation has been claimed at up to £500/socket (capped at 75% of total cost, max 40 sockets per applicant). The scheme is funded only to 31 March 2027, so the practical pressure now is avoiding the queue that builds in Q1 2027 ahead of the scheme ending."),
        ],
        "body": _COSTS_GUIDE_BODY,
    },
}


# ---------------------------------------------------------------- services ----
# Service-intent landing pages. The OZEV source has no per-installer sub-tag
# for fleet/workplace/depot/public site type — every authorised installer is
# tagged simply "Commercial" and/or "Residential". So the eligible pool for
# all four pages is the same: every OZEV-authorised commercial installer.
# The intro and FAQs surface that honestly rather than fabricate sub-flags.
SERVICES = {
    "fleet-charging-installers": {
        "h1": "Fleet EV Charging Installers UK",
        "audience": "fleet operators running vans, HGVs or company cars",
        "title_tail": "Fleet EV Charging Installers UK",
        "meta_desc": ("OZEV-authorised UK installers for fleet EV charging — vans, "
                      "HGVs and company cars. Independent directory of {n} "
                      "commercial installers, with Workplace Charging Scheme and "
                      "Depot Charging Scheme grant context."),
        "intro_html": ("<p>Fleet EV charging is its own discipline. Charging twenty vans overnight "
                       "is not \"home chargers, twenty times over\" — it is a load-management, "
                       "supply-sizing and back-office problem. The installer you pick has to think "
                       "in diversity factors, G99 connection applications and OCPP back-offices, "
                       "not single sockets.</p>"
                       "<p>The {n} installers on this page are all <strong>OZEV-authorised for "
                       "commercial work</strong> on the public GOV.UK list — the same authorisation "
                       "that covers fleet depot installs. OZEV does not publish a separate \"fleet "
                       "specialist\" sub-tag, so the right next step is to shortlist three, then "
                       "ask each for a recent comparable fleet project. The "
                       "<a style=\"color:var(--green-d)\" href=\"/guides/ev-charging-for-fleets/\">EV "
                       "charging for fleets guide</a> sets out what a credible answer looks like.</p>"
                       "<h2>Typical fleet charging scope</h2>"
                       "<ul>"
                       "<li><strong>Depot AC, 7–22 kW per bay</strong> — overnight charging for vans, "
                       "cars and light commercial vehicles returning to base. Load management is "
                       "usually mandatory: 20 × 11 kW is 220 kW of unmanaged peak.</li>"
                       "<li><strong>Depot DC rapid, 50–150 kW</strong> — for HGVs, coaches and "
                       "back-to-back van duty cycles. Almost always needs DNO reinforcement.</li>"
                       "<li><strong>Mixed workplace + fleet sites</strong> — staff and pool cars "
                       "share infrastructure; load management and tariff strategy separate "
                       "operating cost from over-spec.</li>"
                       "</ul>"
                       "<h2>Grants that apply to fleet projects</h2>"
                       "<ul>"
                       "<li><strong>Workplace Charging Scheme (WCS)</strong> — up to £500 per socket "
                       "(the rate in force since 1 April 2026; was £350), covering up to 75% of "
                       "cost, capped at 40 sockets per applicant. Scheme funded to 31 March 2027. "
                       "Eligible for off-street staff/fleet parking. See the "
                       "<a style=\"color:var(--green-d)\" href=\"/guides/workplace-charging-scheme/\">WCS "
                       "guide</a>.</li>"
                       "<li><strong>Depot Charging Scheme</strong> — new for 2026. Funds 70% of "
                       "chargepoint and civil costs (trenching, cabling, electrical upgrades) at "
                       "fleet depots, capped at £1m per organisation. First application window: "
                       "25 March – 30 June 2026; works to be completed by 31 March 2027. Aimed at "
                       "zero-emission HGVs, vans and coaches. See the "
                       "<a style=\"color:var(--green-d)\" href=\"/guides/ev-infrastructure-grant/\">grant "
                       "guide</a>.</li>"
                       "</ul>"
                       "<h2>Questions to ask every fleet installer</h2>"
                       "<ul>"
                       "<li>Have you delivered a fleet depot of this socket count and power before? "
                       "Show me a redacted recent example.</li>"
                       "<li>Is dynamic load management baked in, or a paid add-on?</li>"
                       "<li>Is the G99 (DNO) application included, with a separate budget line for "
                       "DNO works?</li>"
                       "<li>Are WCS and (where applicable) the Depot Charging Scheme shown "
                       "explicitly on your quote?</li>"
                       "<li>What OCPP back-office and what does it cost beyond year one?</li>"
                       "</ul>"
                       "<p>For worked numbers — including a 20-van depot at £83k gross / £39k net "
                       "after the Depot Charging Scheme — see the "
                       "<a style=\"color:var(--green-d)\" href=\"/guides/ev-charger-installation-costs-uk/\">commercial "
                       "EV charger installation costs</a> guide.</p>"),
        "faqs": [
            ("How do I know an installer can actually deliver a fleet depot?",
             "OZEV authorisation is necessary but not sufficient — it covers commercial work generally, not depot scale specifically. Ask for two redacted recent depot projects of similar socket count and supply level, and ask whether load management is baked in or an add-on."),
            ("Which grant applies to my fleet site?",
             "If it is a workplace car park with staff and fleet parking, the Workplace Charging Scheme (up to £500/socket, the rate in force since 1 April 2026) applies. If it is a dedicated fleet depot moving zero-emission HGVs, vans or coaches, the new Depot Charging Scheme is the better fit — 70% of chargepoint and civil costs up to £1m per organisation, first window 25 March – 30 June 2026."),
            ("Can I stack the WCS with the Depot Charging Scheme?",
             "Not generally on the same sockets. A good installer applies whichever scheme fits each site type; mixed-use sites are split by use case in the application."),
            ("How long does a fleet depot installation take?",
             "On a site with adequate existing supply, 8–14 weeks from order. On a site that needs a DNO reinforcement or new transformer, lead times are 6–18 months end-to-end — the DNO works are the long pole."),
            ("Do these installers cover the whole UK?",
             "Most do — OZEV authorisation is national. The directory lists each installer at their registered office postcode, but service radius is wider. Confirm coverage when you ring."),
        ],
    },
    "workplace-charging-installers": {
        "h1": "Workplace EV Charging Installers UK",
        "audience": "employers fitting staff car-park EV charging",
        "title_tail": "Workplace EV Charging Installers UK",
        "meta_desc": ("OZEV-authorised UK installers for workplace EV charging in "
                      "staff and office car parks. Independent directory of {n} "
                      "commercial installers, with Workplace Charging Scheme "
                      "(up to £500/socket since 1 April 2026) context."),
        "intro_html": ("<p>Workplace EV charging is the most common commercial install in the UK "
                       "and the one the Workplace Charging Scheme (WCS) was built for. The {n} "
                       "installers on this page are all <strong>OZEV-authorised</strong> for "
                       "commercial work — which is the authorisation required to redeem a WCS "
                       "voucher on your behalf.</p>"
                       "<p>OZEV does not sub-tag the public list by site type, so this page is "
                       "filtered to every commercial OZEV-authorised installer. Shortlist three, "
                       "give each your voucher reference, and compare quotes with the WCS line "
                       "shown explicitly.</p>"
                       "<h2>Typical workplace charging scope</h2>"
                       "<ul>"
                       "<li><strong>Fast AC, 7–22 kW per socket</strong> — staff and visitor "
                       "parking. 22 kW only delivers 22 kW when the supply is three-phase and the "
                       "vehicle accepts it. Most fleet cars accept 11 kW AC; specifying 22 kW "
                       "everywhere is usually over-spend.</li>"
                       "<li><strong>Smart load management</strong> — even a 12-socket workplace "
                       "can exceed an existing single-phase supply at peak.</li>"
                       "<li><strong>OCPP-managed back-office</strong> — necessary for RFID access, "
                       "group billing, salary-sacrifice reconciliation and switching software "
                       "supplier without ripping the hardware out.</li>"
                       "</ul>"
                       "<h2>Workplace Charging Scheme — the headline rules</h2>"
                       "<ul>"
                       "<li>Up to <strong>£500 per socket</strong>, the rate in force since "
                       "1 April 2026 (was £350). The rate applies to installations completed on "
                       "or after that date, regardless of voucher application date.</li>"
                       "<li>Capped at <strong>75% of total purchase + installation cost</strong>.</li>"
                       "<li>Maximum <strong>40 sockets per applicant</strong>, across all sites.</li>"
                       "<li>Scheme funded to <strong>31 March 2027</strong>; no confirmed successor.</li>"
                       "<li>Claimed through your OZEV-authorised installer — the discount is "
                       "applied to your invoice; the grant never touches your bank account.</li>"
                       "</ul>"
                       "<p>Full details on the "
                       "<a style=\"color:var(--green-d)\" href=\"/guides/workplace-charging-scheme/\">WCS "
                       "guide</a>, or use the "
                       "<a style=\"color:var(--green-d)\" href=\"/calculator/\">grant + cost "
                       "calculator</a> to model your project.</p>"
                       "<h2>What makes workplace different from depot or public</h2>"
                       "<p>Workplace sites are staff/visitor parking — not customer parking "
                       "(public-access retail bays are not WCS-eligible) and not depot bays "
                       "(which are usually fleet-only and increasingly fit the Depot Charging "
                       "Scheme instead). The installer's value-add is mostly grant administration "
                       "plus load management — civils are typically modest because the supply "
                       "already sits in a meter room a short trench away.</p>"
                       "<h2>Questions to ask every workplace installer</h2>"
                       "<ul>"
                       "<li>Will you redeem the WCS voucher on the quote, with the discount shown "
                       "as a separate line?</li>"
                       "<li>Is the quote OCPP-based with no software lock-in if I switch CPMS in "
                       "year three?</li>"
                       "<li>What is the load-management strategy, and is it included?</li>"
                       "<li>What is the warranty period and on-site SLA?</li>"
                       "</ul>"),
        "faqs": [
            ("How much is the Workplace Charging Scheme worth in 2026?",
             "Up to £350 per socket until 31 March 2026, then up to £500 per socket from 1 April 2026 — covering a maximum of 75% of total purchase and installation cost, capped at 40 sockets per applicant. The scheme is funded to 31 March 2027."),
            ("Do I have to use an OZEV-authorised installer for the WCS?",
             "Yes. The voucher is redeemed through an OZEV-authorised installer, who applies the discount to your invoice. Every installer on this page is on the public GOV.UK OZEV authorised list at the most recent refresh."),
            ("Is customer parking eligible for the WCS?",
             "No. The WCS is for staff and fleet off-street parking. Public-access bays at retail, hospitality and visitor car parks are not WCS-eligible — they are commercially funded."),
            ("How long does a workplace install take?",
             "On an existing three-phase supply, a 12-socket workplace is typically 4–8 weeks from order to commissioning. On a single-phase supply or where load management is being added across an existing distribution board, allow 8–12 weeks."),
            ("Which kinds of organisations qualify for the WCS?",
             "UK-registered businesses, charities and public-sector bodies with dedicated off-street parking for staff or fleet, where installation is by an OZEV-authorised installer. You must own the site or have landlord consent."),
        ],
    },
    "depot-rapid-charging-installers": {
        "h1": "Depot Rapid DC Charging Installers UK",
        "audience": "logistics, bus and coach depots specifying DC rapid charging",
        "title_tail": "Depot Rapid DC Charging Installers UK",
        "meta_desc": ("OZEV-authorised UK installers for depot rapid DC EV charging "
                      "— logistics, bus, coach and HGV depots. Independent directory "
                      "of {n} commercial installers, with Depot Charging Scheme "
                      "(70% funded, up to £1m) context."),
        "intro_html": ("<p>Depot rapid DC charging is the deep end of commercial EV: 50–150 kW per "
                       "bay, near-certain DNO reinforcement, transformer-class civils and an "
                       "operating envelope where uptime <em>is</em> the business. The {n} "
                       "installers on this page are all <strong>OZEV-authorised for commercial "
                       "work</strong> — but OZEV does not publish a rapid-DC sub-tag, so ask each "
                       "shortlisted installer specifically for a recent rapid-DC depot reference "
                       "of similar power and socket count.</p>"
                       "<h2>Typical depot rapid scope</h2>"
                       "<ul>"
                       "<li><strong>50 kW DC dual-gun units</strong> — minimum for HGV and coach "
                       "duty cycles where a one-hour turn-around matters. Hardware around "
                       "£10,000–£24,000 per unit; install £2,000–£5,000; civils £2,000–£6,000.</li>"
                       "<li><strong>150 kW+ ultra-rapid units</strong> — for back-to-back HGV "
                       "charging or partner-shared sites. Hardware £30,000–£55,000 per unit; "
                       "civils and HV switchgear push all-in past £35,000 per unit and frequently "
                       "to £80,000+.</li>"
                       "<li><strong>HV connections and transformer compounds</strong> — anything "
                       "over ~200 kW of installed capacity usually triggers an HV (11 kV) supply, "
                       "a new transformer pad, switchgear and a metered substation arrangement.</li>"
                       "</ul>"
                       "<h2>Grants for depot rapid sites</h2>"
                       "<ul>"
                       "<li><strong>Depot Charging Scheme</strong> — 70% of chargepoint and civil "
                       "costs (trenching, cabling, electrical upgrades) up to £1m per organisation. "
                       "First application window: 25 March – 30 June 2026. Works to be completed "
                       "by 31 March 2027. Aimed at fleets adopting zero-emission HGVs, vans and "
                       "coaches. Does NOT fund the vehicles, and does NOT fund the DNO's own "
                       "network reinforcement (which Ofgem's 2023 Access SCR rules largely "
                       "socialise across all users).</li>"
                       "<li><strong>Workplace Charging Scheme</strong> — applies only to "
                       "off-street staff/fleet parking sockets, not to public-access DC rapid "
                       "bays. On a mixed site, the AC workplace sockets can claim WCS and the "
                       "rapid DC bays sit under the Depot Charging Scheme separately.</li>"
                       "</ul>"
                       "<h2>The DNO problem is the project</h2>"
                       "<p>For depot rapid projects, the DNO connection scope is the single "
                       "biggest cost and lead-time risk. Under Ofgem's Access SCR rules (April "
                       "2023), the DNO absorbs the deep network reinforcement cost, but the "
                       "customer pays for the connection works and the assets up to the meter. "
                       "A documented case (Fleet News) saw a £640k connection drop to ~£130k "
                       "under the new rules — but many quotes do not yet reflect this. A "
                       "credible depot installer scopes the DNO position <em>before</em> "
                       "quoting hardware.</p>"
                       "<h2>Questions to ask every depot rapid installer</h2>"
                       "<ul>"
                       "<li>Have you commissioned a rapid DC depot of this power level before? "
                       "Show me a redacted recent connection offer letter for a comparable site.</li>"
                       "<li>Is the DNO budget estimate in the quote as a separate line, with the "
                       "assumption stated, or excluded?</li>"
                       "<li>Are you proposing an Independent Connection Provider (ICP) for the "
                       "contestable works, and why or why not?</li>"
                       "<li>Is the Depot Charging Scheme 70% line shown explicitly on the quote?</li>"
                       "<li>What is the SLA on a faulty rapid unit, and what uptime do you "
                       "contract to?</li>"
                       "</ul>"
                       "<p>For worked depot numbers and the DNO sub-text, see the "
                       "<a style=\"color:var(--green-d)\" href=\"/guides/ev-charger-installation-costs-uk/\">commercial "
                       "EV charger installation costs</a> guide.</p>"),
        "faqs": [
            ("What does a depot rapid DC charger cost installed in 2026?",
             "Per unit, all-in: 50–100 kW dual-gun DC rapid £14,000–£35,000 installed; 150 kW+ ultra-rapid £35,000–£80,000. A DNO supply upgrade adds anywhere from £15,000 at LV to £150,000+ for a new HV connection. Software is £10–£50 per charger per month."),
            ("What does the Depot Charging Scheme actually fund?",
             "Chargepoints PLUS the civil works on the customer side of the meter — trenching, cabling, electrical upgrades. 70% of those costs are funded, capped at £1m per organisation. It does NOT fund the vehicles, nor the DNO's own network reinforcement."),
            ("When does the Depot Charging Scheme open?",
             "The first application window is 25 March – 30 June 2026. Works to be completed by 31 March 2027. Subsequent windows have been signalled as part of a multi-year programme to 2030."),
            ("How long does a depot rapid project take end-to-end?",
             "Typically 6–18 months including the DNO works. The hardware install is the short part (8–12 weeks); the long pole is the DNO connection offer, acceptance, reinforcement and energisation."),
            ("Are public-access rapid bays at a depot eligible for any grant?",
             "Not under the Depot Charging Scheme — it is aimed at the fleet's own zero-emission vehicles. Public-access bays at retail or trunk-road sites are commercially funded."),
        ],
    },
    "public-car-park-ev-installers": {
        "h1": "Public Car Park EV Charging Installers UK",
        "audience": "retail, hospitality and council operators of public-access car parks",
        "title_tail": "Public Car Park EV Charging Installers UK",
        "meta_desc": ("OZEV-authorised UK installers for public car park EV "
                      "charging — retail, hospitality, council and visitor "
                      "car parks. Independent directory of {n} commercial "
                      "installers."),
        "intro_html": ("<p>Public car-park EV charging is commercial EV's commercial frontier: the "
                       "sockets are <em>revenue-generating</em>, so the project has to underwrite "
                       "itself rather than rely on the grant maths that fund workplace and depot "
                       "installs. The {n} installers on this page are all <strong>OZEV-authorised "
                       "for commercial work</strong> on the public GOV.UK list — although OZEV does "
                       "not publish a public-access sub-tag, so the sensible next step is to ask "
                       "each shortlisted installer for two recent public car-park projects with "
                       "utilisation data.</p>"
                       "<h2>Typical public car-park scope</h2>"
                       "<ul>"
                       "<li><strong>Destination AC, 7–22 kW</strong> — for retail, hospitality and "
                       "leisure sites where dwell time is 1–3 hours. Cheaper per socket, but "
                       "revenue is constrained by the dwell.</li>"
                       "<li><strong>Rapid DC, 50–100 kW</strong> — for trunk-road and "
                       "high-turnover retail. Hardware £14,000–£35,000 installed per unit, plus "
                       "DNO. Throughput is the business model.</li>"
                       "<li><strong>Ultra-rapid DC, 150 kW+</strong> — for premium sites and "
                       "forecourt-style hubs. £35,000–£80,000 per unit installed; usually needs HV "
                       "and a transformer compound.</li>"
                       "<li><strong>Contactless payment and OCPI roaming</strong> — public-access "
                       "bays in the UK must accept contactless or open-payment systems under the "
                       "Public Charge Point Regulations 2023; OCPI roaming lets your bays appear "
                       "in third-party apps and broadens the revenue catchment.</li>"
                       "</ul>"
                       "<h2>Why grants mostly don't apply</h2>"
                       "<p>The Workplace Charging Scheme requires off-street staff or fleet "
                       "parking — public visitor parking is explicitly excluded. The Depot "
                       "Charging Scheme funds depots, not public bays. So most public car-park "
                       "projects are <strong>commercially funded</strong>: capex, or a "
                       "charging-as-a-service contract where the operator funds the hardware and "
                       "shares revenue.</p>"
                       "<p>That changes the conversation. You are not optimising for \"lowest net "
                       "capex after grant\" — you are optimising for utilisation, uptime and "
                       "payment friction. The installer's value-add shifts to siting (where on the "
                       "site does dwell time and visibility intersect?), payment-and-app "
                       "integration, and uptime SLA.</p>"
                       "<h2>Questions to ask every public car-park installer</h2>"
                       "<ul>"
                       "<li>Have you commissioned a public car-park site at this throughput "
                       "before? What utilisation did it hit by month 12?</li>"
                       "<li>Is the proposal capex or charging-as-a-service? What is the revenue "
                       "share and term?</li>"
                       "<li>How are contactless payment and OCPI roaming handled, and at what "
                       "ongoing cost?</li>"
                       "<li>What uptime do you contract to, and what is the on-site response SLA "
                       "for a faulty rapid unit?</li>"
                       "<li>Who owns the data — me or the back-office provider — and what happens "
                       "to it if I switch CPMS in year three?</li>"
                       "</ul>"
                       "<p>For worked retail numbers and revenue commentary, see the "
                       "<a style=\"color:var(--green-d)\" href=\"/guides/ev-charger-installation-costs-uk/\">commercial "
                       "EV charger installation costs</a> guide.</p>"),
        "faqs": [
            ("Can I claim the WCS for public car-park bays?",
             "No. The WCS is restricted to off-street staff and fleet parking. Public-access bays at retail, hospitality and visitor car parks are excluded — they are commercially funded."),
            ("Is there any grant for public-access rapid DC bays?",
             "Not as a standalone OZEV scheme in 2026. The Local EV Infrastructure (LEVI) Fund supports council-led on-street and destination charging via local authorities, but it is not a direct grant a private operator applies for. Most retail and hospitality car-park projects are capex or charging-as-a-service."),
            ("What is the typical payback on a public-access rapid bay?",
             "At a public price around 79p/kWh, around 40% utilisation, average session 30 kW: gross revenue of roughly £62,000–£80,000 per bay per year before electricity cost. Payback is typically modelled at 3–5 years; tariff differential and uptime drive the spread."),
            ("Do public bays need to accept contactless payment?",
             "Yes — the Public Charge Point Regulations 2023 require public-access charge points of 8 kW or above to offer contactless payment or an open payment system, and to publish pricing and 99%+ rapid-charger uptime."),
            ("Should I buy the hardware or use charging-as-a-service?",
             "Capex gives you the revenue and the asset, charging-as-a-service gives you no upfront cost and a revenue share. The right answer depends on your cost of capital, your forecast utilisation, and whether EV charging is core to your business or a tenant amenity."),
        ],
    },
}


def page_service(slug, spec, installers):
    """Build a service-intent landing page. The OZEV source has no per-installer
    sub-tag for fleet/workplace/depot/public, so the eligible pool is every
    OZEV-authorised commercial installer. The intro surfaces this honestly."""
    url = f"{BASE_URL}/services/{slug}/"
    eligible = [i for i in installers if "Commercial" in i.get("services", [])]
    feat = [i for i in eligible if i.get("featured")]
    rest = sorted([i for i in eligible if not i.get("featured")],
                  key=lambda x: x["name"].lower())
    ordered = feat + rest
    n = len(ordered)
    coverage_note = ""
    if n < 5:
        coverage_note = ('<p class="note">Coverage growing — the directory '
                         'rebuilds weekly from the official OZEV list.</p>')

    cards = "".join(card(i) for i in ordered)

    region_counts: dict[str, int] = {}
    for i in eligible:
        r = i.get("region")
        if r and r != "N/A":
            region_counts[r] = region_counts.get(r, 0) + 1
    top_regions = sorted(region_counts.items(), key=lambda kv: -kv[1])[:5]
    region_items = "".join(
        f'<li><a style="color:var(--green-d)" href="/regions/{slugify(r)}/">'
        f'{esc(r)}</a> — {c} OZEV-authorised commercial installer'
        f'{"s" if c != 1 else ""}</li>'
        for r, c in top_regions)
    top_regions_html = ""
    if region_items:
        top_regions_html = (
            f'<h2>Top regions for {esc(spec["h1"].lower())}</h2>'
            f'<ul style="margin:12px 0 0 22px;line-height:1.7">{region_items}</ul>')

    jl_list = {
        "@context": "https://schema.org", "@type": "ItemList",
        "name": spec["h1"], "numberOfItems": n,
        "itemListElement": [
            {"@type": "ListItem", "position": idx + 1,
             "url": f"{BASE_URL}/installers/{i['_slug']}/",
             "name": i["name"]}
            for idx, i in enumerate(ordered[:100])]}
    trail = [("Directory", "/"), ("Services", "/#directory"),
             (spec["h1"], f"/services/{slug}/")]
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl_list)
              + "</script>" + breadcrumb_jsonld(trail)
              + faq_jsonld(spec["faqs"]))

    title = f"{spec['title_tail']} — {n} Verified OZEV-Authorised Providers"
    desc = spec["meta_desc"].format(n=n)
    intro = spec["intro_html"].format(n=n)

    return (
        head(title, desc, url, jsonld)
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> ›
<a href="/#directory">Services</a> › {esc(spec['h1'])}</div>
<section style="padding-top:8px"><div class="wrap">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">{esc(spec['h1'])}</h1>
<p class="lead" style="margin-top:14px;max-width:760px">For {esc(spec['audience'])}.
{n} OZEV-authorised commercial EV charging installers on the official GOV.UK
list, filtered to those offering commercial work — independent, free, and
rebuilt weekly.</p>
<div class="prose" style="max-width:760px">{intro}</div>
{coverage_note}
<h2 class="sh" style="margin-top:40px">The installers</h2>
<p class="note">{n} OZEV-authorised commercial installer{'s' if n != 1 else ''}
shown. Featured partners are labelled and shown first; nothing else affects
order.</p>
<div class="grid">{cards or '<p class=muted>None indexed yet — coverage widens each refresh.</p>'}</div>
<div class="prose" style="max-width:760px;margin-top:40px">
{top_regions_html}
{faq_html(spec['faqs'])}
</div>
{industries_block_for_service(slug)}
<div class="cta-row" style="margin-top:22px">
<a class="btn btn-g" href="/calculator/">Estimate cost + grant</a>
<a class="btn btn-o" style="border-color:#cfd6df;color:#0a0a0a" href="/#directory">All UK installers</a>
</div>
<p class="note" style="margin-top:24px">
<a style="color:var(--green-d)" href="/">Back to home</a> ·
<a style="color:var(--green-d)" href="/sitemap.xml">Sitemap</a>
</p>
</div></section>""" + footer() + SHORTLIST_JS + "</body></html>"
    )


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


# ---------------------------------------------- grant eligibility wizard ----
def page_grant_wizard():
    """Client-side wizard: 6 questions -> eligibility for UK 2026 charger grants.
    Pure inline JS, no deps. Matches existing site CSS (.prose / .box / .calc /
    .btn / .disc) so it inherits the site look without new styles."""
    url = f"{BASE_URL}/tools/uk-ev-grant-eligibility/"
    faqs = [
        ("Which UK EV charger grants does the wizard cover?",
         "Two live commercial schemes: the Workplace Charging Scheme (WCS) — up "
         "to £500/socket since 1 April 2026, capped at 75% of cost and 40 sockets "
         "per applicant, ending 31 March 2027 — and the 2026 Depot Charging Scheme "
         "— 70% of chargepoint and civil costs at fleet depots, up to £1 million "
         "per organisation. It also flags that the older EV Infrastructure Grant "
         "for Staff and Fleets closed to new applicants on 31 March 2026."),
        ("Is this an official eligibility check?",
         "No. It is an indicative client-side tool based on the public scheme "
         "rules as of May 2026. Always confirm current eligibility on GOV.UK and "
         "with an OZEV-authorised installer before applying."),
        ("Who is eligible for the Workplace Charging Scheme?",
         "UK-registered businesses, charities and public-sector bodies with "
         "dedicated off-street parking for staff or fleet (not public-access "
         "customer parking), where installation is carried out by an OZEV-"
         "authorised installer."),
        ("Who is eligible for the Depot Charging Scheme?",
         "UK fleet operators installing chargepoints at commercial fleet depots "
         "for zero-emission vans, HGVs or coaches. It funds chargepoints plus "
         "civils on the customer side of the meter; it does not fund vehicles "
         "or DNO network reinforcement."),
        ("What happened to the EV Infrastructure Grant for Staff and Fleets?",
         "It closed to new applications on 31 March 2026. The claim deadline "
         "for existing vouchers was 26 May 2026. For fleet sites, the Depot "
         "Charging Scheme is the 2026 replacement."),
    ]
    jl = {"@context": "https://schema.org", "@type": "WebApplication",
          "name": "UK EV charger grant eligibility wizard",
          "applicationCategory": "BusinessApplication",
          "operatingSystem": "Web", "url": url,
          "offers": {"@type": "Offer", "price": "0", "priceCurrency": "GBP"}}
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>" + faq_jsonld(faqs)
              + breadcrumb_jsonld([("Directory", "/"),
                                   ("Tools", "/#directory"),
                                   ("Grant eligibility wizard",
                                    "/tools/uk-ev-grant-eligibility/")]))
    body_html = """
<div class="wrap crumb"><a href="/">Directory</a> › Tools › Grant eligibility wizard</div>
<section style="padding-top:8px"><div class="wrap prose">
<h1>UK EV charger grant eligibility wizard</h1>
<p class="upd">Indicative client-side tool · current as of May 2026 · runs entirely in your browser</p>
<p>Answer six short questions to see which UK 2026 EV charging grants you are
likely to qualify for. Nothing is sent anywhere — the logic runs in your browser.</p>

<div class="calc" id="wiz" style="grid-template-columns:1fr">
 <div class="full" data-step="1">
  <label><strong>Q1.</strong> Are you a UK-registered business, charity or public-sector body?</label>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
   <button class="btn btn-g btn-sm" type="button" data-a="q1=y">Yes</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q1=n" style="border:1px solid #cfd6df">No</button>
  </div>
 </div>
 <div class="full" data-step="2" style="display:none">
  <label><strong>Q2.</strong> Do you have off-street parking under your own control (or with landlord consent)?</label>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
   <button class="btn btn-g btn-sm" type="button" data-a="q2=y">Yes</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q2=n" style="border:1px solid #cfd6df">No</button>
  </div>
 </div>
 <div class="full" data-step="3" style="display:none">
  <label><strong>Q3.</strong> What is the primary use of the parking / chargepoints?</label>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
   <button class="btn btn-d btn-sm" type="button" data-a="q3=employee" style="border:1px solid #cfd6df">Employee parking</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q3=fleet" style="border:1px solid #cfd6df">Fleet vehicles</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q3=mixed" style="border:1px solid #cfd6df">Mixed (employee + fleet)</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q3=public" style="border:1px solid #cfd6df">Public / customer access</button>
  </div>
 </div>
 <div class="full" data-step="4" style="display:none">
  <label><strong>Q4.</strong> How many sockets are you planning to install (across all sites)?</label>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
   <button class="btn btn-d btn-sm" type="button" data-a="q4=1-10" style="border:1px solid #cfd6df">1–10</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q4=11-40" style="border:1px solid #cfd6df">11–40</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q4=40+" style="border:1px solid #cfd6df">40+</button>
  </div>
 </div>
 <div class="full" data-step="5" style="display:none">
  <label><strong>Q5.</strong> Is the site a commercial fleet depot (vans / HGVs / coaches)?</label>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
   <button class="btn btn-g btn-sm" type="button" data-a="q5=y">Yes</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q5=n" style="border:1px solid #cfd6df">No</button>
  </div>
 </div>
 <div class="full" data-step="6" style="display:none">
  <label><strong>Q6.</strong> When are you planning to complete the installation?</label>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
   <button class="btn btn-d btn-sm" type="button" data-a="q6=now" style="border:1px solid #cfd6df">Now / next few months</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q6=before2027" style="border:1px solid #cfd6df">Before 31 Mar 2027</button>
   <button class="btn btn-d btn-sm" type="button" data-a="q6=after2027" style="border:1px solid #cfd6df">After 31 Mar 2027</button>
  </div>
 </div>
 <div class="full" id="wiz-results" style="display:none"></div>
 <div class="full" style="display:flex;gap:10px;flex-wrap:wrap">
  <button class="btn btn-d" id="wiz-reset" type="button" style="background:#eef2f7;color:#0a0a0a">Start over</button>
 </div>
</div>

<div class="disc" style="margin-top:18px">Indicative only — check
<a style="color:#7a5c00;text-decoration:underline" href="https://www.gov.uk/government/publications/workplace-charging-scheme-guidance-for-applicants">GOV.UK</a>
before applying.</div>

<div class="cta-row" style="margin-top:18px">
 <a class="btn btn-g" href="/calculator/">Estimate cost + grant →</a>
 <a class="btn btn-d" href="/#directory" style="background:#eef2f7;color:#0a0a0a">Browse OZEV installers</a>
</div>

<h2>How this wizard decides</h2>
<ul>
 <li><strong>WCS:</strong> needs UK business/charity/public-sector + off-street parking + non-public use + sockets within the 40/applicant cap + installation completed by 31 Mar 2027.</li>
 <li><strong>Depot Charging Scheme:</strong> needs a commercial fleet depot (vans/HGVs/coaches) and works completed by 31 Mar 2027. First application window 25 Mar – 30 Jun 2026 is currently open.</li>
 <li><strong>EV Infrastructure Grant for Staff and Fleets:</strong> closed to new applicants on 31 Mar 2026; flagged for awareness only.</li>
 <li><strong>Public / customer-access charging</strong> (retail, destination) is not eligible for WCS or the Depot Charging Scheme — it is funded commercially.</li>
</ul>
""" + faq_html(faqs) + """
</div></section>
"""
    js = r"""
<script>
(function(){
 var A={};
 function show(step){
  document.querySelectorAll('[data-step]').forEach(function(d){d.style.display='none';});
  var el=document.querySelector('[data-step="'+step+'"]');
  if(el)el.style.display='';
 }
 function render(){
  var r=document.getElementById('wiz-results');
  if(!A.q1||!A.q2||!A.q3||!A.q4||!A.q5||!A.q6){r.style.display='none';return;}
  // Eligibility
  var ukBody=A.q1==='y';
  var offStreet=A.q2==='y';
  var use=A.q3;
  var nSockets=A.q4;
  var isDepot=A.q5==='y';
  var when=A.q6;
  var cards=[];
  // WCS
  var wcs={t:'Workplace Charging Scheme (WCS)',cap:'Up to £500/socket, 75% of cost, max 40 sockets/applicant. Ends 31 Mar 2027.'};
  if(!ukBody){wcs.s='no';wcs.r='Not a UK business / charity / public-sector body.';}
  else if(!offStreet){wcs.s='no';wcs.r='Requires dedicated off-street parking under your control.';}
  else if(use==='public'){wcs.s='no';wcs.r='Public / customer-access bays are not WCS-eligible — only staff or fleet parking.';}
  else if(when==='after2027'){wcs.s='no';wcs.r='Scheme funding ends 31 Mar 2027 — installations completed after that date cannot claim.';}
  else if(nSockets==='40+'){wcs.s='likely';wcs.r='Eligible, but capped at 40 sockets per applicant — apply for the first 40, fund the rest separately.';}
  else {wcs.s='yes';wcs.r='Eligible. Apply for a voucher online; your OZEV-authorised installer deducts it from the invoice.';}
  cards.push(wcs);
  // Depot Charging Scheme
  var dcs={t:'Depot Charging Scheme (2026)',cap:'70% of chargepoint + civil costs, up to £1m per organisation. Works to be completed by 31 Mar 2027.'};
  if(!ukBody){dcs.s='no';dcs.r='Not a UK business / charity / public-sector body.';}
  else if(!isDepot){dcs.s='no';dcs.r='Scheme is for commercial fleet depots (vans / HGVs / coaches).';}
  else if(use==='public'){dcs.s='no';dcs.r='Public / customer-access bays are not eligible.';}
  else if(when==='after2027'){dcs.s='no';dcs.r='Works must be completed by 31 Mar 2027.';}
  else {dcs.s='yes';dcs.r='Likely eligible. The first application window (25 Mar – 30 Jun 2026) is currently open — move quickly.';}
  cards.push(dcs);
  // Infrastructure Grant (Staff & Fleets) — closed
  cards.push({t:'EV Infrastructure Grant for Staff and Fleets',
   cap:'CLOSED to new applications on 31 March 2026.',
   s:'no',
   r:'No new applications since 31 March 2026. For fleet sites, see the Depot Charging Scheme above.'});

  var pill=function(s){
   if(s==='yes')return '<span style="background:#e8f6ee;color:#15803d;border:1px solid #b6e2c4;font-weight:700;font-size:12px;padding:3px 10px;border-radius:9999px">ELIGIBLE</span>';
   if(s==='likely')return '<span style="background:#fef7e0;color:#7a5c00;border:1px solid #f0d98a;font-weight:700;font-size:12px;padding:3px 10px;border-radius:9999px">LIKELY ELIGIBLE</span>';
   return '<span style="background:#fbe9e9;color:#7a1a1a;border:1px solid #f0bcbc;font-weight:700;font-size:12px;padding:3px 10px;border-radius:9999px">NOT ELIGIBLE</span>';
  };
  var guideLink=function(t){
   if(t.indexOf('Workplace')===0)return '/guides/workplace-charging-scheme/';
   if(t.indexOf('Depot')===0)return '/guides/ev-infrastructure-grant/';
   return '/guides/grant-deadlines/';
  };
  var html='<h2 style="margin-top:8px">Your indicative result</h2>';
  cards.forEach(function(c){
   html+='<div class="box" style="margin:14px 0"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px">'+
    pill(c.s)+'<strong>'+c.t+'</strong></div>'+
    '<p style="margin-bottom:6px"><em>'+c.cap+'</em></p>'+
    '<p style="margin-bottom:6px">'+c.r+'</p>'+
    '<p style="margin-bottom:0;font-size:13.5px"><a style="color:var(--green-d)" href="'+guideLink(c.t)+'">Read the '+c.t.split(' (')[0]+' guide →</a></p>'+
    '</div>';
  });
  if(!ukBody){
   html+='<div class="disc">Because you indicated this is not a UK business, charity or public-sector body, neither of the commercial schemes applies. Domestic chargepoint grants are a separate scheme and not covered here.</div>';
  }
  r.innerHTML=html;
  r.style.display='';
  r.scrollIntoView({behavior:'smooth',block:'start'});
 }
 function next(after){
  // logic flow
  if(after==='q1'){if(A.q1!=='y'){render();return;}show(2);return;}
  if(after==='q2'){show(3);return;}
  if(after==='q3'){show(4);return;}
  if(after==='q4'){show(5);return;}
  if(after==='q5'){show(6);return;}
  if(after==='q6'){render();return;}
 }
 document.addEventListener('click',function(e){
  var b=e.target.closest('[data-a]');
  if(!b)return;
  var p=b.getAttribute('data-a').split('=');
  A[p[0]]=p[1];
  // visual mark
  var step=b.closest('[data-step]');
  if(step){step.querySelectorAll('[data-a]').forEach(function(x){
   x.style.opacity=(x===b)?'1':'.55';
   x.style.outline=(x===b)?'2px solid #15803d':'none';
  });}
  next(p[0]);
 });
 document.getElementById('wiz-reset').addEventListener('click',function(){
  A={};document.querySelectorAll('[data-a]').forEach(function(x){x.style.opacity='';x.style.outline='';});
  document.getElementById('wiz-results').style.display='none';
  show(1);
 });
 show(1);
})();
</script>"""
    return (head("UK EV Charger Grant Eligibility Wizard (2026)",
                 "Free wizard: in 6 questions, see which UK 2026 EV charger grants you qualify for — Workplace Charging Scheme and/or the new Depot Charging Scheme. Indicative, browser-only.",
                 url, jsonld)
            + navbar()
            + body_html
            + footer() + SHORTLIST_JS + js + "</body></html>")


def page_simple(title, desc, slug, body_html, noindex=False):
    url = f"{BASE_URL}/{slug}/"
    return (head(title, desc, url, "", noindex) + navbar()
            + f'<section style="padding-top:30px"><div class="wrap prose"><h1>{esc(title)}</h1>{body_html}</div></section>'
            + footer() + SHORTLIST_JS + "</body></html>")


def page_cost_calculator_tool(installers):
    """In-depth cost + grant calculator at /tools/ev-charger-cost-calculator/.

    Long-tail SEO + lead-magnet tool. All math is client-side (no backend).
    Cost bands and grant rules are sourced from guides-new/costs.md and the
    GOV.UK changes-from-April-2026 page — no fabricated numbers.
    """
    url = f"{BASE_URL}/tools/ev-charger-cost-calculator/"
    from collections import Counter
    region_counts = Counter(
        i["region"] for i in installers if i.get("region") not in ("N/A", "", None)
    )
    region_data = {
        r: {"count": region_counts.get(r, 0), "slug": slugify(r)}
        for r in REGIONS_ORDER
    }
    region_opts = "".join(
        f'<option value="{esc(r)}">{esc(r)} ({region_data[r]["count"]} installers)</option>'
        for r in REGIONS_ORDER
    )

    faqs = [
        ("How much does it cost to install a commercial EV charger in the UK in 2026?",
         "Installed, per socket: fast AC 7 kW around £1,200–£3,000; 22 kW AC "
         "around £1,800–£3,500; rapid DC 50 kW around £14,000–£35,000. "
         "Site-wide civils add £600–£9,000+ and a DNO grid upgrade can add "
         "anywhere from a few hundred pounds to £50,000+ at higher power. "
         "Figures are indicative UK 2026 ranges from public sources — confirm "
         "with itemised installer quotes."),
        ("Is the Workplace Charging Scheme grant £500 per socket?",
         "Yes — from 1 April 2026 the OZEV Workplace Charging Scheme pays up "
         "to £500 per socket (was £350), capped at 75% of total project cost "
         "and a maximum of 40 sockets per applicant. The scheme is funded "
         "until 31 March 2027."),
        ("What is the Depot Charging Scheme worth?",
         "For eligible fleet depots, the Depot Charging Scheme funds 70% of "
         "chargepoints and civil works (trenching, cabling, electrical "
         "upgrades) up to £1 million per organisation. Works must be "
         "completed by 31 March 2027."),
        ("Can public car parks claim the Workplace Charging Scheme?",
         "No. WCS is for off-street parking for staff and fleet vehicles. "
         "Public-access retail, customer car parks and on-street bays are "
         "funded commercially or via separate local-authority schemes."),
        ("Why is the DNO grid upgrade cost so variable?",
         "A 12-socket workplace on an existing three-phase supply often only "
         "needs a £400–£1,200 G99 notification. A 20-bay depot needing a "
         "100 kVA upgrade is typically £15,000–£35,000. Multi-megawatt or "
         "HV-connected sites run into six and seven figures."),
    ]

    jl = {"@context": "https://schema.org", "@type": "WebApplication",
          "name": "EV Charger Installation Cost & Grant Calculator (UK)",
          "applicationCategory": "BusinessApplication",
          "operatingSystem": "Web", "url": url,
          "offers": {"@type": "Offer", "price": "0", "priceCurrency": "GBP"}}
    trail = [("Directory", "/"),
             ("EV charger cost calculator", "/tools/ev-charger-cost-calculator/")]
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl)
              + "</script>" + faq_jsonld(faqs)
              + breadcrumb_jsonld(trail))

    region_json = json.dumps(region_data, ensure_ascii=False)

    tool_css = (
        ".tool-shell{max-width:980px;margin:0 auto}"
        ".tool-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}"
        ".tool-grid .full{grid-column:1/-1}"
        ".tool-card{background:var(--card-l);border:1px solid var(--bd-l);border-radius:16px;padding:24px}"
        ".tool-card label{display:block;font-size:13px;font-weight:600;margin-bottom:6px;color:#33404f}"
        ".tool-card .hint{font-size:12px;color:var(--mut2);margin-top:4px}"
        ".tool-card input,.tool-card select{width:100%;font:inherit;font-size:15px;padding:11px 13px;border:1px solid var(--bd-l);border-radius:10px;background:#fff;color:var(--ink)}"
        ".tool-card input:focus,.tool-card select:focus{outline:0;border-color:var(--green);box-shadow:0 0 0 3px rgba(22,163,74,.15)}"
        ".tool-results{background:var(--light);border:1px solid var(--bd-l);border-radius:16px;padding:24px;margin-top:20px}"
        ".tool-row{display:flex;justify-content:space-between;align-items:baseline;padding:10px 0;border-bottom:1px dashed var(--bd-l);gap:14px;flex-wrap:wrap}"
        ".tool-row:last-child{border-bottom:0}"
        ".tool-row .lbl{font-size:14px;color:#33404f}"
        ".tool-row .val{font-size:16px;font-weight:700;color:var(--ink);text-align:right}"
        ".tool-row .val.pos{color:var(--green-d)}"
        ".tool-row.head{font-size:11.5px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut2);font-weight:700;border-bottom:1px solid var(--bd-l);padding-bottom:6px}"
        ".tool-net{background:#0e1a12;color:#fff;border-radius:12px;padding:18px 20px;margin-top:18px;display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}"
        ".tool-net .nlbl{font-size:13px;color:#9fe6b4;text-transform:uppercase;letter-spacing:.6px;font-weight:600}"
        ".tool-net .nval{font-size:28px;font-weight:800;letter-spacing:-1px;color:#fff}"
        ".tool-grants{margin-top:18px}"
        ".tool-grants .g{background:#fff;border:1px solid var(--bd-l);border-left:4px solid var(--green);border-radius:10px;padding:14px 16px;margin-bottom:10px}"
        ".tool-grants .g.muted{border-left-color:#cfd6df;opacity:.75}"
        ".tool-grants .g b{display:block;margin-bottom:3px;font-size:14px}"
        ".tool-grants .g span{font-size:13px;color:var(--mut)}"
        ".tool-cta{background:var(--card-l);border:1px solid var(--bd-l);border-radius:16px;padding:22px;margin-top:20px;display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}"
        ".tool-cta .ctxt{flex:1;min-width:240px;font-size:15px}"
        ".tool-cta .ctxt b{color:var(--green-d)}"
        ".tool-caveat{background:#fff8e6;border:1px solid #f0d98a;color:#7a5c00;font-size:13.5px;padding:14px 16px;border-radius:10px;margin-top:16px;line-height:1.5}"
        ".tool-sources{font-size:12.5px;color:var(--mut);margin-top:14px;line-height:1.6}"
        ".tool-sources a{color:var(--green-d)}"
        "@media(max-width:680px){.tool-grid{grid-template-columns:1fr}.tool-net .nval{font-size:22px}}"
    )

    body = f"""<div class="wrap crumb"><a href="/">Directory</a> ›
EV charger cost calculator</div>
<section style="padding-top:8px"><div class="wrap tool-shell">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px;margin-bottom:10px">
EV charger installation cost &amp; grant calculator</h1>
<p class="lead" style="margin-top:6px">Estimate the all-in cost of a commercial EV
charging install in the UK and the grants you can claim against it. Pure 2026 public
data — no quote forms, no email gate. Sourced from the
<a style="color:var(--green-d)" href="/guides/ev-charger-installation-costs-uk/">commercial
EV charger installation costs guide</a>.</p>

<div class="tool-card">
<div class="tool-grid">
<div>
<label for="t_sockets">Number of sockets</label>
<input id="t_sockets" type="number" min="1" max="40" value="6">
<div class="hint">1–40. The WCS grant caps at 40 sockets per applicant.</div>
</div>
<div>
<label for="t_charger">Charger type</label>
<select id="t_charger">
<option value="ac7">7 kW AC (single-phase, workplace standard)</option>
<option value="ac22">22 kW AC (three-phase fast)</option>
<option value="dc50">50 kW DC rapid</option>
</select>
<div class="hint">22 kW only delivers 22 kW if the supply is three-phase.</div>
</div>
<div>
<label for="t_site">Site type</label>
<select id="t_site">
<option value="workplace">Workplace car park</option>
<option value="depot">Fleet depot</option>
<option value="public">Public car park (retail / customer)</option>
<option value="mixed">Mixed-use (staff + visitor)</option>
</select>
</div>
<div>
<label for="t_dno">DNO grid upgrade likely?</label>
<select id="t_dno">
<option value="no">No — existing supply has headroom</option>
<option value="unsure" selected>Unsure — assume G99 notification only</option>
<option value="yes">Yes — supply upgrade required</option>
</select>
<div class="hint">Beyond a handful of 7 kW sockets, a G99 application is usually needed.</div>
</div>
<div class="full">
<label for="t_region">UK region</label>
<select id="t_region">{region_opts}</select>
</div>
</div>
</div>

<div class="tool-results" id="t_out" aria-live="polite"></div>

<div class="tool-caveat"><strong>Indicative only — not a quote.</strong>
Actual cost depends on a site survey: cable run length, surface reinstatement,
existing supply headroom, DNO connection offer and CPMS choice. Always obtain
itemised written quotes from OZEV-authorised installers before committing.
Grant rates verified against
<a style="color:var(--green-d)" href="https://www.gov.uk/guidance/changes-to-electric-vehicle-chargepoint-grant-schemes-from-1-april-2026">GOV.UK</a>.
</div>

<div class="tool-sources">
<strong>Sources:</strong> Cost ranges from our
<a href="/guides/ev-charger-installation-costs-uk/">2026 commercial EV charger
installation costs guide</a> (aggregating GOV.UK, OZEV, Checkatrade and
installer-published rate cards). Workplace Charging Scheme rates: GOV.UK
guidance for changes from 1 April 2026. Depot Charging Scheme: GOV.UK
<a href="https://find-government-grants.service.gov.uk/grants/depot-charging-scheme-1">find-government-grants service</a>.
</div>

<div class="prose" style="margin-top:46px">{faq_html(faqs)}</div>

<p style="margin-top:32px;font-size:14px"><a style="color:var(--green-d)" href="/">← Back to the directory home</a></p>
</div></section>"""

    js = (
        "<script>\n(function(){\n var REG="
        + region_json
        + ";\n var HW={ac7:[1200,3000],ac22:[1800,3500],dc50:[14000,35000]};\n"
        " var CIVILS={workplace:[600,2500],depot:[1500,9000],public:[2000,6000],mixed:[1500,5000]};\n"
        " var DNO_AC={no:[0,0],unsure:[400,1200],yes:[5000,35000]};\n"
        " var DNO_DC={no:[0,0],unsure:[800,2000],yes:[15000,90000]};\n"
        " var TODAY=new Date('" + TODAY + "');\n"
        " var WCS_BUMP=new Date('2026-04-01');\n"
        " var PER_SOCKET=(TODAY>=WCS_BUMP)?500:350;\n"
        " var fSockets=document.getElementById('t_sockets');\n"
        " var fCharger=document.getElementById('t_charger');\n"
        " var fSite=document.getElementById('t_site');\n"
        " var fDno=document.getElementById('t_dno');\n"
        " var fRegion=document.getElementById('t_region');\n"
        " var out=document.getElementById('t_out');\n"
        " function money(n){return '\\u00a3'+Math.round(n).toLocaleString('en-GB');}\n"
        " function range(lo,hi){if(lo===hi)return money(lo);return money(lo)+' \\u2013 '+money(hi);}\n"
        " function calc(){\n"
        "  var n=parseInt(fSockets.value,10);if(isNaN(n)||n<1)n=1;if(n>40)n=40;fSockets.value=n;\n"
        "  var ct=fCharger.value, st=fSite.value, dno=fDno.value, region=fRegion.value;\n"
        "  var isDC=(ct==='dc50');\n"
        "  var hw=HW[ct], civ=CIVILS[st];\n"
        "  var dnoBand=(isDC?DNO_DC:DNO_AC)[dno];\n"
        "  var hwLo=n*hw[0], hwHi=n*hw[1];\n"
        "  var civLo=civ[0], civHi=civ[1];\n"
        "  var dnoLo=dnoBand[0], dnoHi=dnoBand[1];\n"
        "  var grossLo=hwLo+civLo+dnoLo, grossHi=hwHi+civHi+dnoHi;\n"
        "  var wcsEligible=!isDC && (st==='workplace'||st==='depot'||st==='mixed');\n"
        "  var wcsSockets=Math.min(n,40);\n"
        "  var wcsRaw=wcsEligible ? wcsSockets*PER_SOCKET : 0;\n"
        "  var wcsLo=wcsEligible ? Math.min(wcsRaw, Math.round(grossLo*0.75)) : 0;\n"
        "  var wcsHi=wcsEligible ? Math.min(wcsRaw, Math.round(grossHi*0.75)) : 0;\n"
        "  var depotEligible=(st==='depot');\n"
        "  var depotBaseLo=hwLo+civLo, depotBaseHi=hwHi+civHi;\n"
        "  var depotLo=depotEligible ? Math.min(Math.round(depotBaseLo*0.70), 1000000) : 0;\n"
        "  var depotHi=depotEligible ? Math.min(Math.round(depotBaseHi*0.70), 1000000) : 0;\n"
        "  var grantLo, grantHi, grantLabel;\n"
        "  if(depotEligible && depotLo>=wcsLo && depotHi>=wcsHi){\n"
        "   grantLo=depotLo; grantHi=depotHi; grantLabel='Depot Charging Scheme (70%, \\u00a31m cap)';\n"
        "  } else if(wcsEligible){\n"
        "   grantLo=wcsLo; grantHi=wcsHi;\n"
        "   grantLabel='Workplace Charging Scheme (\\u00a3'+PER_SOCKET+'/socket \\u00d7 '+wcsSockets+', 75% cap)';\n"
        "  } else { grantLo=0; grantHi=0; grantLabel=null; }\n"
        "  var netLo=Math.max(0,grossLo-grantLo), netHi=Math.max(0,grossHi-grantHi);\n"
        "  var grantsHtml='<div class=\"tool-grants\">';\n"
        "  grantsHtml+='<div class=\"g'+(wcsEligible?'':' muted')+'\"><b>Workplace Charging Scheme \\u2014 '+(wcsEligible?'eligible':'not eligible for this site type')+'</b><span>'+(wcsEligible ? ('Up to \\u00a3'+PER_SOCKET+'/socket \\u00d7 '+wcsSockets+' = '+money(wcsRaw)+', capped at 75% of total cost. Maximum claim against this project: '+range(wcsLo,wcsHi)+'.') : (st==='public' ? 'Public-access car parks aren\\u2019t eligible \\u2014 WCS is for off-street staff and fleet parking.' : (isDC ? 'WCS does not fund rapid DC chargers.' : 'This site type isn\\u2019t eligible.')))+'</span></div>';\n"
        "  grantsHtml+='<div class=\"g'+(depotEligible?'':' muted')+'\"><b>Depot Charging Scheme \\u2014 '+(depotEligible?'eligible (fleet depot)':'not eligible')+'</b><span>'+(depotEligible ? ('Funds 70% of chargepoints + civil works (trenching, cabling, electrical upgrades) up to \\u00a31 million per organisation. Indicative claim against this project: '+range(depotLo,depotHi)+'.') : 'Only commercial fleet depots qualify \\u2014 not workplaces, retail or mixed-use sites.')+'</span></div>';\n"
        "  grantsHtml+='</div>';\n"
        "  var rd=REG[region]||{count:0,slug:''};\n"
        "  var ctaHtml='';\n"
        "  if(rd.slug){\n"
        "   ctaHtml='<div class=\"tool-cta\"><div class=\"ctxt\">See <b>'+rd.count+' OZEV-authorised installers in '+region+'</b> who can quote a project of this size.</div><a class=\"btn btn-g\" href=\"/regions/'+rd.slug+'/\">Open '+region+' directory <span class=\"arrow\">\\u2192</span></a></div>';\n"
        "  }\n"
        "  var dnoExtra='';\n"
        "  if(dno==='unsure'){dnoExtra=' <span style=\"color:var(--mut2);font-size:12.5px\">(G99 notification only \\u2014 confirm with installer)</span>';}\n"
        "  else if(dno==='yes' && isDC){dnoExtra=' <span style=\"color:var(--mut2);font-size:12.5px\">(connection works; reinforcement socialised under Ofgem Access SCR)</span>';}\n"
        "  else if(dno==='yes'){dnoExtra=' <span style=\"color:var(--mut2);font-size:12.5px\">(LV connection works; reinforcement socialised under Ofgem Access SCR)</span>';}\n"
        "  var typeLbl={ac7:'7 kW AC',ac22:'22 kW AC',dc50:'50 kW DC rapid'}[ct];\n"
        "  var siteLbl={workplace:'workplace',depot:'fleet depot',public:'public car park',mixed:'mixed-use'}[st];\n"
        "  var html='';\n"
        "  html+='<div class=\"tool-row head\"><span>Cost line</span><span>Indicative range</span></div>';\n"
        "  html+='<div class=\"tool-row\"><span class=\"lbl\">Hardware + install \\u2014 '+n+' \\u00d7 '+typeLbl+'</span><span class=\"val\">'+range(hwLo,hwHi)+'</span></div>';\n"
        "  html+='<div class=\"tool-row\"><span class=\"lbl\">Site civils &amp; groundworks ('+siteLbl+')</span><span class=\"val\">'+range(civLo,civHi)+'</span></div>';\n"
        "  html+='<div class=\"tool-row\"><span class=\"lbl\">DNO grid works'+dnoExtra+'</span><span class=\"val\">'+range(dnoLo,dnoHi)+'</span></div>';\n"
        "  html+='<div class=\"tool-row\"><span class=\"lbl\"><strong>Gross project cost (before grant)</strong></span><span class=\"val\"><strong>'+range(grossLo,grossHi)+'</strong></span></div>';\n"
        "  if(grantLo>0||grantHi>0){html+='<div class=\"tool-row\"><span class=\"lbl\">Grant applied: '+grantLabel+'</span><span class=\"val pos\">\\u2212'+range(grantLo,grantHi)+'</span></div>';}\n"
        "  html+='<div class=\"tool-net\"><span class=\"nlbl\">Estimated net cost after grants</span><span class=\"nval\">'+range(netLo,netHi)+'</span></div>';\n"
        "  html+=grantsHtml; html+=ctaHtml;\n"
        "  out.innerHTML=html;\n"
        " }\n"
        " [fSockets,fCharger,fSite,fDno,fRegion].forEach(function(el){el.addEventListener('input',calc);el.addEventListener('change',calc);});\n"
        " calc();\n"
        "})();\n"
        "</script>"
    )

    return (
        head("EV Charger Installation Cost & Grant Calculator UK (2026)",
             "Free UK calculator: estimate commercial EV charger installation cost, "
             "DNO upgrade, Workplace Charging Scheme grant (£500/socket from April 2026) "
             "and Depot Charging Scheme. Indicative ranges from 2026 public data.",
             url, jsonld)
        + navbar()
        + f"<style>{tool_css}</style>"
        + body
        + footer()
        + SHORTLIST_JS
        + js
        + "</body></html>"
    )


GLOSSARY_TERMS = [
    # (id, term, acronym/expansion or None, category, definition_html)
    # Grants & compliance
    ("wcs", "WCS", "Workplace Charging Scheme", "Grants & compliance",
     'A UK government voucher scheme administered by OZEV that contributes up to '
     '£500 per socket (raised from £350 on 1 April 2026) toward the up-front cost '
     'of EV charging sockets at workplaces, capped at 75% of project cost and 40 '
     'sockets per applicant. Closes to new applications on 31 March 2027. '
     'Applications must be made through an OZEV-authorised installer. '
     'See the <a href="/guides/workplace-charging-scheme/">WCS guide</a>.'),
    ("depot-charging-scheme", "Depot Charging Scheme", None, "Grants & compliance",
     'The 2026 successor scheme to the EV Infrastructure Grant, intended for '
     'commercial vehicle depots (vans, HGVs, buses). Funds up to 70% of eligible '
     'depot charging infrastructure costs. Applicants apply through an '
     'OZEV-authorised installer. See the <a href="/guides/ev-infrastructure-grant/">'
     'EV Infrastructure Grant / Depot Charging Scheme guide</a>.'),
    ("ev-infrastructure-grant", "EV Infrastructure Grant", None, "Grants & compliance",
     'A grant funding up to 75% of the cost of infrastructure works (cabling, '
     'groundworks) to support EV chargepoints for small and medium-sized businesses. '
     'Closed to new applicants on 31 March 2026 and superseded by the Depot Charging '
     'Scheme. See the <a href="/guides/ev-infrastructure-grant/">infrastructure '
     'grant guide</a>.'),
    ("ozev", "OZEV", "Office for Zero Emission Vehicles", "Grants & compliance",
     'The cross-Whitehall UK government team (sitting jointly within DfT and DESNZ) '
     'responsible for EV and ultra-low-emission vehicle policy and grant schemes. '
     'OZEV authorises installers for grant work, runs the WCS and Depot Charging '
     'Scheme, and publishes the public installer register this directory is built '
     'from.'),
    ("ozev-authorised-installer", "OZEV-authorised installer", None,
     "Grants & compliance",
     'A company on the public OZEV register, permitted to carry out grant-funded '
     'commercial EV chargepoint installations. Authorisation is a prerequisite for '
     'claiming WCS and Depot Charging Scheme funding. Every business listed in '
     'this directory is an OZEV-authorised installer.'),
    ("plug-in-van-grant", "Plug-in Van Grant", None, "Grants & compliance",
     'A separate vehicle-side grant (not a chargepoint grant) that reduces the '
     'purchase price of eligible electric vans and small trucks. Relevant to '
     'depot operators because van procurement and depot charging are usually '
     'planned together.'),
    ("part-s", "Building Regulations Part S", None, "Grants & compliance",
     'The section of the Building Regulations for England (in force since June '
     '2022) requiring EV chargepoint provision in new and materially-renovated '
     'buildings, including most new non-residential buildings with associated '
     'parking. Drives a large share of new commercial install demand.'),
    ("ev-ready", "EV-ready", None, "Grants & compliance",
     'An informal term for a car park or site where ducting, cable routes and '
     'spare electrical capacity have been installed so future EV chargepoints '
     'can be added without civils works. Often cheapest done at the time of an '
     'unrelated resurface or build, before <a href="#part-s">Part S</a> forces it.'),
    # Hardware
    ("ac-charger", "AC charger", None, "Hardware",
     'A chargepoint that delivers alternating current to the vehicle; the '
     'vehicle\'s onboard charger converts it to DC for the battery. Typical '
     'commercial AC units are 7 kW (single-phase) or 22 kW (three-phase). '
     'Cheaper, slower, and the workhorse of '
     '<a href="#workplace">workplace</a> and <a href="#destination-charging">'
     'destination</a> charging.'),
    ("dc-rapid", "DC rapid", None, "Hardware",
     'A chargepoint that supplies direct current straight to the battery, '
     'bypassing the vehicle\'s small onboard AC charger. Typically 50–150 kW. '
     'Used where dwell time is short — depot turn-around, en-route, taxi ranks.'),
    ("dc-ultra-rapid", "DC ultra-rapid", None, "Hardware",
     '150 kW and above DC chargepoints, increasingly 300–400 kW for HGVs and '
     'long-distance cars. Requires substantial grid capacity and almost always '
     'triggers a <a href="#g99">G99</a> DNO application.'),
    ("ccs2", "CCS2", "Combined Charging System (Type 2)", "Hardware",
     'The standard DC fast/rapid connector used in Europe and the UK, combining '
     'a Type 2 AC inlet with two extra DC pins. Effectively the default DC '
     'connector on new commercial rapid chargers.'),
    ("chademo", "CHAdeMO", None, "Hardware",
     'An older Japanese DC rapid charging standard, still found on some Nissan '
     'and Mitsubishi vehicles. New commercial sites usually fit CCS2 as '
     'default and CHAdeMO only if the user mix demands it.'),
    ("type-2", "Type 2", "IEC 62196-2", "Hardware",
     'The standard AC connector used across the UK and EU for AC charging at '
     '3–22 kW. Tethered Type 2 cables are common on workplace units; untethered '
     '(socketed) Type 2 lets drivers use their own cable.'),
    ("tethered", "Tethered vs untethered", None, "Hardware",
     'Tethered chargers have a captive cable; untethered (socketed) chargers '
     'require the driver to bring their own. Workplace and fleet sites often '
     'prefer tethered for user simplicity; public-access and shared bays often '
     'prefer untethered to handle mixed vehicles and reduce vandalism.'),
    ("ocpp", "OCPP", "Open Charge Point Protocol", "Hardware",
     'An open communication standard between chargepoints and back-office '
     'management software. OCPP 1.6 is widely deployed; 2.0.1 adds smart '
     'charging and ISO 15118 support. Specifying OCPP means a site is not '
     'locked into one back-office vendor.'),
    ("iso-15118", "ISO 15118", None, "Hardware",
     'An international standard covering vehicle-to-charger communication, '
     'including Plug & Charge (automatic identification and billing on plug-in) '
     'and vehicle-to-grid (V2G). Underpins smart-charging features on newer '
     'commercial hardware.'),
    ("smart-charging", "Smart charging", None, "Hardware",
     'Controlling when and how fast each vehicle charges based on grid signals, '
     'tariffs, on-site generation or user need. Mandatory in the UK for most '
     'new chargepoints under the Smart Charge Point Regulations 2021. Essential '
     'for depot economics and grid headroom.'),
    ("load-balancing", "Load balancing", None, "Hardware",
     'Dynamically sharing a fixed electrical supply between multiple chargers '
     'so the site never exceeds its grid limit. Lets a site install more sockets '
     'than its raw kVA would suggest — central to depot design and often the '
     'difference between needing or avoiding a <a href="#g99">G99</a> upgrade.'),
    ("rfid", "RFID", "Radio-Frequency Identification", "Hardware",
     'Card or fob-based driver authentication on a chargepoint, linking a '
     'session to a user or fleet account in the back-office. The cheap, '
     'reliable access-control default for workplace and depot sites.'),
    ("mode-3", "Mode 3", None, "Hardware",
     'The IEC 61851 charging mode covering AC chargepoints with a dedicated '
     'control pilot circuit — i.e. every standard Type 2 commercial AC charger. '
     'Distinguished from Mode 1/2 (domestic socket adaptors, not used commercially).'),
    ("mode-4", "Mode 4", None, "Hardware",
     'The IEC 61851 charging mode covering DC rapid/ultra-rapid charging, where '
     'the charger itself contains the AC-to-DC rectifier and communicates digitally '
     'with the vehicle. All commercial DC chargers are Mode 4.'),
    # Electrical / civils
    ("dno", "DNO", "Distribution Network Operator", "Electrical & civils",
     'The regional company that owns and operates the local electricity '
     'distribution network — UK Power Networks, SSEN, National Grid Electricity '
     'Distribution, NIE, etc. Any meaningful commercial EV install requires a '
     'DNO notification (<a href="#g98">G98</a>) or application '
     '(<a href="#g99">G99</a>).'),
    ("g99", "G99", None, "Electrical & civils",
     'The Energy Networks Association Engineering Recommendation governing the '
     'connection of generation and larger demand (including most rapid/ultra-rapid '
     'chargepoints) to the distribution network. G99 applications can take '
     'weeks to months and may trigger reinforcement costs — they are the most '
     'common cause of commercial install delay.'),
    ("g98", "G98", None, "Electrical & civils",
     'The lighter-touch ENA recommendation for small connections — typically '
     'up to 16 A per phase per site. Most single AC workplace chargers fall '
     'under G98 and need only a notification rather than a full application.'),
    ("kva", "kVA", "kilovolt-ampere", "Electrical & civils",
     'The unit of apparent electrical power used when specifying supplies and '
     'transformer capacity. A site\'s available kVA, minus existing demand, sets '
     'the ceiling on how much charging it can host without a fuse upgrade or '
     '<a href="#g99">G99</a> application.'),
    ("three-phase", "Three-phase", None, "Electrical & civils",
     'A 400 V supply delivered over three live conductors, standard for '
     'commercial sites. Required for 22 kW AC and most DC chargers; lets a site '
     'host higher-power charging in the same footprint as a single-phase install.'),
    ("single-phase", "Single-phase", None, "Electrical & civils",
     'A 230 V supply over one live conductor, standard at most homes and small '
     'shops. Caps AC charging at around 7 kW per socket. Many small commercial '
     'sites are single-phase, which constrains charger choice.'),
    ("load-study", "Load study", None, "Electrical & civils",
     'A measurement and modelling exercise — usually a few weeks of half-hourly '
     'metering — that establishes a site\'s real available capacity and '
     'utilisation pattern before specifying chargers. Often pays for itself by '
     'avoiding an unnecessary DNO upgrade.'),
    ("lv-hv", "LV / HV", "Low Voltage / High Voltage", "Electrical & civils",
     'In UK distribution, LV usually means up to 1 kV (the standard 400/230 V '
     'mains seen at most sites); HV is 1 kV–132 kV. Larger depots, hub sites '
     'and ultra-rapid installations may require an HV connection or a private '
     'substation.'),
    ("fuse-upgrade", "Fuse upgrade", None, "Electrical & civils",
     'Replacing the main service fuse on an LV connection with a higher-rated '
     'one (e.g. 60 A to 100 A), increasing the site\'s import capacity. Carried '
     'out by the DNO, often at modest cost — the cheapest route to more charging '
     'capacity when it is available.'),
    ("mpan", "MPAN", "Meter Point Administration Number", "Electrical & civils",
     'The 13-digit reference identifying an electricity supply point. Required '
     'for every DNO application, tariff change and back-office configuration. '
     'A single site may have several MPANs (one per metered supply).'),
    ("half-hourly-metering", "Half-hourly (HH) metering", None,
     "Electrical & civils",
     'Electricity metering that records consumption in 30-minute blocks, '
     'mandatory above 100 kW maximum demand and optional below. Underpins '
     'time-of-use tariffs, smart-charging optimisation and accurate site '
     'load studies.'),
    ("civils", "Civils", None, "Electrical & civils",
     'Trenching, ducting, bay marking, surfacing reinstatement and bollard '
     'fitting — i.e. the groundworks portion of an EV install, as distinct '
     'from electrical and chargepoint hardware. Routinely 20–40% of total '
     'project cost and the line most likely to surprise.'),
    ("ducting", "Ducting", None, "Electrical & civils",
     'The plastic conduit buried during civils to carry cabling between the '
     'incoming supply, sub-distribution and each chargepoint. Over-specifying '
     'duct count at first install is the cheapest way to make a site '
     '<a href="#ev-ready">EV-ready</a> for future expansion.'),
    ("bollard-protection", "Bollard protection", None, "Electrical & civils",
     'Steel bollards (or wheel stops + integrated unit) protecting pedestal '
     'chargepoints from vehicle impact. Effectively mandatory under most '
     'site insurance terms and good-practice guidance for commercial bays.'),
    # Commercial
    ("cpo", "CPO", "Charge Point Operator", "Commercial",
     'A business that operates and maintains chargepoints day-to-day — '
     'monitoring uptime, handling driver payments, resolving faults. A site '
     'owner may be their own CPO, or contract a third-party CPO under '
     'concession or charging-as-a-service.'),
    ("back-office", "Back-office", None, "Commercial",
     'The cloud software that monitors chargepoints, authenticates users, '
     'meters sessions, calculates billing and surfaces fault data. Choice of '
     'back-office is at least as important as choice of hardware — and '
     '<a href="#ocpp">OCPP</a> compliance lets the two be chosen independently.'),
    ("tariff", "Tariff", None, "Commercial",
     'The pricing structure a CPO charges drivers (or a site charges users): '
     'pence per kWh, time-based, idle-fees, or a hybrid. For depot fleets, '
     'the relevant tariff is usually the wholesale electricity tariff plus '
     'time-of-use shaping rather than a public CPO tariff.'),
    ("fleet-operator", "Fleet operator", None, "Commercial",
     'A business running its own vehicles — vans, HGVs, company cars, taxis. '
     'Typically charges at a depot overnight and tops up en-route. See the '
     '<a href="/services/fleet-charging-installers/">fleet charging installers</a> '
     'list and the <a href="/guides/ev-charging-for-fleets/">fleet guide</a>.'),
    ("depot", "Depot", None, "Commercial",
     'A site where commercial vehicles return to base — typical of logistics, '
     'bus, taxi, council and trade fleets. Optimal for cheap overnight '
     'charging with <a href="#load-balancing">load balancing</a>, and the '
     'core target of the <a href="#depot-charging-scheme">Depot Charging Scheme</a>.'),
    ("workplace", "Workplace charging", None, "Commercial",
     'Chargepoints provided in staff or visitor car parks. Eligible for '
     'the <a href="#wcs">WCS</a> at up to £500 per socket. See '
     '<a href="/services/workplace-charging-installers/">workplace installers</a>.'),
    ("destination-charging", "Destination charging", None, "Commercial",
     'Chargepoints at places people stop for a non-charging reason — hotels, '
     'retail, leisure, hospitality — where the vehicle is parked for hours. '
     'AC 7–22 kW is usually the right fit; ultra-rapid is wasted on a '
     'two-hour dwell.'),
    ("en-route", "En-route charging", None, "Commercial",
     'High-power public DC charging on or near strategic roads, used during '
     'a journey. Dwell time is 10–40 minutes; ultra-rapid DC and strong grid '
     'capacity are essential.'),
    ("dwell-time", "Dwell time", None, "Commercial",
     'How long a vehicle is parked at a chargepoint. The single most important '
     'input into specifying charger power: long dwell = AC; short dwell = DC '
     'rapid; very short dwell = DC ultra-rapid.'),
    ("utilisation-rate", "Utilisation rate", None, "Commercial",
     'The proportion of a chargepoint\'s available hours during which it is '
     'delivering energy. Drives the payback on any public or commercial '
     'install — typical break-even on rapid DC sits in the 12–25% range '
     'depending on tariff and capex.'),
    ("payback-period", "Payback period", None, "Commercial",
     'The years until net savings (fuel + grant + chargepoint revenue) equal '
     'the project capex. Depot retrofits often pay back in 3–6 years on '
     'fuel saving alone; public installs depend heavily on '
     '<a href="#utilisation-rate">utilisation</a>. The '
     '<a href="/tools/ev-charger-cost-calculator/">cost calculator</a> '
     'gives an indicative figure.'),
]


def page_glossary():
    """Comprehensive UK commercial EV-charging glossary.

    Doubles as a strong internal-linking hub: each entry can link to the
    relevant guide, service or industry page. Emits DefinedTermSet JSON-LD
    plus a BreadcrumbList for discoverability.
    """
    url = f"{BASE_URL}/glossary/"
    title = ("EV Charging Glossary (UK, 2026) — Grants, Hardware, "
             "Electrical & Commercial Terms")
    desc = ("Plain-English UK commercial EV charging glossary: OZEV, WCS, "
            "Depot Charging Scheme, G99, OCPP, CCS2, kVA, load balancing, "
            "CPO and more — defined with links to the relevant guides.")

    # Build alphabetical jump-nav
    by_letter: dict[str, list] = {}
    for entry in GLOSSARY_TERMS:
        first = entry[1][0].upper()
        by_letter.setdefault(first, []).append(entry)
    letters_present = sorted(by_letter.keys())
    jump_nav = " ".join(
        f'<a href="#letter-{l}" style="display:inline-block;padding:4px 9px;'
        f'margin:2px;border:1px solid var(--bd-l);border-radius:6px;'
        f'color:var(--green-d);font-weight:700;font-size:14px">{l}</a>'
        for l in letters_present
    )
    # All A-Z letters (faded if absent) for a complete bar
    all_letters_bar = " ".join(
        (f'<a href="#letter-{l}" style="display:inline-block;padding:4px 9px;'
         f'margin:2px;border:1px solid var(--bd-l);border-radius:6px;'
         f'color:var(--green-d);font-weight:700;font-size:14px;text-decoration:none">{l}</a>'
         if l in by_letter else
         f'<span style="display:inline-block;padding:4px 9px;margin:2px;'
         f'border:1px solid var(--bd-l);border-radius:6px;color:#bbb;'
         f'font-weight:700;font-size:14px">{l}</span>')
        for l in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )

    # Group by category for readable presentation
    cats: dict[str, list] = {}
    for entry in GLOSSARY_TERMS:
        cats.setdefault(entry[3], []).append(entry)
    cat_order = ["Grants & compliance", "Hardware", "Electrical & civils",
                 "Commercial"]

    sections = []
    seen_letters = set()
    for cat in cat_order:
        items = cats.get(cat, [])
        if not items:
            continue
        # Sort within category alphabetically by term
        items_sorted = sorted(items, key=lambda e: e[1].lower())
        dts = []
        for tid, term, acronym, _, defn in items_sorted:
            first_letter = term[0].upper()
            anchor_extra = ""
            if first_letter not in seen_letters:
                anchor_extra = f'<span id="letter-{first_letter}"></span>'
                seen_letters.add(first_letter)
            acro_html = (f' <span style="color:var(--mut);font-weight:500;'
                         f'font-size:15px">— {esc(acronym)}</span>'
                         if acronym else "")
            dts.append(
                f'{anchor_extra}<dt id="{tid}" style="font-weight:800;'
                f'font-size:18px;margin-top:18px;scroll-margin-top:80px">'
                f'<a href="#{tid}" style="color:var(--ink);text-decoration:none">'
                f'{esc(term)}</a>{acro_html}</dt>'
                f'<dd style="margin:6px 0 0;color:var(--ink);font-size:16px;'
                f'line-height:1.55">{defn}</dd>'
            )
        sections.append(
            f'<h2 id="cat-{slugify(cat)}">{esc(cat)}</h2>'
            f'<dl style="margin:0 0 30px 0">{"".join(dts)}</dl>'
        )

    # DefinedTermSet JSON-LD
    defined_terms = [
        {
            "@type": "DefinedTerm",
            "@id": f"{BASE_URL}/glossary/#{tid}",
            "name": term + (f" ({acronym})" if acronym else ""),
            "description": _strip_tags(defn),
            "inDefinedTermSet": f"{BASE_URL}/glossary/",
            "termCode": tid,
        }
        for (tid, term, acronym, _cat, defn) in GLOSSARY_TERMS
    ]
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org",
        "@type": "DefinedTermSet",
        "@id": f"{BASE_URL}/glossary/",
        "name": "UK Commercial EV Charging Glossary",
        "url": url,
        "inLanguage": "en-GB",
        "publisher": {"@type": "Organization", "name": SITE_NAME,
                      "url": BASE_URL},
        "hasDefinedTerm": defined_terms,
    }) + "</script>") + breadcrumb_jsonld([
        ("Home", "/"),
        ("Glossary", "/glossary/"),
    ])

    intro = f"""
<p class="upd">UK commercial EV charging terms, plain-English. Last updated {TODAY}.</p>
<p>If you're scoping a workplace, depot or destination EV charging project for the
first time, the acronyms come at you fast — OZEV, WCS, G99, OCPP, CCS2, kVA. This
glossary defines the {len(GLOSSARY_TERMS)} terms you'll meet in installer quotes,
DNO correspondence and grant paperwork, with links through to the relevant
<a href="/guides/ev-charging-for-fleets/">guides</a> and
<a href="/#directory">installer directory</a>.</p>

<div class="box" style="margin:18px 0 24px 0">
<strong>Jump to a letter:</strong><br>
<div style="margin-top:8px">{all_letters_bar}</div>
</div>

<p style="font-size:14px;color:var(--mut)"><strong>Categories:</strong>
<a href="#cat-grants-compliance" style="color:var(--green-d)">Grants &amp; compliance</a> ·
<a href="#cat-hardware" style="color:var(--green-d)">Hardware</a> ·
<a href="#cat-electrical-civils" style="color:var(--green-d)">Electrical &amp; civils</a> ·
<a href="#cat-commercial" style="color:var(--green-d)">Commercial</a></p>
"""

    body = intro + "".join(sections) + (
        '<h2>See also</h2><ul>'
        '<li><a href="/guides/ev-charging-for-fleets/" style="color:var(--green-d)">'
        'EV charging for fleets — buyer\'s guide</a></li>'
        '<li><a href="/guides/workplace-charging-scheme/" style="color:var(--green-d)">'
        'Workplace Charging Scheme guide</a></li>'
        '<li><a href="/guides/ev-infrastructure-grant/" style="color:var(--green-d)">'
        'EV Infrastructure Grant / Depot Charging Scheme</a></li>'
        '<li><a href="/guides/grant-deadlines/" style="color:var(--green-d)">'
        'UK EV grant deadlines</a></li>'
        '<li><a href="/tools/ev-charger-cost-calculator/" style="color:var(--green-d)">'
        'Cost &amp; grant calculator</a></li>'
        '<li><a href="/methodology/" style="color:var(--green-d)">'
        'How this directory is built (methodology)</a></li>'
        '</ul>'
    )

    return (head(title, desc, url, jsonld) + navbar()
            + '<section style="padding-top:30px"><div class="wrap prose">'
            + f'<h1>UK Commercial EV Charging Glossary</h1>'
            + body
            + '</div></section>'
            + footer() + SHORTLIST_JS + "</body></html>")


def _strip_tags(html: str) -> str:
    """Very small HTML-tag stripper used for JSON-LD descriptions."""
    import re as _re
    return _re.sub(r"<[^>]+>", "", html).replace("&amp;", "&").strip()


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
            "/about/", "/contact/", "/privacy/", "/methodology/",
            "/glossary/"]
    write(DIST / "index.html", page_index(installers))
    write(DIST / "calculator" / "index.html", page_calculator())
    write(DIST / "tools" / "uk-ev-grant-eligibility" / "index.html",
          page_grant_wizard())
    urls.append("/tools/uk-ev-grant-eligibility/")
    write(DIST / "tools" / "ev-charger-cost-calculator" / "index.html",
          page_cost_calculator_tool(installers))
    urls.append("/tools/ev-charger-cost-calculator/")
    write(DIST / "map" / "index.html", page_map())
    write(DIST / "map-data.js", map_data_js(installers))
    write(DIST / "data" / "uk-ev-installer-landscape" / "index.html",
          page_data_landscape(installers, stats))
    # Dated May 2026 snapshot — pitchable to trade press, separate URL.
    write(DIST / "data" / SNAPSHOT_SLUG / "index.html",
          page_data_landscape_snapshot(installers, towns))
    urls.append(f"/data/{SNAPSHOT_SLUG}/")
    # Open-data downloads referenced by the snapshot page's "use this data".
    _write_public_open_data(installers)
    write(DIST / "glossary" / "index.html", page_glossary())
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

    for slug, spec in SERVICES.items():
        write(DIST / "services" / slug / "index.html",
              page_service(slug, spec, installers))
        urls.append(f"/services/{slug}/")

    for slug, spec in INDUSTRIES.items():
        write(DIST / "industries" / slug / "index.html",
              page_industry(slug, spec, installers))
        urls.append(f"/industries/{slug}/")

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

    methodology_jsonld = (
        '<script type="application/ld+json">' + json.dumps({
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": "UK OZEV-Authorised Commercial EV Charger Installers",
            "description": (
                "Directory of OZEV-authorised installers offering commercial / "
                "fleet electric vehicle chargepoint installations across the UK, "
                "derived from the public GOV.UK OZEV authorised-installer tool."),
            "url": f"{BASE_URL}/data/uk-ev-installer-landscape/",
            "isAccessibleForFree": True,
            "license": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
            "creator": {"@type": "Organization", "name": SITE_NAME,
                        "url": BASE_URL},
            "publisher": {"@type": "Organization", "name": SITE_NAME,
                          "url": BASE_URL},
            "sourceOrganization": {
                "@type": "GovernmentOrganization",
                "name": "Office for Zero Emission Vehicles (OZEV) / GOV.UK",
                "url": "https://www.gov.uk/electric-vehicle-chargepoint-installers",
            },
            "version": TODAY,
            "dateModified": TODAY,
            "spatialCoverage": {"@type": "Place", "name": "United Kingdom"},
            "inLanguage": "en-GB",
            "keywords": ["EV charging", "OZEV", "commercial installers",
                         "fleet charging", "UK", "OGL v3.0"],
            "distribution": [
                {
                    "@type": "DataDownload",
                    "encodingFormat": "application/json",
                    "contentUrl": f"{BASE_URL}/data/installers.json",
                    "name": "Installers JSON",
                },
            ],
        }, ensure_ascii=False) + "</script>"
        + breadcrumb_jsonld([("Home", "/"),
                             ("Methodology", "/methodology/")])
    )

    # Hand-built methodology page (avoid page_simple so we can inject the
    # Dataset JSON-LD into <head>).
    methodology_body = f"""<p class="upd">Last refreshed <strong>{TODAY}</strong>
· Source: <a style="color:var(--green-d)"
href="https://www.gov.uk/electric-vehicle-chargepoint-installers">GOV.UK OZEV
authorised-installer tool</a>.</p>

<p>This page documents — for journalists, sponsors, partner installers and any
researcher reusing our derived statistics — exactly how the {len(installers)}
listings and the figures on the <a style="color:var(--green-d)"
href="/data/uk-ev-installer-landscape/">UK EV installer landscape</a> page are
produced. If anything below is wrong or unclear, please
<a style="color:var(--green-d)" href="/contact/">tell us</a> and we will fix it
on the next rebuild.</p>

<h2>1. Where the installer list comes from</h2>
<p>The single upstream source is the public GOV.UK / Office for Zero Emission
Vehicles (OZEV) authorised-installer tool:
<a style="color:var(--green-d)"
href="https://www.gov.uk/electric-vehicle-chargepoint-installers">
https://www.gov.uk/electric-vehicle-chargepoint-installers</a>. Every business
on this site is an OZEV-authorised installer that has self-declared (to OZEV) a
willingness to carry out commercial installations. We do not include any
installer that is not on that register.</p>

<h2>2. Last refresh date</h2>
<p>The data underpinning this build was last refreshed on
<strong>{TODAY}</strong>. A refresh date is also stamped into the footer of
every page and into the <code>generated_at</code> field of
<a style="color:var(--green-d)" href="/data/installers.json">installers.json</a>.</p>

<h2>3. Collection</h2>
<p>The OZEV tool is queried across a UK-wide postcode grid (covering all 12
nations / English regions). Requests are rate-limited and respectful (the
collection runs at a fraction of the throughput a human user would generate)
and use a UA string identifying this project so OZEV / GDS can contact us if
needed.</p>

<h2>4. Normalisation</h2>
<p>Raw OZEV records are normalised at build time:</p>
<ul>
<li>Trading name is collapsed to a single canonical string (whitespace, casing,
trailing &quot;Ltd&quot; / &quot;Limited&quot; variations).</li>
<li>Postcodes are uppercased and re-spaced to the standard UK format.</li>
<li>Towns are mapped to one of 12 UK regions using ONS region boundaries; an
installer whose postcode does not resolve is flagged <code>N/A</code> rather
than guessed.</li>
<li>Phone numbers are E.164-normalised and the primary contact number is
preferred over fax / personal mobile where multiple are present.</li>
<li>A stable, collision-safe URL slug is assigned per installer and reused
across rebuilds.</li>
<li>Records are de-duplicated on a (normalised name + postcode) key.</li>
</ul>

<h2>5. Accuracy rule — no fabrication</h2>
<p>If a field is not present in the OZEV source, it is shown as
&quot;Not listed&quot; or omitted entirely. We never infer, guess or fill in a
missing website, phone number or service category. Stats and counts shown on
the data landscape page are computed directly from the normalised dataset and
nowhere else.</p>

<h2>6. How updates happen</h2>
<p>The pipeline (<code>pipeline/extract.py</code> → <code>site/generate.py</code>)
runs automatically on a <strong>weekly</strong> cadence. Each run regenerates
<code>data/installers.json</code> and rebuilds every page from scratch — no
manual editing of listings is possible after publish. The refresh date in the
footer is set programmatically from the build clock.</p>

<h2>7. Known limitations</h2>
<ul>
<li><strong>OZEV does not sub-categorise commercial installers.</strong> The
register flags whether an installer offers commercial work, but does not split
that into &quot;fleet depot&quot; vs &quot;workplace&quot; vs &quot;public
destination&quot;. Our service-pages (e.g. <a style="color:var(--green-d)"
href="/services/fleet-charging-installers/">fleet charging installers</a>) all
draw from the same single commercial-flagged pool. Buyers should still confirm
suitability with each installer directly.</li>
<li>OZEV authorisation reflects what an installer is permitted to do, not
their current workload, project portfolio or geographic operating area. A
small installer on the register may not actually serve every postcode in their
nominal region.</li>
<li>The OZEV register is itself self-declared (with light spot-checking).
Where a listing looks inaccurate we accept correction requests via the
<a style="color:var(--green-d)" href="/contact/">contact page</a>; we do not
overwrite OZEV's data, but we can suppress an entry.</li>
<li>Cost figures and grant rates quoted in our guides come from GOV.UK / OZEV /
Ofgem / IET publications and are cited inline; they are not derived from this
dataset.</li>
</ul>

<h2>8. Reporting an error</h2>
<p>Spot a mistake — wrong town, dead website, listing that shouldn&apos;t be
here? Email
<a style="color:var(--green-d)" href="mailto:{esc(CONTACT_EMAIL)}">
{esc(CONTACT_EMAIL)}</a> or use the
<a style="color:var(--green-d)" href="/contact/">contact page</a>. Corrections
and removals are actioned on the next rebuild, with no questions asked.</p>

<h2>9. Data licence</h2>
<p>The upstream OZEV data is reused under the
<a style="color:var(--green-d)"
href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">
Open Government Licence v3.0</a>. Our derived statistics, normalisations and
counts (everything on this site that is not the raw OZEV record) are released
under the same OGL v3.0 — free to reuse with attribution. Suggested citation:
&quot;{esc(SITE_NAME)}, derived from GOV.UK OZEV authorised-installer data
under OGL v3.0, refreshed {TODAY}&quot;.</p>

<h2>10. Privacy stance</h2>
<p>We deliberately do <strong>not</strong> publish scraped personal
(<code>firstname.lastname@</code>) or free-webmail email addresses as
clickable links — a privacy choice taken under UK GDPR (lawful basis:
legitimate interests, balanced against the limited and already-public nature
of the OZEV business data) and PECR. Where only a personal email exists in the
source, we route enquiries via a generic &quot;request a quote&quot; flow
instead. Full detail is on the
<a style="color:var(--green-d)" href="/privacy/">privacy &amp; data page</a>.</p>

<h2>11. Data schema</h2>
<p>The public dataset is published as JSON at
<a style="color:var(--green-d)" href="/data/installers.json">
/data/installers.json</a>. The per-record shape is:</p>
<pre style="background:var(--light);border:1px solid var(--bd-l);
border-radius:10px;padding:14px;overflow-x:auto;font-size:13px;line-height:1.5">{{
  "name":      "Example EV Installations Ltd",
  "town":      "Manchester",
  "region":    "North West",
  "postcode":  "M1 1AA",
  "website":   "https://example.com",
  "phone":     "+441611234567",
  "email":     "info@example.com",          // generic mailbox only
  "services":  ["Commercial", "Residential"],
  "featured":  false,
  "_slug":     "example-ev-installations-m1"
}}</pre>
<p>Top-level payload also includes <code>count</code>,
<code>generated_at</code> (ISO 8601) and <code>licence</code>.</p>

<h2>12. Downloads</h2>
<ul>
<li><a style="color:var(--green-d)" href="/data/installers.json">
installers.json</a> — full public dataset (UTF-8, ~{len(installers)} records,
OGL v3.0).</li>
<li><a style="color:var(--green-d)" href="/sitemap.xml">sitemap.xml</a> —
every public URL on this site.</li>
</ul>

<p style="font-size:13px;color:var(--mut);margin-top:34px">
Methodology version: {TODAY}. Pipeline source: <code>pipeline/extract.py</code>,
<code>site/generate.py</code>. This page is rebuilt automatically on each
refresh — any inaccuracy is fixable; please flag it.</p>"""

    write(DIST / "methodology" / "index.html",
          head("Methodology & Data Transparency",
               "Exactly how this OZEV commercial EV installer dataset is "
               "built, refreshed, normalised, licensed (OGL v3.0) and "
               "published — including the data schema and known limitations.",
               f"{BASE_URL}/methodology/",
               methodology_jsonld)
          + navbar()
          + '<section style="padding-top:30px"><div class="wrap prose">'
          + '<h1>Methodology &amp; Data Transparency</h1>'
          + methodology_body
          + '</div></section>'
          + footer() + SHORTLIST_JS + "</body></html>")

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
                             "/data/uk-ev-installer-landscape/",
                             f"/data/{SNAPSHOT_SLUG}/") else
              "0.85" if u.startswith(("/services", "/industries")) else
              "0.8" if u.startswith(("/guides", "/towns")) else
              "0.7" if u == "/glossary/" else "0.6")
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


# ---------------------------------------------------------------------------
# Industry-vertical landing pages. Same OZEV-authorised commercial pool as
# /services/* — OZEV has no per-vertical sub-tag in its source data, so each
# industry page is honest about that and filters by Commercial only. Every
# external figure (Building Regs Part S in-force date, Greener NHS net-zero
# years, framework codes, scheme rates) is checked against public GOV.UK /
# regulator sources; no figure is invented for a vertical.
# ---------------------------------------------------------------------------
INDUSTRIES = {
    "hotels-hospitality": {
        "h1": "EV Charger Installers for UK Hotels & Hospitality",
        "audience": "hotels, restaurants, pubs with rooms and leisure venues",
        "title": "EV Charger Installers for UK Hotels — Verified Commercial Providers",
        "card_blurb": "Destination charging for guest car parks. WCS limits and CaaS realities, honestly.",
        "meta_desc": ("OZEV-authorised UK installers for hotel and hospitality "
                      "EV charging — destination charging for guests, with "
                      "Public Charge Point Regulations 2023 context. {n} "
                      "verified commercial installers."),
        "intro_html": (
            "<p>Hotel and hospitality EV charging is destination charging by "
            "another name: a guest plugs in at check-in and leaves charged at "
            "check-out. Dwell time is long (8–14 hours overnight, 1–3 hours at "
            "a restaurant or spa), which lets you specify cheaper AC hardware "
            "rather than rapid DC and still send the car away full. The "
            "commercial question is whether the bays are a guest amenity, a "
            "small revenue line, or both.</p>"
            "<p>The {n} installers on this page are all "
            "<strong>OZEV-authorised for commercial work</strong> on the "
            "public GOV.UK list. OZEV does not publish a hospitality "
            "sub-tag, so this page is filtered to every commercial "
            "OZEV-authorised installer; the right next step is to ask three "
            "shortlisted installers for a recent hotel or hospitality "
            "reference of similar scale.</p>"
            "<h2>Typical hotel and hospitality scope</h2>"
            "<ul>"
            "<li><strong>Destination AC, 7–22 kW</strong> — for overnight "
            "guests. 7 kW is usually plenty for a full charge over a stay; "
            "11 or 22 kW only helps where dwell time is shorter (lunch, "
            "spa-day, conferences).</li>"
            "<li><strong>A small number of 50 kW rapid bays</strong> — at "
            "roadside hotels and motorway-adjacent sites where the bays "
            "double as a coffee-stop revenue line for non-guests.</li>"
            "<li><strong>Branded EV-friendly listing</strong> — Tesla "
            "Destination, Zap-Map, hotel-chain apps. The installer scope "
            "should include how the bays appear in third-party apps if you "
            "want non-guest traffic.</li>"
            "</ul>"
            "<h2>The grant picture is awkward — be honest about it</h2>"
            "<p>The Workplace Charging Scheme (WCS) is restricted to "
            "<em>off-street staff and fleet parking</em>. Guest parking is "
            "explicitly not eligible. Some hotels qualify for WCS on the "
            "subset of bays reserved for staff (housekeeping, kitchen, "
            "duty managers) — but the customer-facing bays are commercially "
            "funded. The Depot Charging Scheme funds fleet depots, not "
            "hospitality. So for most hotels the project is a mix of "
            "capex and <em>charging-as-a-service</em> (CPO funds the "
            "hardware, shares revenue) — see the "
            "<a style=\"color:var(--green-d)\" "
            "href=\"/guides/ev-charger-installation-costs-uk/\">commercial "
            "EV charger installation costs</a> guide for what the maths "
            "actually looks like.</p>"
            "<h2>Buying questions a hotel should ask</h2>"
            "<ul>"
            "<li>Are the staff bays separable so we can claim WCS on those, "
            "and the guest bays sit under a separate commercial contract?</li>"
            "<li>Capex or charging-as-a-service? If CaaS, what is the "
            "revenue share, the term, and what happens at break clause?</li>"
            "<li>Will the bays accept contactless payment as required by the "
            "Public Charge Point Regulations 2023 for any public-access "
            "point of 8 kW or above?</li>"
            "<li>How are guest charges handled — folio billing, free with "
            "stay, or pay-as-you-go via the CPO app?</li>"
            "<li>Planning permission: is the site a listed building or in a "
            "conservation area, and is the bay layout within "
            "permitted-development rights?</li>"
            "</ul>"
            "<h2>Common pitfalls</h2>"
            "<ul>"
            "<li>Specifying 22 kW everywhere when a 14-hour overnight stay "
            "charges fine on 7 kW. Over-spec drives capex without "
            "improving guest experience.</li>"
            "<li>Putting all the bays in one row at the far end of the car "
            "park because that's where the supply is. Guests will not walk "
            "past 60 empty unbranded spaces to reach the EV bay; siting "
            "matters more than power.</li>"
            "<li>Signing a CaaS contract with a long exclusivity clause and "
            "no break, then losing flexibility when guest charging patterns "
            "change.</li>"
            "</ul>"),
        "faqs": [
            ("Can a hotel claim the Workplace Charging Scheme?",
             "Only for off-street bays reserved for staff and fleet — not for guest parking. Guest-facing bays are explicitly excluded from the WCS, which is restricted to staff and fleet parking under the scheme rules. Many hotels split the project so staff bays claim the grant and guest bays sit under a separate commercial contract."),
            ("Will I need planning permission for a hotel car-park installation?",
             "Most ground-mounted chargepoints in an existing off-street car park are covered by permitted development in England under The Town and Country Planning (General Permitted Development) (England) Order, subject to height and siting limits. Listed buildings, conservation areas and any upstand over the permitted height typically need a full application. A reputable installer scopes this before quoting."),
            ("Should we offer guest charging free with the room, or pay-per-use?",
             "Both are common. Free-with-stay is simpler operationally and avoids the Public Charge Point Regulations 2023 contactless requirement, because the bays are no longer public-access for payment purposes. Pay-per-use opens you to non-guest revenue but brings the regulations into scope at any point 8 kW or above."),
            ("What hardware fits a typical UK hotel car park?",
             "For overnight stays, 7 kW AC is usually sufficient and cheapest per socket. 22 kW AC is worth it only where dwell time is shorter (lunch, spa-day, daytime conferences). One or two 50 kW DC rapid bays are common at roadside or motorway-adjacent hotels for non-guest passing trade."),
            ("Is charging-as-a-service or capex better for a hotel?",
             "Depends on cost of capital, forecast utilisation and whether EV charging is core to the proposition. Capex retains the revenue and the asset; CaaS gives you no upfront cost in exchange for a revenue share and contract term. Many independent hotels go CaaS for guest bays and capex for staff bays."),
            ("How are EV bays reflected in third-party apps and booking sites?",
             "Listing in Zap-Map, the National Chargepoint Registry and the CPO's own app is normally part of the CaaS contract. Tesla Destination listing is separate and depends on installing Tesla wall connectors alongside any open AC bays."),
        ],
        "related_services": [
            "public-car-park-ev-installers",
            "workplace-charging-installers",
            "fleet-charging-installers",
        ],
    },
    "logistics-haulage": {
        "h1": "EV Charger Installers for UK Logistics & Haulage Depots",
        "audience": "logistics operators, haulage firms, parcel and last-mile fleets",
        "title": "EV Charger Installers for UK Logistics & Haulage — Verified Commercial Providers",
        "card_blurb": "Fleet depots and HGV charging. Depot Charging Scheme (70%, up to £1m) front-and-centre.",
        "meta_desc": ("OZEV-authorised UK installers for logistics and haulage "
                      "depot EV charging. Depot Charging Scheme (70% funded, "
                      "up to £1m) front-and-centre. {n} verified commercial "
                      "installers."),
        "intro_html": (
            "<p>Logistics and haulage depots are where the Depot Charging "
            "Scheme was aimed: zero-emission HGVs, vans and coaches charging "
            "between duty cycles, on private land, with electrical demand "
            "that makes the DNO connection the single biggest project risk. "
            "The maths only works if grant claim, supply scoping and "
            "operational duty cycles are designed together — not bolted "
            "together afterwards.</p>"
            "<p>The {n} installers on this page are all "
            "<strong>OZEV-authorised for commercial work</strong> on the "
            "public GOV.UK list. OZEV does not publish a depot or HGV "
            "sub-tag, so the right next step is to ask each shortlisted "
            "installer for a recent depot reference of similar power and "
            "socket count.</p>"
            "<h2>Typical logistics depot scope</h2>"
            "<ul>"
            "<li><strong>AC overnight bays, 7–22 kW</strong> — for vans and "
            "smaller commercial vehicles returning to base on a single duty "
            "cycle. Load management is essential: 30 vans at 11 kW unmanaged "
            "is 330 kW of peak demand.</li>"
            "<li><strong>DC rapid bays, 50–150 kW</strong> — for HGVs, "
            "coaches and back-to-back van duty cycles. Almost always "
            "triggers a G99 connection application and DNO reinforcement.</li>"
            "<li><strong>HV connection and transformer compound</strong> — "
            "anything above ~200 kW of installed capacity usually means a "
            "new 11 kV supply, transformer pad and metered substation.</li>"
            "</ul>"
            "<h2>Depot Charging Scheme — the headline rules</h2>"
            "<ul>"
            "<li>70% of <strong>chargepoint and civil costs</strong> "
            "(trenching, cabling, electrical upgrades), capped at £1m per "
            "organisation.</li>"
            "<li>First application window: <strong>25 March – 30 June "
            "2026</strong>. Works to be completed by 31 March 2027.</li>"
            "<li>Aimed at fleets adopting <strong>zero-emission HGVs, vans "
            "and coaches</strong> — not the vehicles themselves, and not "
            "the DNO's own deep network reinforcement.</li>"
            "<li>See the "
            "<a style=\"color:var(--green-d)\" "
            "href=\"/guides/ev-infrastructure-grant/\">grant guide</a> for "
            "the full mechanics.</li>"
            "</ul>"
            "<h2>How rapid DC sizing relates to operational duty cycles</h2>"
            "<p>Power per bay should be sized backwards from the duty cycle, "
            "not forwards from the spec sheet. A 44-tonne tractor unit "
            "doing one daily run with an 11-hour rest takes a 50 kW bay; a "
            "multi-drop van fleet with 90-minute charge windows between "
            "loops needs 150 kW. Over-spec wastes capex on the unit and "
            "drives a larger DNO connection that you then pay for. "
            "Under-spec strands a vehicle. A credible depot installer asks "
            "for the duty-cycle data first and quotes hardware second.</p>"
            "<h2>The DNO problem is the project</h2>"
            "<p>Under Ofgem's Access SCR rules (April 2023) the DNO absorbs "
            "deep network reinforcement cost — but the customer still pays "
            "the connection works and the assets to the meter. A documented "
            "case (Fleet News) saw a £640k connection drop to around £130k "
            "under the new rules. Many quotes still don't reflect this. A "
            "credible depot installer scopes the DNO position before "
            "quoting hardware. See the "
            "<a style=\"color:var(--green-d)\" "
            "href=\"/guides/ev-charger-installation-costs-uk/\">costs "
            "guide</a> for worked depot numbers.</p>"
            "<h2>Buying questions a logistics operator should ask</h2>"
            "<ul>"
            "<li>Can you show a redacted recent G99 application and "
            "connection offer letter for a comparable site?</li>"
            "<li>Is the Depot Charging Scheme 70% line shown explicitly on "
            "the quote, with a separate budget for the DNO works?</li>"
            "<li>Is dynamic load management baked in, or a paid add-on?</li>"
            "<li>Are you proposing an Independent Connection Provider (ICP) "
            "for the contestable works, and why or why not?</li>"
            "<li>What uptime SLA applies to the rapid units, and what is "
            "the on-site response time?</li>"
            "</ul>"),
        "faqs": [
            ("Is the Depot Charging Scheme the right grant for a haulage depot?",
             "Yes for fleets adopting zero-emission HGVs, vans or coaches. It funds 70% of chargepoint and civil costs (trenching, cabling, electrical upgrades) up to £1m per organisation. First window 25 March – 30 June 2026; works completed by 31 March 2027."),
            ("How does depot DC rapid sizing relate to operational duty cycles?",
             "Size the bay from the rest window backwards. An 11-hour overnight rest charges a 44-tonne tractor unit at 50 kW; a 90-minute mid-shift window in a parcel-delivery loop needs 150 kW. Over-spec drives a larger DNO connection you then pay for. Under-spec strands a vehicle."),
            ("Can a logistics depot also claim the Workplace Charging Scheme?",
             "Only for off-street staff and pool-car bays — not for HGV or operational fleet bays at a depot moving zero-emission HGVs, vans or coaches, which are the Depot Charging Scheme's territory. Mixed-use sites split the application by use case."),
            ("What is the typical lead time for a depot rapid project?",
             "6–18 months end-to-end. The hardware install is short (8–12 weeks); the long pole is the DNO connection offer, acceptance, reinforcement and energisation."),
            ("Do I need an Independent Connection Provider (ICP)?",
             "Optional. Contestable works on the connection can be done by an ICP rather than the DNO, often quicker. A good installer either has ICP capability in-house or partners with one and explains the trade-off in the quote."),
            ("Does the Depot Charging Scheme cover the vehicles themselves?",
             "No. The scheme funds chargepoint hardware and the customer-side civil works only. Vehicles are funded separately — historically through the Plug-in Truck Grant (check the Department for Transport for current status) or through commercial leasing."),
        ],
        "related_services": [
            "depot-rapid-charging-installers",
            "fleet-charging-installers",
            "workplace-charging-installers",
        ],
    },
    "local-authority-public-sector": {
        "h1": "EV Charger Installers for UK Local Authorities & Public Sector",
        "audience": "councils, public-sector bodies and government estate teams",
        "title": "EV Charger Installers for UK Local Authorities — Verified Commercial Providers",
        "card_blurb": "Council and public-sector procurement. LEVI Fund, RM6213 framework, on-street and residents.",
        "meta_desc": ("OZEV-authorised UK installers for local authority and "
                      "public-sector EV charging — LEVI Fund, on-street and "
                      "council car parks, residents without driveways. {n} "
                      "verified commercial installers."),
        "intro_html": (
            "<p>Local authority EV charging is a different procurement "
            "exercise from a private fleet project. Spend goes through "
            "frameworks, the residents-without-driveways case is political "
            "as much as technical, and the funding route is usually the "
            "Local EV Infrastructure (LEVI) Fund rather than the OZEV "
            "Workplace Charging Scheme. The installer's value-add shifts "
            "from cheapest capex to demonstrable framework experience and "
            "long-horizon operations.</p>"
            "<p>The {n} installers on this page are all "
            "<strong>OZEV-authorised for commercial work</strong> on the "
            "public GOV.UK list. OZEV does not flag framework participation "
            "in its source data — so this page filters by commercial only, "
            "and the right next step is to verify framework membership "
            "directly with each shortlisted installer.</p>"
            "<h2>Procurement routes councils use</h2>"
            "<ul>"
            "<li><strong>Crown Commercial Service RM6213 — Vehicle Charging "
            "Infrastructure Solutions</strong>. A pan-public agreement for "
            "chargepoint hardware, installation and operation. Many "
            "councils default to it.</li>"
            "<li><strong>Regional procurement consortia</strong> (ESPO, YPO "
            "and others) — frequently used for smaller council car-park "
            "projects.</li>"
            "<li><strong>LEVI capital and capability funding</strong> — "
            "administered by the Office for Zero Emission Vehicles, "
            "delivered to local authorities for residents without "
            "off-street parking. LEVI capability funding pays for the "
            "in-house officers; LEVI capital funds the infrastructure.</li>"
            "</ul>"
            "<h2>Typical local-authority scope</h2>"
            "<ul>"
            "<li><strong>On-street residential AC, 7–22 kW</strong> — for "
            "residents without driveways. Lamp-column or kerbside units; "
            "civils dominated by trenching and pavement reinstatement.</li>"
            "<li><strong>Council car-park bays, mixed AC and DC</strong> — "
            "Park &amp; Ride, leisure-centre, town-centre parking. "
            "Public-access and revenue-generating.</li>"
            "<li><strong>Council fleet bays</strong> — refuse vehicles, "
            "social-care vans, grey-fleet pool. Workplace Charging Scheme "
            "may apply to off-street staff bays; the Depot Charging Scheme "
            "applies where a council fleet depot operates zero-emission "
            "HGVs.</li>"
            "</ul>"
            "<h2>Common pitfalls</h2>"
            "<ul>"
            "<li>Specifying the same bay everywhere when "
            "residents-without-driveways need different siting and tariff "
            "design than Park &amp; Ride.</li>"
            "<li>Underestimating ongoing operational cost — back-office, "
            "maintenance and contactless-payment compliance under the "
            "Public Charge Point Regulations 2023 add a per-charger annual "
            "cost that needs a budget line beyond the LEVI capital.</li>"
            "<li>Concession structures that leave the council carrying "
            "stranded-asset risk in year seven when hardware ages out.</li>"
            "</ul>"
            "<h2>Buying questions a council should ask</h2>"
            "<ul>"
            "<li>Which framework are you bidding under, and can you show "
            "two recent council references at similar scale?</li>"
            "<li>How does your proposal meet the Public Charge Point "
            "Regulations 2023 — contactless payment, 99% uptime on rapid "
            "units, published pricing, open-data feeds to the National "
            "Chargepoint Registry?</li>"
            "<li>Is the proposal capex, concession or revenue-share — and "
            "what is the asset position in year 10?</li>"
            "<li>How does the back-office handle on-street resident tariff "
            "design (cap on overnight cost, off-peak windows)?</li>"
            "<li>What is the LEVI capital draw schedule, and how does it "
            "phase with delivery milestones?</li>"
            "</ul>"),
        "faqs": [
            ("Which framework do councils typically buy EV charging through?",
             "Crown Commercial Service RM6213 (Vehicle Charging Infrastructure Solutions) is the main pan-public agreement. Regional consortia like ESPO and YPO are also widely used. A council can also tender directly under the Public Contracts Regulations 2015 (as amended) where the value or scope makes that preferable."),
            ("What is the LEVI Fund and how does a council apply?",
             "The Local Electric Vehicle Infrastructure Fund is administered by the Office for Zero Emission Vehicles. It provides capital funding for local authorities to deliver on-street and residential charging for residents without off-street parking, plus capability funding for the officers running the programme. Allocations are made by region; the local authority leads delivery."),
            ("Are on-street resident chargepoints subject to the Public Charge Point Regulations 2023?",
             "Yes for any unit 8 kW or above. The regulations require contactless or open-payment systems on public-access points of that size, published pricing, 99% rapid-charger uptime, and open-data feeds to the National Chargepoint Registry."),
            ("Can a council claim the Workplace Charging Scheme for its own fleet?",
             "Yes — the WCS is open to public-sector bodies for off-street staff and fleet parking, up to 40 sockets per applicant at up to £500 per socket (the rate in force since 1 April 2026), capped at 75% of cost. The voucher is redeemed through an OZEV-authorised installer."),
            ("What ongoing operational costs does a council need to budget?",
             "Back-office software (£10–£50 per charger per month), maintenance and SLA, electricity, payment-acquiring fees on contactless, and periodic hardware refresh. LEVI capital does not fund these — capability funding helps with the staffing, but ongoing costs sit in the operational budget."),
            ("What is the typical concession term for an on-street charging contract?",
             "Commonly 8–15 years, with the operator funding the hardware in exchange for revenue share or fixed payments. Term length is the key risk variable: too long and the council is locked in past a hardware refresh; too short and the operator can't underwrite the deployment."),
        ],
        "related_services": [
            "public-car-park-ev-installers",
            "workplace-charging-installers",
            "fleet-charging-installers",
        ],
    },
    "property-management-multi-tenant": {
        "h1": "EV Charger Installers for UK Property Management & Multi-Tenant Buildings",
        "audience": "landlords, managing agents and multi-tenant building operators",
        "title": "EV Charger Installers for UK Property & Multi-Tenant Buildings — Verified Providers",
        "card_blurb": "Landlords, MUDs and multi-let estates. Approved Document S (EV-ready Building Regs Part S).",
        "meta_desc": ("OZEV-authorised UK installers for property management "
                      "and multi-tenant EV charging — Approved Document S "
                      "(EV-ready Building Regs Part S), landlord–tenant cost "
                      "split, common-area metering. {n} verified commercial "
                      "installers."),
        "intro_html": (
            "<p>Multi-tenant EV charging — apartment blocks, mixed-use "
            "developments, leasehold flats with shared parking, multi-let "
            "industrial estates — is mostly a wiring-and-billing problem "
            "with an EV charger on the end of it. Who pays for the supply "
            "upgrade, who owns the bay, how is electricity billed back to "
            "the tenant who used it, and how does the project sit inside "
            "Approved Document S of the Building Regulations? These are "
            "the questions that move quotes from indicative to real.</p>"
            "<p>The {n} installers on this page are all "
            "<strong>OZEV-authorised for commercial work</strong> on the "
            "public GOV.UK list. OZEV does not publish a multi-tenant or "
            "MUD (multi-unit-dwelling) sub-tag — so this page filters to "
            "every commercial OZEV-authorised installer; ask three "
            "shortlisted installers for a recent MUD or multi-let "
            "reference.</p>"
            "<h2>Approved Document S — Building Regs Part S</h2>"
            "<p>Since 15 June 2022, Approved Document S of the Building "
            "Regulations (England) has required EV charging provision in "
            "new buildings and certain major renovations. In summary:</p>"
            "<ul>"
            "<li><strong>New residential buildings with associated parking</strong>"
            " — every dwelling with a parking space gets a charge point; "
            "where the residential development has more than 10 parking "
            "spaces, additional cable routes are required for spaces not "
            "directly served.</li>"
            "<li><strong>New non-residential buildings with more than 10 "
            "parking spaces</strong> — at least one charge point, plus "
            "cable routes (passive provision) for one in five remaining "
            "spaces.</li>"
            "<li><strong>Major renovations creating &gt;10 parking spaces</strong>"
            " — equivalent provision applies where the parking is being "
            "altered. The regulations apply to England; Wales, Scotland "
            "and Northern Ireland have separate but broadly similar "
            "regimes.</li>"
            "</ul>"
            "<p>Approved Document S applies to <em>new build and major "
            "renovation</em>, not to existing untouched stock. For an "
            "existing apartment block adding EV charging today, Part S "
            "is the design reference rather than a legal requirement.</p>"
            "<h2>Typical multi-tenant scope</h2>"
            "<ul>"
            "<li><strong>Shared 7–22 kW AC bays in a common car park</strong>"
            " — billed through a CPO back-office, RFID or app-based.</li>"
            "<li><strong>Allocated bay charging</strong> — one bay per "
            "leaseholder, each socket on a sub-meter; electricity billed "
            "to the tenant directly.</li>"
            "<li><strong>Landlord master supply + DNO upgrade</strong> — "
            "where the existing supply can't take 10–40 sockets, the "
            "landlord may need a new connection. Whether that cost sits "
            "with the freeholder, leaseholder service charge, or the CPO "
            "concession is a legal and commercial question, not a "
            "technical one.</li>"
            "</ul>"
            "<h2>The grant picture</h2>"
            "<ul>"
            "<li>The <strong>EV Chargepoint Grant for landlords</strong> "
            "supports landlords installing chargepoints in residential "
            "rental properties — check the live OZEV pages for the "
            "current cap, per-applicant ceiling and eligibility before "
            "applying.</li>"
            "<li>The <strong>Workplace Charging Scheme</strong> applies "
            "where the parking serves a workplace tenant — including "
            "multi-let industrial estates where each tenant is itself a "
            "business with eligible off-street staff parking.</li>"
            "</ul>"
            "<h2>Buying questions a landlord should ask</h2>"
            "<ul>"
            "<li>Who owns the asset on day one and on day 3,650 — the "
            "freeholder, the management company, or the CPO?</li>"
            "<li>Is electricity sub-metered per socket, and how does "
            "billback to the tenant work in practice?</li>"
            "<li>Is the landlord supply already adequate, or does the "
            "project trigger a DNO upgrade — and where does that cost "
            "sit in the service charge?</li>"
            "<li>How is consent from leaseholders managed where the lease "
            "is silent on common-area alterations?</li>"
            "<li>Does the design meet Approved Document S where the "
            "building is in scope?</li>"
            "</ul>"),
        "faqs": [
            ("What is Approved Document S and does it apply to my building?",
             "Approved Document S of the Building Regulations (England) sets EV-ready provision standards for new build and major renovation. In force since 15 June 2022, it requires charge points and cable routes in new residential and non-residential buildings with associated parking, scaled to the number of parking spaces. It does not retrospectively apply to existing untouched buildings."),
            ("Who pays for the supply upgrade in a multi-tenant block?",
             "There is no single statutory answer. Costs typically sit with the freeholder/management company, are recovered through the service charge, or are funded by a CPO concession in exchange for revenue. The right answer depends on the lease terms and what the leaseholders consent to — get legal advice before signing."),
            ("Can leaseholders install their own charger on a private bay?",
             "Often yes, with landlord/management-company consent, where the lease and physical layout permit it. Many leases require formal consent for any common-area alteration; some require a deed of variation. The EV Chargepoint Grant for landlords and renters/flat-owners has historically supported this — check the current OZEV rules before quoting tenants a grant amount."),
            ("How is electricity billed back to the tenant who used it?",
             "Either through a CPO back-office (RFID or app-based; the CPO bills the user and remits a revenue share) or through per-socket sub-metering tied to the leaseholder's own electricity account. Sub-metering is simpler legally but more expensive at install."),
            ("Does the Workplace Charging Scheme apply in a multi-let industrial estate?",
             "Yes for the tenants — each tenant business with eligible off-street staff or fleet parking can apply in its own right, up to 40 sockets at up to £500 per socket (the rate in force since 1 April 2026), capped at 75% of cost. The landlord typically provides the infrastructure and tenants claim individually."),
            ("What's the most common pitfall on multi-tenant projects?",
             "Quoting capex before scoping who owns the asset, who pays for the DNO upgrade and how electricity is billed. A technically perfect install with no agreed billing route or no leaseholder consent stalls at energisation."),
        ],
        "related_services": [
            "workplace-charging-installers",
            "public-car-park-ev-installers",
            "fleet-charging-installers",
        ],
    },
    "car-dealerships": {
        "h1": "EV Charger Installers for UK Car Dealerships",
        "audience": "franchised dealers, used-car forecourts and aftersales workshops",
        "title": "EV Charger Installers for UK Car Dealerships — Verified Commercial Providers",
        "card_blurb": "Customer test-drive bays + workshop dwell + staff fleet. Brand-spec realities.",
        "meta_desc": ("OZEV-authorised UK installers for car dealership EV "
                      "charging — customer test-drive bays, workshop "
                      "diagnostics, brand-mandated standards. {n} verified "
                      "commercial installers."),
        "intro_html": (
            "<p>Car dealerships have an unusual EV charging profile: two "
            "distinct demand sources sharing a site, plus a manufacturer "
            "specification that often dictates the hardware. Customer "
            "test-drive and handover bays need rapid throughput; the "
            "workshop needs slower, longer-duration bays for diagnostics "
            "and battery conditioning. Get either wrong and the site "
            "either over-spends or under-serves.</p>"
            "<p>The {n} installers on this page are all "
            "<strong>OZEV-authorised for commercial work</strong> on the "
            "public GOV.UK list. OZEV does not publish a dealership "
            "sub-tag, and manufacturer-approved-installer lists are "
            "separate and brand-specific — so the right next step is to "
            "cross-check this directory against your brand's approved "
            "list, where one exists, before shortlisting.</p>"
            "<h2>Typical dealership scope</h2>"
            "<ul>"
            "<li><strong>Customer-facing rapid DC, 50–150 kW</strong> — "
            "for test-drive returns, pre-handover top-ups and customer "
            "courtesy charges. Visibility from the showroom matters; "
            "siting is part of the sales proposition.</li>"
            "<li><strong>Workshop AC, 7–22 kW</strong> — multiple slow "
            "bays for diagnostic dwell, battery conditioning, "
            "pre-delivery inspection (PDI). Hardware is straightforward; "
            "what matters is socket count.</li>"
            "<li><strong>Staff and fleet AC, 7 kW</strong> — Workplace "
            "Charging Scheme eligible off-street parking. Often the "
            "easiest grant claim on site.</li>"
            "</ul>"
            "<h2>Brand-mandated standards</h2>"
            "<p>Most franchised dealers receive a brand specification from "
            "the manufacturer — required hardware, branding, signage, "
            "minimum socket count per dealership and sometimes a preferred "
            "installer list. The commercial reality is that the "
            "manufacturer contract usually overrides choosing on price "
            "alone. The installer's value-add is delivering the brand "
            "spec inside the time window the brand has mandated.</p>"
            "<h2>The grant picture</h2>"
            "<ul>"
            "<li><strong>Workplace Charging Scheme</strong> applies to "
            "staff and dealer-fleet off-street parking — up to £500 per "
            "socket (the rate in force since 1 April 2026), 75% cap, "
            "40-socket cap per applicant. Demonstrator and customer "
            "test-drive bays are public-facing and usually outside scope.</li>"
            "<li>Customer-facing rapid bays are commercially funded, "
            "though some manufacturers contribute to brand-spec hardware "
            "as part of the franchise agreement. Confirm with your area "
            "manager what the brand pays for.</li>"
            "</ul>"
            "<h2>Common pitfalls</h2>"
            "<ul>"
            "<li>Specifying customer rapid bays at the back of the lot "
            "because that's where the supply is. Customers won't walk; "
            "siting visible from the showroom is part of the sale.</li>"
            "<li>Forgetting workshop dwell bays in the design — a 5-bay "
            "EV workshop running PDI on new cars needs 5 sockets, not "
            "one shared rapid.</li>"
            "<li>Signing manufacturer-spec hardware without checking the "
            "back-office is OCPP-open. Some brand specs lock you into "
            "proprietary software; year-five contract review is harder.</li>"
            "</ul>"
            "<h2>Buying questions a dealer principal should ask</h2>"
            "<ul>"
            "<li>Are you on our brand's approved installer list, and "
            "what's your current lead time for a site of this size?</li>"
            "<li>How are customer bays and staff bays separated for the "
            "WCS claim, and what's the staff-bay socket count?</li>"
            "<li>Is the workshop dwell-bay count designed around "
            "year-three EV throughput, not year-one?</li>"
            "<li>Is the back-office OCPP-compliant so we can change "
            "CPMS in year five without re-cabling?</li>"
            "</ul>"),
        "faqs": [
            ("Do car dealerships need brand-approved installers?",
             "Most franchised manufacturers operate their own approved-installer or preferred-supplier lists for dealership EV infrastructure. The OZEV authorised list (which this directory is built from) is a separate, broader pool. Cross-check both — being on the OZEV list is a baseline for grant work; being on the brand list is what the franchise contract usually requires."),
            ("Can a dealership claim the Workplace Charging Scheme?",
             "Yes for off-street staff and fleet bays — up to £500 per socket (the rate in force since 1 April 2026), capped at 75% of cost and 40 sockets per applicant. Customer test-drive and demonstrator bays sit outside the WCS because they are not staff/fleet parking."),
            ("How many bays does a typical dealership need?",
             "Highly brand- and volume-dependent. A franchised dealer pushing an EV-heavy line-up commonly specifies one or two customer-facing rapid DC bays (50–150 kW), 4–8 workshop dwell bays (7–22 kW AC) and a handful of staff/fleet bays. Brand spec usually sets minimums."),
            ("Should customer-facing chargers be free or paid?",
             "Free during test-drive and handover is normal — the cost is part of the sale. Free indefinitely as a customer amenity is harder to justify once EV mix is mainstream. Many dealers move to pay-per-use via an open-payment terminal once free-charging volumes get material; the Public Charge Point Regulations 2023 apply if you take payment at 8 kW or above."),
            ("Do dealer service workshops need DC or AC chargers?",
             "Mostly AC. Workshop dwell is long (PDI, software updates, conditioning), so 7–22 kW AC is sufficient and cheaper per socket. A single DC bay can be useful for diagnostics requiring fast charge cycles, but it shouldn't dominate the spec."),
            ("Does the manufacturer pay for the chargepoints?",
             "Sometimes partially. Some manufacturers contribute to brand-spec hardware or co-fund flagship visible bays as part of the franchise agreement. Confirm directly with your area manager what is funded; do not assume."),
        ],
        "related_services": [
            "workplace-charging-installers",
            "public-car-park-ev-installers",
            "fleet-charging-installers",
        ],
    },
    "nhs-healthcare": {
        "h1": "EV Charger Installers for UK NHS & Healthcare Sites",
        "audience": "NHS trusts, primary-care networks and private healthcare estate teams",
        "title": "EV Charger Installers for UK NHS & Healthcare — Verified Commercial Providers",
        "card_blurb": "NHS trusts and healthcare estates. Greener NHS targets, staff parking, blue-light fleets.",
        "meta_desc": ("OZEV-authorised UK installers for NHS and healthcare "
                      "EV charging — fleet vans, staff parking, blue-light "
                      "vehicles, Greener NHS net-zero targets. {n} verified "
                      "commercial installers."),
        "intro_html": (
            "<p>NHS and healthcare EV charging sits inside a broader "
            "net-zero obligation. Under the Health and Care Act 2022, the "
            "NHS in England has statutory net-zero duties; the Greener NHS "
            "programme commits to net-zero for the emissions the NHS "
            "directly controls (the NHS Carbon Footprint) by 2040, and for "
            "the wider NHS Carbon Footprint Plus by 2045. Fleet "
            "electrification is one of the more measurable contributions — "
            "community-nursing vans, patient-transport vehicles, estates "
            "fleet and staff commuting all sit in scope.</p>"
            "<p>The {n} installers on this page are all "
            "<strong>OZEV-authorised for commercial work</strong> on the "
            "public GOV.UK list. OZEV does not publish a healthcare "
            "sub-tag, and there is no NHS-specific OZEV grant scheme — "
            "trusts typically procure through public-sector frameworks "
            "and apply for the same general OZEV schemes as any other "
            "public-sector body.</p>"
            "<h2>Typical NHS / healthcare scope</h2>"
            "<ul>"
            "<li><strong>Estates fleet AC, 7–22 kW</strong> — "
            "community-nursing vans, estates and facilities, social-care "
            "vehicles. WCS-eligible off-street parking in most cases.</li>"
            "<li><strong>Staff car-park AC, 7 kW</strong> — high "
            "socket-count, low-power. Staff commuting is a large share of "
            "NHS Carbon Footprint Plus emissions.</li>"
            "<li><strong>Patient and visitor bays, mixed AC + DC</strong> — "
            "public-access and revenue-generating; subject to the Public "
            "Charge Point Regulations 2023 at 8 kW and above.</li>"
            "<li><strong>Blue-light / ambulance trust depots</strong> — "
            "rapid DC for vehicle turnaround between shifts. Closer to a "
            "logistics depot than a typical hospital car park.</li>"
            "</ul>"
            "<h2>Procurement and grants</h2>"
            "<ul>"
            "<li><strong>NHS Shared Business Services frameworks and Crown "
            "Commercial Service RM6213</strong> are the main routes. "
            "Trusts can also tender directly under the Public Contracts "
            "Regulations 2015 (as amended).</li>"
            "<li><strong>Workplace Charging Scheme</strong> is open to "
            "public-sector bodies for off-street staff and fleet parking "
            "— up to £500 per socket (the rate in force since 1 April "
            "2026), capped at 75% of cost and 40 sockets per applicant. "
            "The voucher is redeemed through an OZEV-authorised "
            "installer.</li>"
            "<li><strong>Depot Charging Scheme</strong> applies where an "
            "NHS depot operates zero-emission HGVs, vans or coaches — "
            "ambulance, patient transport and large estates fleets can "
            "qualify. 70% of chargepoint and civil costs, capped at £1m "
            "per organisation; first window 25 March – 30 June 2026, "
            "works completed by 31 March 2027.</li>"
            "</ul>"
            "<p>There is no NHS-specific OZEV grant beyond these general "
            "schemes. Some trusts have funded EV-adjacent work through "
            "the Public Sector Decarbonisation Scheme (PSDS) where it "
            "forms part of a wider heat-decarbonisation business case, "
            "but PSDS is not primarily an EV scheme — check the current "
            "Salix rules before assuming eligibility.</p>"
            "<h2>Specific considerations for hospital sites</h2>"
            "<ul>"
            "<li><strong>Resilience and back-up generation</strong> — "
            "hospital sites are critical infrastructure. Where the EV "
            "load is material, the installer must coordinate with the "
            "estate's standby generation and load-shedding strategy.</li>"
            "<li><strong>Existing power constraints</strong> — older "
            "hospital sites often have constrained supplies already. A "
            "DNO upgrade for EV may unlock other estate decarbonisation "
            "work (heat pumps, theatre ventilation) and should be scoped "
            "jointly.</li>"
            "<li><strong>Public-access compliance</strong> — patient and "
            "visitor bays at 8 kW or above must accept contactless "
            "payment and publish pricing under the Public Charge Point "
            "Regulations 2023.</li>"
            "</ul>"
            "<h2>Buying questions a trust should ask</h2>"
            "<ul>"
            "<li>Which framework are you bidding under, and can you show "
            "two recent NHS or public-sector references at similar scale?</li>"
            "<li>How does the design interact with the site's existing "
            "standby generation and resilience strategy?</li>"
            "<li>How are staff, patient/visitor and fleet bays separated "
            "in the WCS and Depot Charging Scheme claims?</li>"
            "<li>Does the back-office report energy and emissions in a "
            "format that maps to the Greener NHS reporting framework?</li>"
            "<li>What ongoing operational cost (back-office, maintenance, "
            "payment fees) sits with the trust beyond the capital project?</li>"
            "</ul>"),
        "faqs": [
            ("Is there an NHS-specific EV charging grant?",
             "No. NHS trusts apply for the same OZEV schemes as any other public-sector body — the Workplace Charging Scheme for staff/fleet bays and the Depot Charging Scheme for fleet depots operating zero-emission HGVs, vans or coaches. There is no separate NHS or healthcare top-up grant under OZEV."),
            ("Does the Greener NHS net-zero target require EV charging?",
             "Indirectly. The Greener NHS programme commits to net-zero for direct NHS emissions (NHS Carbon Footprint) by 2040, and for the wider NHS Carbon Footprint Plus (including staff commuting and visitor travel) by 2045. Fleet electrification and staff EV provision are among the more measurable contributions; there is no specific charger-per-site mandate."),
            ("Which framework do NHS trusts buy EV charging through?",
             "NHS Shared Business Services frameworks and Crown Commercial Service RM6213 (Vehicle Charging Infrastructure Solutions) are the most common routes. Trusts can also tender directly under the Public Contracts Regulations 2015 (as amended)."),
            ("How does the Depot Charging Scheme apply to an ambulance trust?",
             "Ambulance and patient-transport depots operating zero-emission vans or larger vehicles can apply for 70% of chargepoint and civil costs, capped at £1m per organisation. First application window 25 March – 30 June 2026; works completed by 31 March 2027."),
            ("Can patient and visitor bays be public-access and paid?",
             "Yes — most acute hospital sites operate visitor parking commercially. Any public-access charge point at 8 kW or above must accept contactless payment, publish pricing, and meet 99% uptime (rapid units) under the Public Charge Point Regulations 2023."),
            ("What about resilience — what if the grid goes down?",
             "Hospital sites are critical infrastructure with standby generation. EV charging load needs to be either non-essential (sheds first on a loss of supply) or specifically backed up; the installer must coordinate with the trust's estate engineering and emergency-planning team. This is usually scoped at design stage, not retrofitted later."),
        ],
        "related_services": [
            "fleet-charging-installers",
            "workplace-charging-installers",
            "depot-rapid-charging-installers",
        ],
    },
}


def page_industry(slug, spec, installers):
    """Build an industry-vertical landing page. Like /services/*, the OZEV
    source has no per-vertical sub-tag, so the eligible pool is every
    commercial OZEV-authorised installer. The intro surfaces this honestly."""
    url = f"{BASE_URL}/industries/{slug}/"
    eligible = [i for i in installers if "Commercial" in i.get("services", [])]
    feat = [i for i in eligible if i.get("featured")]
    rest = sorted([i for i in eligible if not i.get("featured")],
                  key=lambda x: x["name"].lower())
    ordered = feat + rest
    n = len(ordered)
    coverage_note = ""
    if n < 5:
        coverage_note = ('<p class="note">Coverage growing — the directory '
                         'rebuilds weekly from the official OZEV list.</p>')

    cards = "".join(card(i) for i in ordered)

    region_counts: dict[str, int] = {}
    for i in eligible:
        r = i.get("region")
        if r and r != "N/A":
            region_counts[r] = region_counts.get(r, 0) + 1
    top_regions = sorted(region_counts.items(), key=lambda kv: -kv[1])[:5]
    region_items = "".join(
        f'<li><a style="color:var(--green-d)" href="/regions/{slugify(r)}/">'
        f'{esc(r)}</a> — {c} OZEV-authorised commercial installer'
        f'{"s" if c != 1 else ""}</li>'
        for r, c in top_regions)
    top_regions_html = ""
    if region_items:
        top_regions_html = (
            '<h2>Top 5 regions for this vertical</h2>'
            f'<ul style="margin:12px 0 0 22px;line-height:1.7">{region_items}</ul>')

    svc_labels = {
        "fleet-charging-installers": ("Fleet charging installers",
                                      "Vans, HGVs, company cars. WCS + Depot Charging Scheme grant routes."),
        "workplace-charging-installers": ("Workplace charging installers",
                                          "Staff and office car parks. Up to £500/socket under the WCS."),
        "depot-rapid-charging-installers": ("Depot rapid DC installers",
                                            "Logistics, bus and coach depots. 70% Depot Charging Scheme funding."),
        "public-car-park-ev-installers": ("Public car-park installers",
                                          "Retail, hospitality, council. Commercial / charging-as-a-service."),
    }
    rel_cards = "".join(
        f'<a class="gcard" style="background:#fff;border-color:var(--bd-l);'
        f'color:var(--ink)" href="/services/{s}/">'
        f'<h3 style="color:var(--ink)">{esc(svc_labels[s][0])}</h3>'
        f'<p style="color:var(--mut)">{esc(svc_labels[s][1])}</p></a>'
        for s in spec["related_services"] if s in svc_labels
    )
    rel_cards += (
        '<a class="gcard" style="background:#fff;border-color:var(--bd-l);'
        'color:var(--ink)" href="/tools/ev-charger-cost-calculator/">'
        '<h3 style="color:var(--ink)">Cost &amp; grant calculator</h3>'
        '<p style="color:var(--mut)">Indicative hardware, civils and DNO '
        'cost — plus WCS &amp; Depot Charging Scheme — for your project.</p></a>'
        '<a class="gcard" style="background:#fff;border-color:var(--bd-l);'
        'color:var(--ink)" href="/tools/uk-ev-grant-eligibility/">'
        '<h3 style="color:var(--ink)">Grant eligibility wizard</h3>'
        '<p style="color:var(--mut)">Answer 6 quick questions — see which '
        'UK 2026 grant(s) you qualify for.</p></a>'
    )

    jl_list = {
        "@context": "https://schema.org", "@type": "ItemList",
        "name": spec["h1"], "numberOfItems": n,
        "itemListElement": [
            {"@type": "ListItem", "position": idx + 1,
             "url": f"{BASE_URL}/installers/{i['_slug']}/",
             "name": i["name"]}
            for idx, i in enumerate(ordered[:100])]}
    trail = [("Directory", "/"), ("Industries", "/#industries"),
             (spec["h1"], f"/industries/{slug}/")]
    jsonld = ('<script type="application/ld+json">' + json.dumps(jl_list)
              + "</script>" + breadcrumb_jsonld(trail)
              + faq_jsonld(spec["faqs"]))

    title = spec["title"]
    desc = spec["meta_desc"].format(n=n)
    intro = spec["intro_html"].format(n=n)

    return (
        head(title, desc, url, jsonld)
        + navbar()
        + f"""<div class="wrap crumb"><a href="/">Directory</a> ›
<a href="/#industries">Industries</a> › {esc(spec['h1'])}</div>
<section style="padding-top:8px"><div class="wrap">
<h1 style="font-size:40px;font-weight:800;letter-spacing:-1.5px">{esc(spec['h1'])}</h1>
<p class="lead" style="margin-top:14px;max-width:760px">For {esc(spec['audience'])}.
{n} OZEV-authorised commercial EV charging installers on the official GOV.UK
list, filtered to those offering commercial work. OZEV does not publish a
per-vertical sub-tag, so the eligible pool is every commercial installer —
shortlist three and ask each for a recent reference in this sector.</p>
<div class="prose" style="max-width:760px">{intro}</div>
{coverage_note}
<h2 class="sh" style="margin-top:40px">The installers</h2>
<p class="note">{n} OZEV-authorised commercial installer{'s' if n != 1 else ''}
shown. Featured partners are labelled and shown first; nothing else affects
order.</p>
<div class="grid">{cards or '<p class=muted>None indexed yet — coverage widens each refresh.</p>'}</div>
<div class="prose" style="max-width:760px;margin-top:40px">
{top_regions_html}
{faq_html(spec['faqs'])}
</div>
<h2 class="sh" style="margin-top:40px">Related services &amp; tools</h2>
<div class="guidegrid" style="margin-top:14px">{rel_cards}</div>
<div class="cta-row" style="margin-top:22px">
<a class="btn btn-g" href="/calculator/">Estimate cost + grant</a>
<a class="btn btn-o" style="border-color:#cfd6df;color:#0a0a0a" href="/#directory">All UK installers</a>
</div>
<p class="note" style="margin-top:24px">
<a style="color:var(--green-d)" href="/">Back to home</a> ·
<a style="color:var(--green-d)" href="/sitemap.xml">Sitemap</a>
</p>
</div></section>""" + footer() + SHORTLIST_JS + "</body></html>"
    )


# Map from /services/<slug> → list of /industries/<slug> most relevant to that
# service. Built by inverting INDUSTRIES[*].related_services. Used by the
# small "Related industries" block injected into each /services/* page.
SERVICE_TO_INDUSTRIES: dict[str, list[str]] = {}
for _islug, _ispec in INDUSTRIES.items():
    for _svc in _ispec["related_services"]:
        SERVICE_TO_INDUSTRIES.setdefault(_svc, []).append(_islug)


def industries_block_for_service(service_slug: str) -> str:
    """Small 'Related industries' block injected at the bottom of each
    /services/* page. Falls back to an empty string if the service has no
    industry cross-links yet (so it is safe to call on any service slug)."""
    inds = SERVICE_TO_INDUSTRIES.get(service_slug, [])[:4]
    if not inds:
        return ""
    cards_html = "".join(
        f'<a class="gcard" style="background:#fff;border-color:var(--bd-l);'
        f'color:var(--ink)" href="/industries/{i}/">'
        f'<h3 style="color:var(--ink)">{esc(INDUSTRIES[i]["h1"].replace("EV Charger Installers for UK ", ""))}</h3>'
        f'<p style="color:var(--mut)">{esc(INDUSTRIES[i]["card_blurb"])}</p></a>'
        for i in inds if i in INDUSTRIES
    )
    return (
        '<h2 class="sh" style="margin-top:40px">Related industries</h2>'
        '<p class="lead" style="max-width:760px">Same commercial OZEV pool, '
        'viewed through a sector lens — pick the page that matches who you '
        'are buying for.</p>'
        f'<div class="guidegrid" style="margin-top:14px">{cards_html}</div>'
    )


if __name__ == "__main__":
    raise SystemExit(main())
