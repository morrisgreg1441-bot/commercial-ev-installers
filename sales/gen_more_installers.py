#!/usr/bin/env python3
"""Generate personalised Featured-listing pitch emails for the full sendable
installer pool — every installer with a generic business mailbox (info@,
sales@, office@...) AND a website AND a known town+region.

Preserves the curated top-50 already in outreach/featured/ (skips any slug
already present) and writes the remainder numbered from 51 upward. The console
generator picks up every status:ready file automatically.

Each email is personalised with the installer's region, the count of commercial
installers in that region, their alphabetical position and immediate neighbours
— the same proven template as the curated batch. Stdlib only.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "installers.json"
OUT = ROOT / "outreach" / "featured"

GENERIC = ("info", "sales", "enquiries", "enquiry", "office", "hello",
           "admin", "contact", "mail", "accounts", "team", "reception",
           "support", "ev", "evcharging", "projects")

SUBJECTS = [
    "OZEV register entry — quick note on {town} visibility",
    "{company} on the commercial EV installer directory — Featured slot offer",
    "Founder rate for {region} — first 25 only",
    "{town} Featured slot — £99/yr, 30-day refund",
    "You're listed in {region} — want the top slot?",
]


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s


def is_generic(email: str) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e or e == "n/a":
        return False
    local = e.split("@")[0]
    return local in GENERIC or any(local.startswith(g) for g in GENERIC)


def ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(n % 10,'th')}"


def existing_slugs() -> set[str]:
    have = set()
    for f in OUT.glob("*.md"):
        m = re.search(r"^slug:\s*(.+)$", f.read_text(encoding="utf-8"), re.M)
        if m:
            have.add(m.group(1).strip())
    return have


def body(company, region, town, count, pos, prev, nxt, email) -> str:
    # Neighbour clause adapts to edges of the list.
    if prev and nxt:
        neigh = (f"Alphabetically your listing sits between {prev} and {nxt} "
                 f"— position {pos} of {count} — which is fine, but not where "
                 f"click-throughs concentrate.")
    elif nxt:
        neigh = (f"Alphabetically you're near the top of the {region} list "
                 f"(position {pos} of {count}), just above {nxt} — but the "
                 f"#1 slot still sits above you.")
    elif prev:
        neigh = (f"Alphabetically you're near the foot of the {region} list "
                 f"(position {pos} of {count}), below {prev} — well past where "
                 f"click-throughs concentrate.")
    else:
        neigh = (f"You're one of {count} commercial installers we list in "
                 f"{region}.")
    return f"""Hi there,

{company} is one of {count} OZEV-authorised commercial installers we list across {region} on the new commercial-only directory at https://commercial-ev-installers.pages.dev. {neigh}

I'm opening a Featured slot for {town} and the {region} region page: £99 one-time for 12 months. Founder rate, capped at 25 sales or 30 June 2026, whichever first. Pins you to #1 on the {town} page, the {region} page, and the relevant commercial-service pages, with a FEATURED PARTNER badge.

I'll be straight — the directory launched in May 2026, traffic is still maturing. That's exactly why this rate is £99 and not £199. You're locking position before SEO compounds, and it's risk-free for a month: if you're not happy in the first 30 days, email me and I'll refund every penny — no questions, no forms. I write the refund cheque, not Stripe.

To claim or ask questions: https://commercial-ev-installers.pages.dev/featured/ — or reply to this email.

Thanks,
Greg Morris

—
hello@commercial-ev-installers.pages.dev · commercial-ev-installers.pages.dev
Prefer not to hear from me? Reply 'remove' and you're off this list for good. Privacy & contact: https://commercial-ev-installers.pages.dev/privacy/
"""


def main() -> int:
    raw = json.load(open(DATA, encoding="utf-8"))["installers"]
    have = existing_slugs()

    # Build per-region alphabetical lists of COMMERCIAL installers (the page
    # ordering the recipient actually sees).
    def is_commercial(i):
        return "Commercial" in (i.get("services") or [])

    regions: dict[str, list] = {}
    for i in raw:
        r = (i.get("region") or "").strip()
        if r and r != "N/A" and is_commercial(i):
            regions.setdefault(r, []).append(i)
    for r in regions:
        regions[r].sort(key=lambda x: x["name"].lower())

    # Candidates: generic mailbox + website + town + region + commercial.
    cands = []
    for i in raw:
        if not is_generic(i.get("email")):
            continue
        if (i.get("website") or "N/A") in ("", "N/A"):
            continue
        town = (i.get("town") or "").strip()
        region = (i.get("region") or "").strip()
        if not town or town == "N/A" or not region or region == "N/A":
            continue
        if not is_commercial(i):
            continue
        slug = slugify(f"{i['name']} {i.get('postcode','')}")
        if slug in have:
            continue
        cands.append(i)

    # Light quality ordering: commercial-only focus first, then region density
    # (more competition = Featured matters more), then name.
    def score(i):
        st = (i.get("service_text") or "").lower()
        commercial_only = "commercial installations only" in st
        region_size = len(regions.get(i.get("region", ""), []))
        return (0 if commercial_only else 1, -region_size, i["name"].lower())
    cands.sort(key=score)

    n = 51
    written = 0
    for i in cands:
        region = i["region"].strip()
        town = i["town"].strip()
        rlist = regions[region]
        names = [x["name"] for x in rlist]
        try:
            idx = next(k for k, x in enumerate(rlist)
                       if x.get("postcode") == i.get("postcode")
                       and x["name"] == i["name"])
        except StopIteration:
            idx = names.index(i["name"]) if i["name"] in names else 0
        count = len(rlist)
        pos = idx + 1
        prev = names[idx - 1] if idx > 0 else ""
        nxt = names[idx + 1] if idx < count - 1 else ""
        company = i["name"]
        slug = slugify(f"{company} {i.get('postcode','')}")
        subj = SUBJECTS[(n) % len(SUBJECTS)].format(
            town=town, region=region, company=company)
        fm = (f"---\nto: {i['email'].strip()}\nto_name: \nsubject: {subj}\n"
              f"slug: {slug}\nprospect_rank: {n:02d}\nstatus: ready\n---\n")
        text = fm + body(company, region, town, count, pos, prev, nxt,
                         i["email"].strip())
        (OUT / f"{n:02d}-{slug}.md").write_text(text, encoding="utf-8",
                                                newline="\n")
        n += 1
        written += 1

    print(f"[installers] candidate pool (generic mailbox + website + "
          f"town/region, not already drafted): {len(cands)}")
    print(f"[installers] wrote {written} new pitches "
          f"(ranks 51-{50 + written}) -> {OUT}")
    ready = len(list(OUT.glob("*.md")))
    print(f"[installers] outreach/featured now holds {ready} files total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
