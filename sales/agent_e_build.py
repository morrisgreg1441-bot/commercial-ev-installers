"""Agent E builder: generates 50 installer outreach emails + 20 trade-body emails.

One-shot. Idempotent. Writes Unix line endings.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "data" / "installers.json"
CSV_PATH = ROOT / "sales" / "prospects-top50.csv"
OUT_FEATURED = ROOT / "outreach" / "featured"
OUT_STUDIO = ROOT / "outreach" / "studio"

OUT_FEATURED.mkdir(parents=True, exist_ok=True)
OUT_STUDIO.mkdir(parents=True, exist_ok=True)

FREE_WEBMAIL = {
    "gmail.com", "hotmail.com", "yahoo.com", "outlook.com",
    "btinternet.com", "aol.com", "live.com", "icloud.com",
    "yahoo.co.uk", "hotmail.co.uk", "outlook.co.uk",
    "me.com", "msn.com", "mac.com",
}
GENERIC_PREFIXES = {
    "info", "sales", "office", "enquiries", "enquiry", "hello",
    "admin", "mail", "contact", "team", "support", "reception",
    "projects", "energyops",
}
FAKE_DOMAINS = {"email.com", "example.com", "test.com"}

SENDER = "Greg Morris"
SITE_URL = "https://commercial-ev-installers.pages.dev"
FEATURED_URL = f"{SITE_URL}/featured/"
PRIVACY_URL = f"{SITE_URL}/privacy/"
# Flagged: SITE_CONTACT_EMAIL env var defaults to hello@example.com in generate.py.
# Greg must update generate.py to use a domain mailbox; placeholder below.
REPLY_EMAIL = "hello@commercial-ev-installers.pages.dev"  # FLAG: replace with real mailbox
POSTAL = "{POSTAL ADDRESS}"  # FLAG: not in MONETIZATION.md; Greg to fill before sending


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-+", "-", text)


def classify(email: str) -> tuple[str, str]:
    """Return (status, reason). status ∈ {'ready', 'SKIP'}."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return "SKIP", "missing/invalid email"
    local, _, domain = email.partition("@")
    if domain in FAKE_DOMAINS:
        return "SKIP", f"fake/test domain ({domain})"
    if domain in FREE_WEBMAIL:
        return "SKIP", "free webmail (PECR B2B exemption does not apply)"
    # firstname.lastname@ or firstname@ → personal
    if "." in local and not any(p in local for p in ("info", "sales", "office", "admin")):
        # heuristic: firstname.lastname pattern
        parts = local.split(".")
        if len(parts) == 2 and all(p.isalpha() and len(p) > 1 for p in parts):
            return "SKIP", "personal firstname.lastname address"
    if local in GENERIC_PREFIXES:
        return "ready", "generic Ltd-company mailbox"
    # Bare first-name local-parts treated as personal
    if local.isalpha() and len(local) < 12:
        return "SKIP", "personal firstname-only address"
    # Hyphenated/compound generics like "energy-ops" → ready
    if any(local.startswith(p) for p in GENERIC_PREFIXES):
        return "ready", "generic Ltd-company mailbox"
    # Default: treat as ready only if local clearly non-personal (digits or >=2 dots)
    if any(ch.isdigit() for ch in local) or local.count(".") >= 2:
        return "ready", "generic-ish company mailbox"
    return "SKIP", "ambiguous local-part; verify generic Ltd-company address manually"


# Load installer dataset
data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
installers = data["installers"]

# Group: count commercial OZEV-authorised installers per region
region_commercial: dict[str, list[dict]] = {}
for inst in installers:
    if "Commercial" in inst.get("services", []):
        region_commercial.setdefault(inst["region"], []).append(inst)

# Sort each region alphabetically by name for neighbour lookup
for r, lst in region_commercial.items():
    lst.sort(key=lambda x: x["name"].lower())


def neighbours_for(name: str, region: str) -> tuple[str, str, int, int]:
    """Return (prev_name, next_name, position, total) within region commercial list."""
    lst = region_commercial.get(region, [])
    names = [i["name"] for i in lst]
    total = len(names)
    # Find by case-insensitive prefix match (slug-based lookup is brittle here)
    target_lc = name.lower()
    pos = None
    for idx, n in enumerate(names):
        if n.lower() == target_lc:
            pos = idx
            break
    if pos is None:
        # Try fuzzy: starts with same first 12 chars
        for idx, n in enumerate(names):
            if n.lower()[:15] == target_lc[:15]:
                pos = idx
                break
    if pos is None:
        return ("(an earlier-letter firm)", "(a later-letter firm)", 0, total)
    prev_n = names[pos - 1] if pos > 0 else "the first listing"
    next_n = names[pos + 1] if pos < total - 1 else "the last listing"
    return (prev_n, next_n, pos + 1, total)


# Subject patterns — rotated to keep variety
def subject_for(rank: int, company: str, town: str, region: str) -> str:
    short = company.replace(" Ltd", "").replace(" Limited", "").strip()
    patterns = [
        f"OZEV register entry — quick note on {town} visibility",
        f"{short} on the commercial EV installer directory — Featured slot offer",
        f"Founder rate for {region} — first 25 only",
        f"{town} Featured slot — £99/yr, 30-day refund",
        f"{short} — alphabetical positioning on the {region} commercial list",
    ]
    return patterns[rank % len(patterns)]


