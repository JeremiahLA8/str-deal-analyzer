#!/usr/bin/env python3
"""
permit_costs.py — per-market permit-cost layer for deal underwriting.

Two permit types matter to a deal:
  1. STR operating permit / license  (the right to operate a vacation rental)
  2. Building permit                 (for any reno or amenity build, scales with value)

This module holds researched, source-cited fee data per market and computes the
building permit fee for a given construction valuation. deal_scenarios.py uses it so
amenity permits are real numbers, not a flat guess. Human-readable companion docs:
references/str-deal-analyzer/permit-costs/<market>.md

Add a market by researching its county fee schedule (see the research routine in the
/analyze-deal skill) and appending to MARKETS. Flag anything that needs a phone call.

CLI:
    python3 scripts/permit_costs.py --market kauai-hi --valuation 22000
    python3 scripts/permit_costs.py --market kauai-hi --info
"""
import argparse, sys

MARKETS = {
    "kauai-hi": {
        "label": "Kauai County, HI",
        "source": "County of Kauai Appendix A — Fees, Rates, Assessments & Taxes "
                  "(kauai.granicus.com), Building Division Permit Brief (2013), verified 2026-06-19",
        # building permit base-fee brackets: (val_min, val_max, fee_at_min, fee_at_max)
        # linear within a bracket; last two brackets are formula-based (see code).
        "building_brackets": [
            (1, 500, 15, 15),
            (501, 2000, 17, 45),
            (2001, 25000, 53, 229),
            (25001, 50000, 236, 404),
            (50001, 100000, 410, 704),
        ],
        "building_formula_over_100k": lambda v: 704 + 5 * ((v - 100000) / 1000),
        "revolving_fund_pct": 0.15,   # "+15% Building Revolving Fund" on the base fee
        "plan_review_pct": 0.15,      # 15% plan review fee on the base fee
        # STR operating permit notes (situational — set the setup line by hand):
        "str_notes": {
            "vda_required": "TVR allowed ONLY in a Visitor Destination Area (VDA) or with a "
                            "pre-2009 grandfathered Non-Conforming Use (NCU) cert.",
            "ncu_renewal_annual": 500,   # Vacation Rental Non-Conforming Cert (Renewal)
            "get_license_one_time": 20,  # Hawaii GET license registration
            "note": "Princeville is a VDA, so a VDA unit registers as a permitted TVR (no NCU). "
                    "The $500/yr NCU renewal applies to non-VDA grandfathered units only.",
        },
        # pass-through taxes on revenue (collected from guests, not owner cost):
        "taxes": {"get_pct": 0.045, "state_tat_pct": 0.11, "county_tat_pct": 0.03,
                  "note": "GET 4.5% + State TAT 11% (2026, Act 96) + Kauai TAT 3% = ~18.5% on rents."},
        # annual REAL PROPERTY tax — rate per $1,000 assessed, tiered/progressive (FY2025-26).
        # An STR is taxed in the VACATION RENTAL class, ~4.4x the owner-occupied rate.
        "property_tax_per_1000": {
            "owner_occupied": [(float("inf"), 2.59)],
            "vacation_rental": [(1_000_000, 11.30), (2_500_000, 11.75), (float("inf"), 12.20)],
            "non_owner_residential": [(1_300_000, 5.45), (2_000_000, 6.05), (float("inf"), 9.40)],
            "note": "FY2025-26 Kauai. STR = vacation_rental class. Use assessed value; purchase "
                    "price is a conservative proxy until reassessment.",
        },
        # cost reality for this market (defaults run low on the mainland template)
        "cost_factors": {
            "furnishing_per_sqft": 30,   # HI: shipping + island labor; mainland ~$18-22
            "insurance_note": "HI condo HO-6 + STR liability runs higher (hurricane/flood "
                              "exposure). Verify with a local broker; don't assume mainland pricing.",
        },
    },
}


def property_tax_estimate(market, assessed_value, classification="vacation_rental"):
    """Annual real property tax via the market's progressive tier table."""
    tiers = MARKETS[market]["property_tax_per_1000"][classification]
    tax, prev = 0.0, 0
    for cap, rate in tiers:
        portion = min(assessed_value, cap) - prev
        if portion <= 0:
            break
        tax += portion / 1000 * rate
        prev = cap
        if assessed_value <= cap:
            break
    return round(tax)


