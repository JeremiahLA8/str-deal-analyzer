#!/usr/bin/env python3
"""
deal_probabilistic.py — Monte Carlo on the revenue assumption (C9).

The deal lives or dies on revenue, and revenue is the softest input. A single point
estimate hides the risk. This samples revenue across a distribution (triangular: a
low / most-likely / high you set from the comp spread) and reports the probability of
positive cash flow plus the CoC range — so "looks marginal" becomes "negative ~70% of
the time" or "breakeven, tips positive if it beats the median comp."

Reuses fill_deal_analyzer.compute(). Revenue uncertainty dominates, so we vary gross
revenue (which already includes cleaning, per the model definition).

Usage:
    python3 scripts/deal_probabilistic.py --spec spec.json
    python3 scripts/deal_probabilistic.py --spec spec.json --low 105000 --mode 131000 --high 160000
    python3 scripts/deal_probabilistic.py --spec spec.json --n 20000

Defaults: mode = the spec's base gross; low/high = mode ±20% unless you pass comp-derived
numbers (recommended — use the AirROI P25 / median / P75, haircut as needed).
"""
import argparse, json, os, random, statistics, sys
sys.path.insert(0, os.path.dirname(__file__))
from fill_deal_analyzer import compute, CELLS, template_defaults


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--low", type=float, help="pessimistic annual gross (default mode*0.80)")
    ap.add_argument("--mode", type=float, help="most-likely annual gross (default = spec base)")
    ap.add_argument("--high", type=float, help="optimistic annual gross (default mode*1.20)")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    random.seed(args.seed)

    spec = json.load(open(args.spec))
    # overlay the spec on the TEMPLATE defaults (same base the fill path uses) — not some
    # other property's full spec, which would leak its HOA/tax/etc. into this deal.
    base = {**template_defaults(), **{k: v for k, v in spec.items() if k in CELLS}}
    base_m = compute(base)
    mode = args.mode or base_m["gross"]
    low = args.low or mode * 0.80
    high = args.high or mode * 1.20

    cocs, cfs, dscrs = [], [], []
    for _ in range(args.n):
        g = random.triangular(low, high, mode)
        m = compute({**base, "gross_override": g})
        cocs.append(m["coc"]); cfs.append(m["cf"]); dscrs.append(m["dscr"])

    p_pos = sum(1 for c in cfs if c > 0) / args.n
    p_dscr1 = sum(1 for d in dscrs if d >= 1.0) / args.n

    def money(x): return f"${x:,.0f}"
    print(f"Monte Carlo — {spec.get('address','deal')}  ({args.n:,} draws)")
    print(f"Revenue modeled (triangular):  low {money(low)}  |  mode {money(mode)}  |  high {money(high)}\n")
    print(f"  P(cash flow > 0):     {p_pos:5.0%}")
    print(f"  P(DSCR >= 1.0):       {p_dscr1:5.0%}")
    print(f"\n  Cash-on-cash:   P10 {pct(cocs,.1):6.1%}   median {pct(cocs,.5):6.1%}   P90 {pct(cocs,.9):6.1%}")
    print(f"  Monthly CF:     P10 {money(pct(cfs,.1)/12):>9}   median {money(pct(cfs,.5)/12):>9}   P90 {money(pct(cfs,.9)/12):>9}")
    print(f"  DSCR:           P10 {pct(dscrs,.1):.2f}      median {pct(dscrs,.5):.2f}      P90 {pct(dscrs,.9):.2f}")
    verdict = ("mostly negative" if p_pos < 0.35 else
               "a coin-flip" if p_pos < 0.65 else "mostly positive")
    print(f"\n  Read: cash flow is {verdict} across the revenue range ({p_pos:.0%} positive).")


if __name__ == "__main__":
    main()
