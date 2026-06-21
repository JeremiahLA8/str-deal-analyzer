#!/usr/bin/env python3
"""
deal_scenarios.py — run a deal across amenity build-out scenarios.

Toggles hot tub / pool options on top of a base deal spec: folds each amenity's
BUILD COST (from the Renovation Rates tab) into the cash invested, applies a
revenue lift, adds the ongoing upkeep, and prints CoC / cash flow / DSCR for each
combination so you can see which build-outs pay for themselves.

Reuses the validated formula chain from fill_deal_analyzer.compute().

Usage:
    python3 scripts/deal_scenarios.py                 # uses the 3880 Wyllie base below
    python3 scripts/deal_scenarios.py --spec spec.json
    python3 scripts/deal_scenarios.py --scope low     # low/mid/high build cost + lift

Each amenity carries ONE revenue premium (`rev_lift`), not separate ADR + occupancy lifts —
a comp-measured premium already blends both, so compounding them double-counts (an early bug
that turned a ~13% pool+hot-tub lift into +44%). The defaults are CONSERVATIVE and market-
agnostic; they are a fallback. Prefer deriving the with-amenity revenue directly from amenity-
matched comps, and override per-deal via the spec's `amenity_lifts` = {key: rev_lift} with the
premium measured for that market. Pool value is highly market-dependent (big in inland/desert
summers, soft in beach/community-pool markets), so the generic default is deliberately low.
"""
import argparse, copy, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from fill_deal_analyzer import compute, CELLS  # reuse the engine
from permit_costs import building_permit_fee, MARKETS  # per-market permit layer

# Build costs are MID from references/str-deal-analyzer Renovation Rates.
# cost = {low, mid, high}; contingency + permits added on top (per Reno Calculator).
# rev_lift = TOTAL revenue premium for the amenity (one number, not ADR x occ — a comp-measured
#   premium already blends both, so compounding them double-counts). opex_mo = added monthly upkeep.
# condo_ok = is this physically/HOA-plausibly addable to a condo/townhome unit.
# These rev_lifts are CONSERVATIVE, market-agnostic DEFAULTS and a fallback only. Prefer deriving
# the with-amenity revenue straight from amenity-matched comps; when you have a comp-measured
# premium for the market, override per-deal via the spec's `amenity_lifts` = {key: rev_lift}.
AMENITIES = {
    "hot_tub":     dict(label="Hot tub",          cost=(7000, 14000, 22000),
                        rev_lift=0.05, opex_mo=150, condo_ok="maybe (HOA approval)"),
    "plunge_pool": dict(label="Plunge pool",      cost=(25000, 35000, 50000),
                        rev_lift=0.07, opex_mo=300, condo_ok="no (no private land)"),
    "pool_fiber":  dict(label="Pool (fiberglass)", cost=(45000, 65000, 85000),
                        rev_lift=0.09, opex_mo=350, condo_ok="no (no private land)"),
    "pool_gunite": dict(label="Pool (gunite)",    cost=(60000, 85000, 110000),
                        rev_lift=0.11, opex_mo=400, condo_ok="no (no private land)"),
}
CONTINGENCY = 0.12   # Reno Calculator default on hard costs
# building permits are computed per-market from construction valuation (permit_costs.py),
# not a flat guess. Falls back to a flat estimate for markets not yet researched.
FALLBACK_PERMIT = 700

# Default base = 3880 Wyllie Rd #8C (condo, comp-derived base).
DEFAULT_SPEC = {
    "purchase_price": 970000, "arv": 970000, "down_pct": 0.25, "closing_pct": 0.01,
    "sqft": 1532, "rehab": 0, "setup_expenses": 3000, "furn_per_sqft": 20,
    "legal": 1000, "permits": 700, "photos": 700,
    "interest_rate": 0.07, "term_years": 30, "interest_only": "No", "pmi_pct": 0,
    "adr": 540, "occupancy": 0.57, "active_days": 365,
    "airbnb_pct": 0.70, "vrbo_pct": 0.15, "booking_pct": 0.10, "direct_pct": 0.05,
    "airbnb_fee": 0.15, "vrbo_fee": 0.07, "booking_fee": 0.15, "processing_fee": 0.029,
    "turnovers_mo": 5, "cost_per_turnover": 310, "mgmt_fee_pct": 0.15,
    "property_tax": 10182, "insurance": 2000, "hoa_annual": 18600,
    "repairs_mo": 200, "supplies_per_turn": 25, "refunds_mo": 50,
    "utilities_mo": 150, "internet_mo": 0, "landscaping_mo": 0, "spa_mo": 0,
    "tax_bracket": 0.35, "land_pct": 0.20, "property_type": "Condo / Townhome",
}
SCOPE_IDX = {"low": 0, "mid": 1, "high": 2}