def write_md(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


# -------- E1: 50 personalised installer emails --------
skip_count = 0
ready_count = 0
with CSV_PATH.open(encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

for row in rows:
    rank = int(row["rank"])
    name = row["name"].strip()
    region = row["region"].strip()
    town = row["town"].strip()
    email = row["email"].strip()
    slug = slugify(name)
    nn = f"{rank:02d}"
    status, reason = classify(email)
    subject = subject_for(rank, name, town, region)
    prev_n, next_n, pos, total = neighbours_for(name, region)
    # Best-effort recipient name from email local-part (only if it's a personal address)
    local = email.split("@")[0] if "@" in email else ""
    to_name = ""
    if "." in local and status == "ready":
        to_name = " ".join(p.capitalize() for p in local.split(".")[:2])

    fm_lines = [
        "---",
        f"to: {email}",
        f"to_name: {to_name}",
        f"subject: {subject}",
        f"slug: {slug}",
        f"prospect_rank: {nn}",
        f"status: {status}",
        "---",
        "",
    ]

    if status == "SKIP":
        body = (
            f"SKIP — {reason}. PECR B2B corporate-subscriber exemption only covers "
            f"emails sent to limited companies and LLPs at corporate mailboxes "
            f"(info@, sales@, office@, enquiries@, etc.). The CSV address for "
            f"{name} does not meet that bar. Before contacting this prospect, "
            f"manually verify a generic Ltd-company address via their website "
            f"({row['website']}) or Companies House, then update the CSV and "
            f"regenerate.\n"
        )
    else:
        commercial_total = len(region_commercial.get(region, []))
        body = f"""Hi there,

{name} is one of {commercial_total} OZEV-authorised commercial installers we list across {region} on the new commercial-only directory at {SITE_URL}. Alphabetically your listing sits between {prev_n} and {next_n} — position {pos} of {commercial_total} — which is fine, but not where click-throughs concentrate.

I'm opening a Featured slot for {town} and the {region} region page: £99 one-time for 12 months. Founder rate, capped at 25 sales or 30 June 2026, whichever first. Pins you to #1 on the {town} page, the {region} page, and the relevant commercial-service pages, with a FEATURED PARTNER badge.

I'll be straight — the directory launched in May 2026, traffic is still maturing. That's exactly why this rate is £99 and not £199. You're locking position before SEO compounds; if it doesn't compound (no 5+ clicks in 30 days), you get every penny back. I write the refund cheque, not Stripe.

To claim or ask questions: {FEATURED_URL} — or reply to this email.

Thanks,
{SENDER}

—
{SENDER}, operator, commercial-ev-installers.pages.dev
Reply: {REPLY_EMAIL}
If you'd rather not hear from me again, reply with 'remove' and you're off this list permanently. See our privacy and contact policy here: {PRIVACY_URL}
Postal: {POSTAL}
"""
    write_md(OUT_FEATURED / f"{nn}-{slug}.md", "\n".join(fm_lines) + body)
    if status == "SKIP":
        skip_count += 1
    else:
        ready_count += 1

print(f"E1 complete: {ready_count} ready, {skip_count} SKIP, total {ready_count + skip_count}")


# -------- E2: 20 trade-body emails --------
TRADE = [
    # (slug, org name, email-or-None, hook_sentence)
    ("bvrla", "BVRLA (British Vehicle Rental and Leasing Association)",
     "brandpartnerships@bvrla.co.uk",
     "a browsable, OGL-licensed UK fleet leasing directory by sector × region × vehicle class, with the same site shell I've already built for OZEV installers"),
    ("fmb", "FMB (Federation of Master Builders)",
     "reception@fmb.org.uk",
     "a member-facing directory of Master Builders by trade × region × project scale, with a public-facing find-a-builder interface separate from the existing FMB site"),
    ("niceic", "NICEIC",
     "enquiries@niceic.com",
     "a commercial electrical contractor directory by accreditation tier × region × specialism (EV, solar, fire alarm), sitting alongside your existing Find a Contractor"),
    ("besa", "BESA (Building Engineering Services Association)",
     "marketing@thebesa.com",
     "a member directory by service discipline (vent hygiene, HVAC, refrigeration) × region, with filter-friendly schema for facilities buyers"),
    ("eca", "ECA (Electrical Contractors' Association)",
     "mediaenquiries@eca.co.uk",
     "a public directory of ECA members by region × specialism, including a separate fleet-EV-installation sub-index to capture commercial buyer search intent"),
    ("recc", "RECC (Renewable Energy Consumer Code)",
     "info@recc.org.uk",
     "a consumer-trust directory of RECC-signatory installers by technology (solar PV, battery, heat pump, EV) × region, with the consumer-code badge prominent"),
    ("mcs", "MCS (Microgeneration Certification Scheme)",
     None,
     ""),
    ("napit", "NAPIT",
     "info@napit.org.uk",
     "a NAPIT-member directory by scheme (electrical, plumbing, ventilation, EV) × region, indexed for the search terms domestic and commercial buyers actually type"),
    ("elecsa", "ELECSA",
     "enquiries.elecsa@certsure.com",
     "a public-facing ELECSA-registered contractor directory by region × specialism, sitting alongside the NICEIC find-a-contractor as a separate, leaner consumer interface"),
    ("energy-saving-trust", "Energy Saving Trust",
     "press@energysavingtrust.org.uk",
     "a public directory of EST-accredited / EST-funded installer networks by technology × region, with consumer-facing copy that matches your existing guidance tone"),
    ("zemo-partnership", "Zemo Partnership",
     None,
     ""),
    ("logistics-uk", "Logistics UK",
     None,
     ""),
    ("rha", "RHA (Road Haulage Association)",
     "enquiries@rha.uk.net",
     "a depot-EV-readiness directory: which RHA-member operators have on-site fleet charging, which are looking for it, indexed by region and depot size"),
    ("cilt-uk", "CILT UK (Chartered Institute of Logistics and Transport)",
     "enquiries@ciltuk.org.uk",
     "a CILT-member-facing service directory by logistics discipline × region — useful both as a benefit and as an SEO asset that compounds outside the membership wall"),
    ("bpca", "BPCA (British Pest Control Association)",
     "enquiry@bpca.org.uk",
     "a public BPCA-member directory by pest specialism × region × commercial-or-residential — the kind of thing facilities managers actually search for"),
    ("bifa", "BIFA (British International Freight Association)",
     "bifamembership@bifa.org",
     "a BIFA-member freight-forwarder directory by trade lane × cargo type × UK port, indexed for the queries importers and exporters type into Google"),
    ("ads-group", "ADS Group (aerospace, defence, security)",
     "comms@adsgroup.org.uk",
     "a public-facing ADS-member supplier directory by capability area × region, designed to be indexable by Tier-1 procurement teams searching outside the existing member portal"),
    ("bsia", "BSIA (British Security Industry Association)",
     "info@bsia.co.uk",
     "a public BSIA-member directory by service area (manned guarding, CCTV, access control) × region × accreditation, separate from the existing find-a-member tool"),
    ("made-smarter-uk", "Made Smarter UK",
     None,
     ""),
    ("bcc", "BCC (British Chambers of Commerce)",
     None,
     ""),
]

trade_skip = 0
trade_ready = 0
for idx, (slug, org, email, hook) in enumerate(TRADE, start=1):
    nn = f"{idx:02d}"
    if email is None:
        status = "SKIP — no publicly-listed generic address"
        subject = f"{org} — directory build proposal (on hold pending contact)"
        fm = (
            "---\n"
            f"to: \n"
            f"to_name: \n"
            f"subject: {subject}\n"
            f"slug: {slug}\n"
            f"prospect_rank: {nn}\n"
            f"status: {status}\n"
            "---\n\n"
            f"SKIP — no publicly-listed generic press/partnerships/info address could be confirmed for {org} via their public contact page or web search. PECR Reg 22 B2B exemption only covers corporate mailboxes; named-individual or contact-form-only routes need separate verification. Action: phone the org's switchboard, ask for press or partnerships, and capture a named generic mailbox before contacting.\n"
        )
        write_md(OUT_STUDIO / f"{nn}-{slug}.md", fm)
        trade_skip += 1
        continue

    subject = f"£750–£1,500 directory build for {org.split(' (')[0]} members"
    body = f"""Hi,

I'm {SENDER}, operator of {SITE_URL} — an independent directory of OZEV-authorised commercial EV installers, built from the public GOV.UK register under OGL v3.0. Live since May 2026.

I build sector directories for trade bodies on fixed price. For {org.split(' (')[0]}, the worked example: {hook}.

Shape: £750 starter (single slice, 2 weeks) or £1,500 standard (full UK, multi-facet filtering, sitemap + JSON-LD, open data export, 3–4 weeks). Fixed price. You own the source code and domain on day one. No retainer.

Why relevant: trade bodies sit on data members can't easily search themselves. A browsable, SEO-indexable directory is a low-cost member benefit and a compounding traffic asset outside the members wall.

If interesting, I'll send a one-page scope plus the OZEV site as a working example.

Thanks,
{SENDER}

—
{SENDER}, operator, commercial-ev-installers.pages.dev
Reply: {REPLY_EMAIL}
If you'd rather not hear from me again, reply with 'remove' and you're off this list permanently. See our privacy and contact policy here: {PRIVACY_URL}
Postal: {POSTAL}
"""
    fm = (
        "---\n"
        f"to: {email}\n"
        f"to_name: \n"
        f"subject: {subject}\n"
        f"slug: {slug}\n"
        f"prospect_rank: {nn}\n"
        f"status: ready\n"
        "---\n\n"
        + body
    )
    write_md(OUT_STUDIO / f"{nn}-{slug}.md", fm)
    trade_ready += 1

print(f"E2 complete: {trade_ready} ready, {trade_skip} SKIP")
