#!/usr/bin/env python3
"""
renovation_budget.py — quick scope-tier renovation estimate for the STR deal analyzer.

The deal model takes rehab as a single number (`rehab` -> cell C21). Rather than guess it,
pick a SCOPE TIER and the budget is keyed off square footage: rehab = sqft x $/sqft.

The $25 / $50 / $75 / $100 per-sqft model (StayAscend's standard):
    light    $25/sqft   cosmetic refresh
    moderate $50/sqft   standard STR conversion
    heavy    $75/sqft   extensive remodel
    full    $100/sqft   full gut / high-end

These are ALL-IN construction $/sqft (materials + labor + contingency + permits). They are
NOT furnishing — furniture/decor is the separate `furn_per_sqft` input (~$18-30/sqft). Don't
double-count. Tiers are deliberately round and a touch conservative; override with --rate for
a real contractor takeoff. For a precise line-item estimate use the workbook's Renovation
Calculator tab (itemized against the Renovation Rates tab).

Usage:
    python3 renovation_budget.py --sqft 1727 --tier moderate
    python3 renovation_budget.py --spec /tmp/deal.json --tier light        # read sqft from a spec
    python3 renovation_budget.py --sqft 1727 --tier 75                     # tier by $/sqft number
    python3 renovation_budget.py --sqft 1727 --rate 40                     # custom $/sqft
    python3 renovation_budget.py --sqft 1727 --tier moderate --json        # spec fragment
    python3 renovation_budget.py --sqft 1727 --all                         # show every tier
"""
import argparse, json, sys

# tier key -> ($/sqft, label, one-line scope)
TIERS = {
    "none":     (0,   "No work",        "move-in ready; no renovation"),
    "light":    (25,  "Cosmetic refresh", "paint, LVP in main areas, fixtures, deep clean, minor repairs"),
    "moderate": (50,  "Standard STR conversion", "flooring + paint throughout, kitchen + bath updates, some mechanical"),
    "heavy":    (75,  "Extensive remodel", "kitchen + baths remodeled, flooring, HVAC, electrical, windows/doors"),
    "full":     (100, "Full gut / high-end", "everything to the studs, premium finishes"),
}
ALIASES = {"cosmetic": "light", "refresh": "light", "standard": "moderate",
           "gut": "full", "0": "none", "25": "light", "50": "moderate", "75": "heavy", "100": "full"}


def resolve_tier(tier):
    if tier is None:
        return None
    t = str(tier).strip().lower()
    t = ALIASES.get(t, t)
    if t not in TIERS:
        sys.exit(f"Unknown tier '{tier}'. Use one of: {', '.join(TIERS)} "
                 f"(or aliases {', '.join(ALIASES)}).")
    return t


def budget(sqft, rate):
    return round(sqft * rate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqft", type=float, default=None)
    ap.add_argument("--spec", default=None, help="read sqft from a deal spec JSON")
    ap.add_argument("--tier", default=None, help="none|light|moderate|heavy|full (or 25/50/75/100)")
    ap.add_argument("--rate", type=float, default=None, help="custom $/sqft (overrides --tier)")
    ap.add_argument("--json", action="store_true", help="print a deal-spec fragment")
    ap.add_argument("--all", action="store_true", help="show the budget at every tier")
    args = ap.parse_args()

    sqft = args.sqft
    if sqft is None and args.spec:
        sqft = json.load(open(args.spec)).get("sqft")
    if not sqft:
        sys.exit("Need square footage: pass --sqft N or --spec <deal.json> with a sqft key.")

    if args.all:
        print(f"Renovation budget by tier — {sqft:,.0f} sqft\n")
        print(f"  {'tier':10}{'$/sqft':>8}{'budget':>12}   scope")
        for k, (rate, label, scope) in TIERS.items():
            print(f"  {k:10}{rate:>8}{budget(sqft, rate):>12,}   {label}: {scope}")
        print("\n  (all-in construction; NOT furnishing. Set spec 'rehab' to the chosen budget.)")
        return

    if args.rate is not None:
        rate, label, scope = args.rate, "Custom", f"custom ${args.rate}/sqft"
    else:
        t = resolve_tier(args.tier)
        if t is None:
            sys.exit("Pick a scope: --tier light|moderate|heavy|full, --rate N, or --all.")
        rate, label, scope = TIERS[t]
    rehab = budget(sqft, rate)
    note = f"Renovation: {label} (~${rate:.0f}/sqft x {sqft:,.0f} sqft = ${rehab:,.0f} all-in; {scope})."

    if args.json:
        print(json.dumps({"rehab": rehab}, indent=2))
        print(f"# append to spec 'notes': {note}", file=sys.stderr)
        return

    print(f"Renovation budget — {sqft:,.0f} sqft")
    print(f"  tier:    {label}  (${rate:.0f}/sqft)")
    print(f"  scope:   {scope}")
    print(f"  REHAB:   ${rehab:,.0f}   (all-in construction; furniture is separate)")
    print(f"\n  -> set spec \"rehab\": {rehab}.  Note: {note}")


if __name__ == "__main__":
    main()