def apply(base, ops, scope, market):
    """ops = list of (amenity_key, direction): +1 = ADD it, -1 = REMOVE an existing one."""
    s = copy.deepcopy(base)
    build, opex_mo, notes = 0.0, 0.0, []
    rev_mult = 1.0
    lifts = base.get("amenity_lifts", {})           # per-deal comp-measured overrides of rev_lift
    for key, d in ops:
        a = AMENITIES[key]
        lift = lifts.get(key, a["rev_lift"])
        if d > 0:                                   # ADD: build cost + upkeep + revenue lift
            hard = a["cost"][SCOPE_IDX[scope]] * (1 + CONTINGENCY)
            permit = building_permit_fee(market, hard) if market in MARKETS else FALLBACK_PERMIT
            build += hard + permit
            opex_mo += a["opex_mo"]
            rev_mult *= (1 + lift)
            notes.append("+ " + a["label"])
        else:                                       # REMOVE: save upkeep, lose the revenue lift
            opex_mo -= a["opex_mo"]
            rev_mult /= (1 + lift)
            notes.append("− " + a["label"])
    s["rehab"] = base.get("rehab", 0) + build
    # one revenue premium, applied to ADR (rev = adr x days x occ, so this scales revenue 1:1 at
    # fixed occupancy) AND to gross_override if the deal uses one — no ADR/occ double-count.
    s["adr"] = base.get("adr", 0) * rev_mult
    s["spa_mo"] = max(0.0, base.get("spa_mo", 0) + opex_mo)
    go = base.get("gross_override", 0) or 0
    if go > 0:
        s["gross_override"] = go * rev_mult
    return s, build, " ".join(notes) if notes else "(current, no change)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=None, help="base deal spec JSON (defaults to 3880 Wyllie #8C)")
    ap.add_argument("--scope", choices=["low", "mid", "high"], default="mid")
    ap.add_argument("--market", default=None, help="permit market override (else spec.permit_market)")
    args = ap.parse_args()
    # merge defaults UNDER a partial spec so compute() has every field. With no --spec, the
    # demo base is 3880 Wyllie (DEFAULT_SPEC). With a --spec, fall back to the TEMPLATE
    # defaults for omitted keys, not Wyllie's — else its HOA/tax/etc. leak into this deal.
    if args.spec:
        from fill_deal_analyzer import template_defaults
        base = json.load(open(args.spec))
        merged = template_defaults(); merged.update(base); base = merged
    else:
        base = dict(DEFAULT_SPEC)
    # market from the spec (or --market override); unknown -> flat permit fallback
    market = args.market or base.get("permit_market")

    # subject's CURRENT amenities (spec flags) drive which scenarios make sense
    has_spa = bool(base.get("has_hot_tub"))
    has_pool = bool(base.get("has_pool"))
    scenarios = [[]]                                     # base = current state
    # ADD what the property lacks
    if not has_spa:
        scenarios.append([("hot_tub", +1)])
    if not has_pool:
        scenarios += [[("plunge_pool", +1)], [("pool_fiber", +1)], [("pool_gunite", +1)]]
    if not has_spa and not has_pool:
        scenarios.append([("hot_tub", +1), ("pool_fiber", +1)])
    # REMOVE / value-of what the property already has
    if has_spa:
        scenarios.append([("hot_tub", -1)])
    if has_pool:
        scenarios.append([("pool_fiber", -1)])          # representative pool
    if has_spa and has_pool:
        scenarios.append([("hot_tub", -1), ("pool_fiber", -1)])

    is_condo = "condo" in str(base.get("property_type", "")).lower()
    mkt = (MARKETS[market]["label"] if market in MARKETS
           else f"no researched market — flat ${FALLBACK_PERMIT} permit fallback")
    cur = ", ".join([a for a, h in [("pool", has_pool), ("hot tub", has_spa)] if h]) or "none"
    print(f"Deal scenarios — {args.scope.upper()} cost/lift   (property: {base.get('property_type','?')})")
    print(f"Permits: {mkt}   |   current amenities: {cur}")
    if is_condo:
        print("NOTE: condo/townhome — private pools are not feasible (no private land); "
              "hot tub needs HOA approval. Pool rows shown for methodology only.")
    print(f"\n{'scenario':28}{'build $':>10}{'cash in':>11}{'gross':>10}{'cf/mo':>9}{'CoC':>8}{'DSCR':>7}   feasible?")
    for ops in scenarios:
        s, build, label = apply(base, ops, args.scope, market)
        m = compute(s)
        adds = [k for k, d in ops if d > 0]
        feas = "yes" if (not adds or not is_condo) else " / ".join(AMENITIES[k]["condo_ok"] for k in adds)
        print(f"{label:28}{build:>10,.0f}{m['total_cash']:>11,.0f}{m['gross']:>10,.0f}"
              f"{m['cf']/12:>9,.0f}{m['coc']:>8.1%}{m['dscr']:>7.2f}   {feas}")
    lift_src = "spec amenity_lifts (comp-measured)" if base.get("amenity_lifts") else "AMENITIES defaults"
    print("\n+ = add (build cost + upkeep, revenue up).  − = remove existing (save upkeep, revenue down).")
    print(f"  Revenue lift = ONE premium per amenity ({lift_src}); defaults conservative: hot tub +5%,")
    print("  plunge +7%, pool +9-11%. PREFER deriving with-amenity revenue from amenity-matched comps —")
    print("  override per-deal with spec 'amenity_lifts'. Adds include 12% contingency + computed permit.")


if __name__ == "__main__":
    main()
