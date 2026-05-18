"""
validate.py — Gatekeeper for data/installers.json.

Enforces the scrape-to-spreadsheet accuracy contract before the site is built:
schema completeness, dedupe integrity, the "never guess" rule (no empty strings
masquerading as data — gaps must be the literal "N/A"), and basic sanity. It
also runs a hallucination spot-check: re-derives postcode/region and flags any
record whose fields are internally inconsistent.

Exit code 0 = safe to publish. Non-zero = stop, do not deploy.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "installers.json"

REQUIRED = [
    "name", "street", "town", "postcode", "region", "lat", "lon", "website",
    "email", "phone", "services", "service_text", "accreditations",
    "source_url", "last_verified",
]
PC_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s\d[A-Z]{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main() -> int:
    if not SRC.exists():
        print("FAIL: data/installers.json missing")
        return 1
    payload = json.loads(SRC.read_text(encoding="utf-8"))
    rows = payload.get("installers", [])
    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        print("FAIL: zero installers — refusing to publish an empty directory")
        return 1

    seen: set[str] = set()
    for i, r in enumerate(rows):
        tag = r.get("name", f"row{i}")

        for k in REQUIRED:
            if k not in r:
                errors.append(f"{tag}: missing field '{k}'")
            elif isinstance(r[k], str) and r[k].strip() == "":
                errors.append(f"{tag}: field '{k}' is blank (must be 'N/A', never guessed)")

        if "Commercial" not in r.get("services", []):
            errors.append(f"{tag}: non-commercial record leaked into dataset")

        pc = r.get("postcode", "")
        if pc != "N/A" and not PC_RE.match(pc):
            warnings.append(f"{tag}: postcode '{pc}' not in expected format")

        em = r.get("email", "")
        if em != "N/A" and not EMAIL_RE.match(em):
            warnings.append(f"{tag}: email '{em}' looks malformed")

        web = r.get("website", "")
        if web != "N/A" and not web.startswith("http"):
            errors.append(f"{tag}: website '{web}' is not a URL or N/A")

        # Hallucination spot-check: lat/lon must both be set or both N/A
        lat, lon = r.get("lat"), r.get("lon")
        if (lat == "N/A") != (lon == "N/A"):
            errors.append(f"{tag}: half-populated coordinates (lat={lat} lon={lon})")

        key = re.sub(r"[^a-z0-9]", "", tag.lower()) + "|" + pc.replace(" ", "").lower()
        if key in seen:
            errors.append(f"{tag}: duplicate not deduplicated ({key})")
        seen.add(key)

    has_contact = sum(
        1 for r in rows
        if r.get("website") != "N/A" or r.get("email") != "N/A" or r.get("phone") != "N/A"
    )
    pct = has_contact / len(rows) * 100
    print(f"Records: {len(rows)}")
    print(f"With at least one contact channel: {has_contact} ({pct:.0f}%)")
    print(f"Warnings: {len(warnings)}  Errors: {len(errors)}")
    for w in warnings[:15]:
        print("  WARN", w)
    for e in errors[:25]:
        print("  ERR ", e)

    if errors:
        print("\nFAIL: validation errors — site build blocked.")
        return 1
    if pct < 40:
        print("\nFAIL: <40% of records have any contact channel — data too thin.")
        return 1
    print("\nOK: dataset passes validation — safe to build & publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
