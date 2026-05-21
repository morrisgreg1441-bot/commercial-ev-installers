"""Mark, remove, or list Featured installers in data/featured.json.

CLI for managing the paid-Featured roster used by site/generate.py.
Single source of truth: data/featured.json (key-ordered, machine-edited).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from difflib import get_close_matches
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = ROOT / "data" / "installers.json"
FEATURED = ROOT / "data" / "featured.json"
GENERATE = ROOT / "site" / "generate.py"

DEFAULT_README = "Edit via sales/mark_featured.py — do not hand-edit."
TIER_DEFAULT_PENCE = {"founder": 9900, "standard": 19900}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s or "x"


def compute_slugs() -> list[str]:
    """Replicate generate.py's slug assignment to enumerate valid slugs."""
    data = json.loads(INSTALLERS.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    slugs: list[str] = []
    for inst in data.get("installers", []):
        base = slugify(inst.get("name", "")) + "-" + slugify(inst.get("postcode", "x"))
        if base in seen:
            seen[base] += 1
            base = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
        slugs.append(base)
    return slugs


def load_featured() -> dict:
    if not FEATURED.exists():
        return {"_README": DEFAULT_README, "featured": []}
    data = json.loads(FEATURED.read_text(encoding="utf-8"))
    data.setdefault("_README", DEFAULT_README)
    data.setdefault("featured", [])
    return data


def save_featured(data: dict) -> None:
    ordered = {k: data[k] for k in sorted(data.keys())}
    FEATURED.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def print_table(entries: list[dict]) -> None:
    cols = ["slug", "tier", "order", "since", "until", "paid_pence"]
    if not entries:
        print("(no featured installers)")
        return
    rows = [cols] + [[str(e.get(c, "")) for c in cols] for e in entries]
    widths = [max(len(r[i]) for r in rows) for i in range(len(cols))]
    for i, row in enumerate(rows):
        line = " | ".join(cell.ljust(widths[j]) for j, cell in enumerate(row))
        print(line)
        if i == 0:
            print("-+-".join("-" * w for w in widths))


def cmd_list(data: dict) -> int:
    entries = sorted(data["featured"], key=lambda e: e.get("order", 9999))
    print_table(entries)
    return 0


def cmd_remove(data: dict, slug: str) -> int:
    before = len(data["featured"])
    data["featured"] = [e for e in data["featured"] if e.get("slug") != slug]
    if len(data["featured"]) == before:
        print(f"Slug '{slug}' was not in the featured list.", file=sys.stderr)
        return 1
    save_featured(data)
    print(f"Removed '{slug}'. Remaining:")
    cmd_list(data)
    return 0


def cmd_add(data: dict, args: argparse.Namespace, valid_slugs: set[str]) -> int:
    if args.slug not in valid_slugs:
        matches = get_close_matches(args.slug, list(valid_slugs), n=5, cutoff=0.4)
        print(f"Slug '{args.slug}' not found in data/installers.json.", file=sys.stderr)
        if matches:
            print("Did you mean:", file=sys.stderr)
            for m in matches:
                print(f"  - {m}", file=sys.stderr)
        return 2

    existing = next((e for e in data["featured"] if e.get("slug") == args.slug), None)
    if existing and not args.force:
        if sys.stdin.isatty():
            resp = input(f"'{args.slug}' already featured. Update? [y/N] ").strip().lower()
            if resp != "y":
                print("Aborted.")
                return 0
        else:
            print(f"Non-TTY: updating existing entry for '{args.slug}'.")

    today = date.today()
    until = today + timedelta(days=int(args.months) * 30)
    if args.order is not None:
        order = args.order
    else:
        existing_orders = [e.get("order", 0) for e in data["featured"] if e.get("slug") != args.slug]
        order = (max(existing_orders) + 1) if existing_orders else 1
    paid = args.paid_pence if args.paid_pence is not None else TIER_DEFAULT_PENCE[args.tier]

    entry = {
        "slug": args.slug,
        "tier": args.tier,
        "order": order,
        "since": today.isoformat(),
        "until": until.isoformat(),
        "paid_pence": paid,
    }
    data["featured"] = [e for e in data["featured"] if e.get("slug") != args.slug]
    data["featured"].append(entry)
    data["featured"].sort(key=lambda e: e.get("order", 9999))
    save_featured(data)

    verb = "Updated" if existing else "Marked"
    print(
        f"✓ {verb} {args.slug} as Featured ({args.tier}, order {order}), "
        f"valid {entry['since']} → {entry['until']}. Run with --rebuild to publish."
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Manage Featured installers.")
    p.add_argument("--slug")
    p.add_argument("--tier", choices=["founder", "standard"])
    p.add_argument("--order", type=int)
    p.add_argument("--paid-pence", type=int)
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--remove", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--rebuild", action="store_true")
    args = p.parse_args()

    try:
        data = load_featured()
    except OSError as e:
        print(f"Error loading featured.json: {e}", file=sys.stderr)
        return 1

    try:
        if args.remove:
            if not args.slug:
                print("--remove requires --slug", file=sys.stderr)
                return 1
            rc = cmd_remove(data, args.slug)
        elif args.list or (not args.slug and not args.tier):
            rc = cmd_list(data)
        else:
            if not args.slug or not args.tier:
                print("Add requires both --slug and --tier", file=sys.stderr)
                return 1
            valid = set(compute_slugs())
            rc = cmd_add(data, args, valid)
    except OSError as e:
        print(f"Filesystem error: {e}", file=sys.stderr)
        return 1

    if rc == 0 and args.rebuild:
        print("\n--- Rebuilding site ---")
        proc = subprocess.run([sys.executable, str(GENERATE)], cwd=str(ROOT))
        return proc.returncode
    return rc


if __name__ == "__main__":
    sys.exit(main())
