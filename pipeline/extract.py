"""
extract.py — Build the OZEV commercial EV-charger-installer dataset.

Queries the public GOV.UK OZEV tool (Open Government Licence v3.0) across a
UK-wide postcode grid, parses the 10-nearest results per postcode, keeps only
installers offering COMMERCIAL installations, deduplicates, and writes:

  data/installers.json   normalized records (site is generated from this)
  data/installers.csv    scrape-to-spreadsheet column order + extra columns
  data/raw_snapshot.json every parsed record with its source postcode query
  data/refresh_report.md human-readable diff vs the previous installers.json

Accuracy rule (from scrape-to-spreadsheet): never guess. Missing = "N/A".
Polite: ~1.1s between requests, descriptive User-Agent, retries, timeouts.
Fully self-contained; no API keys; safe to run unattended on a schedule.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

TOOL_URL = "https://www.gov.uk/electric-vehicle-chargepoint-installers"
USER_AGENT = (
    "ev-installer-directory/1.0 (+https://github.com/; aggregates OGL v3.0 "
    "OZEV public installer data into a browsable directory; contact via site)"
)
REQUEST_GAP_S = 2.0          # base politeness gap between successful requests
TIMEOUT_S = 30
MAX_RETRIES = 4
BACKOFF_429_S = [30, 90, 180, 300]   # escalating cool-off when rate-limited

POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
LOC_RE = re.compile(r"q=loc:([-\d.]+)%2C([-\d.]+)")

# Postcode-area -> UK region (approximate, for the directory's region filter).
AREA_REGION = {
    # London
    "E": "London", "EC": "London", "N": "London", "NW": "London", "SE": "London",
    "SW": "London", "W": "London", "WC": "London",
    # South East
    "BR": "South East", "CR": "South East", "DA": "South East", "GU": "South East",
    "HA": "South East", "IG": "South East", "KT": "South East", "ME": "South East",
    "RM": "South East", "SM": "South East", "TW": "South East", "UB": "South East",
    "EN": "South East", "RH": "South East", "RG": "South East", "SL": "South East",
    "OX": "South East", "MK": "South East", "HP": "South East", "AL": "South East",
    "SG": "South East", "LU": "South East", "CT": "South East", "TN": "South East",
    "BN": "South East", "PO": "South East",
    # South West
    "BS": "South West", "BA": "South West", "GL": "South West", "SN": "South West",
    "SP": "South West", "DT": "South West", "BH": "South West", "TA": "South West",
    "EX": "South West", "PL": "South West", "TQ": "South West", "TR": "South West",
    # East of England
    "CB": "East of England", "CO": "East of England", "CM": "East of England",
    "SS": "East of England", "IP": "East of England", "NR": "East of England",
    "PE": "East of England",
    # Midlands
    "B": "West Midlands", "CV": "West Midlands", "DY": "West Midlands",
    "WS": "West Midlands", "WV": "West Midlands", "ST": "West Midlands",
    "TF": "West Midlands", "WR": "West Midlands", "HR": "West Midlands",
    "SY": "West Midlands",
    "DE": "East Midlands", "LE": "East Midlands", "NG": "East Midlands",
    "LN": "East Midlands", "NN": "East Midlands",
    # Yorkshire & Humber
    "LS": "Yorkshire & Humber", "S": "Yorkshire & Humber",
    "HD": "Yorkshire & Humber", "HX": "Yorkshire & Humber",
    "WF": "Yorkshire & Humber", "BD": "Yorkshire & Humber",
    "HG": "Yorkshire & Humber", "YO": "Yorkshire & Humber",
    "HU": "Yorkshire & Humber", "DN": "Yorkshire & Humber",
    # North West
    "M": "North West", "L": "North West", "PR": "North West", "BB": "North West",
    "BL": "North West", "OL": "North West", "WN": "North West", "WA": "North West",
    "SK": "North West", "CW": "North West", "CH": "North West", "LA": "North West",
    "CA": "North West", "FY": "North West", "IM": "North West",
    # North East
    "NE": "North East", "SR": "North East", "DH": "North East", "DL": "North East",
    "TS": "North East",
    # Scotland
    "EH": "Scotland", "G": "Scotland", "AB": "Scotland", "DD": "Scotland",
    "DG": "Scotland", "FK": "Scotland", "IV": "Scotland", "KA": "Scotland",
    "KW": "Scotland", "KY": "Scotland", "ML": "Scotland", "PA": "Scotland",
    "PH": "Scotland", "TD": "Scotland", "HS": "Scotland", "ZE": "Scotland",
    # Wales
    "CF": "Wales", "SA": "Wales", "NP": "Wales", "LL": "Wales", "LD": "Wales",
    # Northern Ireland
    "BT": "Northern Ireland",
}


def log(msg: str) -> None:
    print(f"[extract] {msg}", flush=True)


def load_postcodes() -> list[str]:
    f = Path(__file__).resolve().parent / "coverage_postcodes.txt"
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def area_of(postcode: str) -> str:
    m = re.match(r"^([A-Z]{1,2})", postcode.upper().replace(" ", ""))
    return m.group(1) if m else ""


def region_for(postcode: str) -> str:
    return AREA_REGION.get(area_of(postcode), "N/A")


class GovUKClient:
    """Holds a session + fresh Rails CSRF token for the OZEV POST endpoint."""

    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.token = ""

    def refresh_token(self) -> bool:
        for attempt in range(MAX_RETRIES):
            try:
                r = self.s.get(TOOL_URL, timeout=TIMEOUT_S)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                meta = soup.find("meta", attrs={"name": "csrf-token"})
                if meta and meta.get("content"):
                    self.token = meta["content"]
                    return True
                hidden = soup.find("input", attrs={"name": "authenticity_token"})
                if hidden and hidden.get("value"):
                    self.token = hidden["value"]
                    return True
            except requests.RequestException as e:
                log(f"token fetch failed (try {attempt+1}): {e}")
                time.sleep(2 * (attempt + 1))
        return False

    def search(self, postcode: str) -> str | None:
        """POST a postcode, return result HTML, or None on failure."""
        for attempt in range(MAX_RETRIES):
            try:
                r = self.s.post(
                    TOOL_URL,
                    data={"authenticity_token": self.token, "postcode": postcode},
                    timeout=TIMEOUT_S,
                )
                if r.status_code == 429:  # rate limited -> long cool-off, keep trying
                    ra = r.headers.get("Retry-After")
                    wait = (int(ra) if ra and ra.isdigit()
                            else BACKOFF_429_S[min(attempt, len(BACKOFF_429_S) - 1)])
                    log(f"{postcode}: 429 rate-limited, cooling off {wait}s")
                    time.sleep(wait)
                    self.refresh_token()
                    continue
                if r.status_code in (403, 422):  # stale CSRF -> refresh and retry
                    log(f"{postcode}: {r.status_code}, refreshing token")
                    if not self.refresh_token():
                        return None
                    continue
                r.raise_for_status()
                return r.text
            except requests.RequestException as e:
                log(f"{postcode}: request failed (try {attempt+1}): {e}")
                time.sleep(5 * (attempt + 1))
        return None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_results(html: str, query_pc: str) -> list[dict]:
    """Extract installer records from one OZEV results page."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup
    records = []
    for li in main.find_all("li"):
        h3 = li.find(["h3", "h2"])
        if not h3:
            continue
        name = clean(h3.get_text())
        if not name:
            continue

        # lat/lon from the Google Maps link
        lat = lon = "N/A"
        gmap = li.find("a", href=re.compile(r"maps\.google"))
        if gmap:
            m = LOC_RE.search(gmap.get("href", ""))
            if m:
                lat, lon = m.group(1), m.group(2)

        # website: first external http link that isn't a map/mailto
        website = "N/A"
        for a in li.find_all("a", href=True):
            href = a["href"]
            if href.startswith("mailto:"):
                continue
            if "maps.google" in href or "openstreetmap.org" in href:
                continue
            if href.startswith("http"):
                website = href.strip()
                break

        # email
        email = "N/A"
        ml = li.find("a", href=re.compile(r"^mailto:", re.I))
        if ml:
            email = ml["href"].split(":", 1)[1].strip()

        # phone + service descriptor from the text paragraphs
        phone = "N/A"
        service_text = ""
        for p in li.find_all("p"):
            t = clean(p.get_text())
            if re.search(r"telephone", t, re.I):
                pm = re.search(r"telephone:\s*(.+)", t, re.I)
                if pm:
                    phone = pm.group(1).strip()
            if re.search(r"installation", t, re.I):
                service_text = t

        # Address: strings between the name and "View on Google Maps"
        strings = [clean(s) for s in li.stripped_strings]
        strings = [s for s in strings if s and s != ","]
        addr_parts: list[str] = []
        started = False
        for s in strings:
            if not started:
                if s == name:
                    started = True
                continue
            if s.lower().startswith("view on "):
                break
            if s.lower().startswith(("http", "telephone:")) or "@" in s:
                continue
            if re.search(r"installation", s, re.I):
                continue
            addr_parts.append(s)
        full_address = ", ".join(addr_parts)

        pc_m = POSTCODE_RE.search(full_address)
        postcode = (
            f"{pc_m.group(1).upper()} {pc_m.group(2).upper()}" if pc_m else "N/A"
        )
        town = addr_parts[-2] if len(addr_parts) >= 2 and pc_m else (
            addr_parts[-1] if addr_parts else "N/A"
        )
        street = ", ".join(addr_parts[:-2]) if len(addr_parts) >= 3 else (
            addr_parts[0] if addr_parts else "N/A"
        )

        # Service classification
        st = service_text.lower()
        commercial = "commercial" in st
        residential = "residential" in st
        if commercial and residential:
            services = ["Commercial", "Residential"]
        elif commercial:
            services = ["Commercial"]
        elif residential:
            services = ["Residential"]
        else:
            services = []

        records.append(
            {
                "name": name,
                "street": street or "N/A",
                "town": town or "N/A",
                "postcode": postcode,
                "region": region_for(postcode) if postcode != "N/A"
                else region_for(query_pc),
                "lat": lat,
                "lon": lon,
                "website": website,
                "email": email,
                "phone": phone,
                "services": services,
                "service_text": service_text or "N/A",
                # Not provided by the source — never fabricated:
                "accreditations": ["OZEV authorised"],
                "grant_support": "N/A",
                "trading_status": "N/A",
                "source_url": TOOL_URL,
                "source_query_postcode": query_pc,
            }
        )
    return records