def tax_tier_warning(market, property_tax, assessed_value):
    """Flag a property_tax that looks like the wrong (owner-occupied) tier for an STR."""
    if not (assessed_value and property_tax):
        return None
    vr = property_tax_estimate(market, assessed_value, "vacation_rental")
    if property_tax < vr * 0.6:   # well below the vacation-rental estimate
        return (f"property_tax ${property_tax:,.0f} looks low for an STR. Vacation-rental class "
                f"on ${assessed_value:,.0f} assessed is ~${vr:,.0f}. Confirm you're not using the "
                f"owner-occupied tier.")
    return None


def building_permit_fee(market, valuation, breakdown=False):
    """Total building permit cost (base + revolving fund + plan review) for a construction value."""
    m = MARKETS[market]
    v = max(0, float(valuation))
    base = None
    for vmin, vmax, fmin, fmax in m["building_brackets"]:
        if v <= vmax:
            frac = 0 if vmax == vmin else (max(v, vmin) - vmin) / (vmax - vmin)
            base = fmin + frac * (fmax - fmin)
            break
    if base is None:
        base = m["building_formula_over_100k"](v)
    revolving = base * m["revolving_fund_pct"]
    plan = base * m["plan_review_pct"]
    total = base + revolving + plan
    if breakdown:
        return {"valuation": v, "base": round(base), "revolving_fund": round(revolving),
                "plan_review": round(plan), "total": round(total)}
    return round(total)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="kauai-hi")
    ap.add_argument("--valuation", type=float, help="construction value to permit")
    ap.add_argument("--assessed", type=float, help="assessed/purchase value for property-tax estimate")
    ap.add_argument("--info", action="store_true", help="print market STR/tax notes")
    args = ap.parse_args()
    if args.market not in MARKETS:
        sys.exit(f"Unknown market '{args.market}'. Known: {', '.join(MARKETS)}")
    m = MARKETS[args.market]
    print(f"{m['label']}\n  source: {m['source']}\n")
    if args.info or (args.valuation is None and args.assessed is None):
        s = m["str_notes"]
        print("STR operating permit:")
        print(f"  {s['vda_required']}")
        print(f"  {s['note']}")
        print(f"  NCU renewal (non-VDA): ${s['ncu_renewal_annual']}/yr | GET license: ${s['get_license_one_time']} one-time")
        t = m["taxes"]
        print(f"\nPass-through taxes (guest-collected): {t['note']}")
        pt = m["property_tax_per_1000"]
        print(f"\nAnnual property tax (per $1,000 assessed): {pt['note']}")
        print(f"  owner-occupied ${pt['owner_occupied'][0][1]:.2f}  vs  vacation-rental "
              f"${pt['vacation_rental'][0][1]:.2f}-{pt['vacation_rental'][-1][1]:.2f} (tiered)")
        print(f"\nBuilding permit examples:")
        for val in (14000, 22000, 35000, 65000, 85000):
            print(f"  ${val:>7,} build -> ${building_permit_fee(args.market, val):>5,} permit")
    if args.assessed is not None:
        vr = property_tax_estimate(args.market, args.assessed, "vacation_rental")
        oo = property_tax_estimate(args.market, args.assessed, "owner_occupied")
        print(f"\nProperty tax on ${args.assessed:,.0f} assessed:")
        print(f"  vacation-rental class: ${vr:,}/yr   (owner-occupied would be ${oo:,}/yr)")
        print(f"  -> use the vacation-rental number for an STR underwrite.")
    if args.valuation is not None:
        b = building_permit_fee(args.market, args.valuation, breakdown=True)
        print(f"\nBuilding permit for ${b['valuation']:,.0f} construction value:")
        print(f"  base ${b['base']:,} + revolving fund ${b['revolving_fund']:,} "
              f"+ plan review ${b['plan_review']:,}  =  ${b['total']:,}")


if __name__ == "__main__":
    main()