def dedupe_key(r: dict) -> str:
    return (
        re.sub(r"[^a-z0-9]", "", r["name"].lower())
        + "|"
        + r["postcode"].replace(" ", "").lower()
    )


def load_previous() -> dict[str, dict]:
    f = DATA / "installers.json"
    if not f.exists():
        return {}
    try:
        prev = json.loads(f.read_text(encoding="utf-8"))
        return {dedupe_key(r): r for r in prev.get("installers", [])}
    except (json.JSONDecodeError, OSError):
        return {}


def write_outputs(records: list[dict], stats: dict) -> None:
    today = datetime.date.today().isoformat()
    for r in records:
        r["last_verified"] = today

    payload = {
        "generated": today,
        "source": TOOL_URL,
        "licence": "Open Government Licence v3.0",
        "count": len(records),
        "installers": sorted(records, key=lambda x: x["name"].lower()),
    }
    (DATA / "installers.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    cols = [
        "Name", "First Name", "Last Name", "Title / Role", "Email", "Phone",
        "Website", "Address", "City", "State", "Country", "Industry",
        "Description", "LinkedIn", "Twitter / X", "Facebook", "Instagram",
        "Year Founded", "Employees", "Revenue", "Source URL", "Notes",
        "Region", "Services", "Accreditations", "Latitude", "Longitude",
        "Last Verified",
    ]
    with (DATA / "installers.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(cols)
        for r in payload["installers"]:
            w.writerow([
                r["name"], "N/A", "N/A", "N/A", r["email"], r["phone"],
                r["website"],
                ", ".join(p for p in [r["street"], r["town"]] if p != "N/A"),
                r["town"], r["region"], "United Kingdom",
                "EV chargepoint installation",
                r["service_text"], "N/A", "N/A", "N/A", "N/A", "N/A", "N/A",
                "N/A", r["source_url"],
                "OZEV-authorised; commercial installs", r["region"],
                "; ".join(r["services"]), "; ".join(r["accreditations"]),
                r["lat"], r["lon"], r["last_verified"],
            ])

    # Diff vs previous run
    prev = load_previous_for_diff()
    cur = {dedupe_key(r): r for r in records}
    added = [cur[k]["name"] for k in cur if k not in prev]
    removed = [prev[k]["name"] for k in prev if k not in cur]
    report = [
        f"# Refresh report — {today}",
        "",
        f"- Postcodes queried: {stats['queried']}",
        f"- Postcodes with results: {stats['hit']}",
        f"- Raw records parsed: {stats['raw']}",
        f"- Commercial installers (deduplicated): {len(records)}",
        f"- Added since last run: {len(added)}",
        f"- Removed since last run: {len(removed)}",
        "",
    ]
    if added:
        report.append("## Added\n" + "\n".join(f"- {n}" for n in sorted(added)[:200]))
    if removed:
        report.append("\n## Removed\n" + "\n".join(f"- {n}" for n in sorted(removed)[:200]))
    (DATA / "refresh_report.md").write_text("\n".join(report), encoding="utf-8")


# previous snapshot captured before overwrite
_PREV_FOR_DIFF: dict[str, dict] = {}


def load_previous_for_diff() -> dict[str, dict]:
    return _PREV_FOR_DIFF


def main() -> int:
    global _PREV_FOR_DIFF
    _PREV_FOR_DIFF = load_previous()

    postcodes = load_postcodes()
    log(f"{len(postcodes)} anchor postcodes loaded")

    client = GovUKClient()
    if not client.refresh_token():
        log("FATAL: could not obtain CSRF token from GOV.UK")
        return 1
    log("CSRF token acquired")

    raw: list[dict] = []
    seen: dict[str, dict] = {}
    stats = {"queried": 0, "hit": 0, "raw": 0}

    for i, pc in enumerate(postcodes, 1):
        stats["queried"] += 1
        html = client.search(pc)
        if html is None:
            log(f"{pc}: no response (skipped)")
            time.sleep(REQUEST_GAP_S)
            continue
        recs = parse_results(html, pc)
        if recs:
            stats["hit"] += 1
        for r in recs:
            raw.append(r)
            if "Commercial" not in r["services"]:
                continue
            k = dedupe_key(r)
            if k not in seen:
                seen[k] = r
        if i % 25 == 0 or i == len(postcodes):
            log(f"{i}/{len(postcodes)} queried — {len(seen)} commercial so far")
        time.sleep(REQUEST_GAP_S)

    stats["raw"] = len(raw)
    records = list(seen.values())

    (DATA / "raw_snapshot.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_outputs(records, stats)
    log(
        f"DONE — {len(records)} commercial installers "
        f"({stats['raw']} raw, {stats['hit']}/{stats['queried']} postcodes hit)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
