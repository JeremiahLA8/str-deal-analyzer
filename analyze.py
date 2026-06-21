#!/usr/bin/env python3
"""analyze.py — one-command STR cash-on-cash pipeline.

Give it a finished deal spec (JSON; see assets/example.spec.json and METHODOLOGY.md for the
key -> cell map) and it runs the whole chain:

  1. fill_deal_analyzer  -> writes the 5-tab workbook + a Summary snapshot + a "Pono Notes"
     reasoning sheet, recalculates the live tabs (real Excel if present), and prints the
     headline metrics (CoC, cap, DSCR, NOI, manager economics, checks).
  2. deal_scenarios      -> (with --scenarios) amenity build-out grid (hot tub / pool combos),
     using one comp-grounded revenue premium per amenity (override per-deal with the spec's
     `amenity_lifts`).
  3. deal_probabilistic  -> (with --low/--mode/--high) a revenue Monte Carlo: P(cash flow > 0)
     and the CoC P10/median/P90 band.

Usage:
    python3 analyze.py deal.spec.json
    python3 analyze.py deal.spec.json --out "/path/<Full Address> - STR COC Analysis.xlsx"
    python3 analyze.py deal.spec.json --scenarios
    python3 analyze.py deal.spec.json --low 79000 --mode 110000 --high 147000
"""
import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(module, *args):
    cmd = [sys.executable, os.path.join(HERE, module), *args]
    print(f"\n{'='*70}\n$ {module} {' '.join(args)}\n{'='*70}")
    return subprocess.run(cmd, check=False).returncode


def main():
    ap = argparse.ArgumentParser(description="One-command STR cash-on-cash pipeline.")
    ap.add_argument("spec", help="deal spec JSON (see assets/example.spec.json)")
    ap.add_argument("--out", default=None, help="workbook output path (default: ~/Downloads/<address> - STR COC Analysis.xlsx)")
    ap.add_argument("--scenarios", action="store_true", help="also run the amenity build-out grid")
    ap.add_argument("--low", type=float, default=None, help="P25 revenue for the Monte Carlo")
    ap.add_argument("--mode", type=float, default=None, help="base/P80 revenue for the Monte Carlo")
    ap.add_argument("--high", type=float, default=None, help="P75 revenue for the Monte Carlo")
    a = ap.parse_args()

    fill_args = [a.spec] + (["--out", a.out] if a.out else [])
    run("fill_deal_analyzer.py", *fill_args)
    if a.scenarios:
        run("deal_scenarios.py", "--spec", a.spec)
    if a.low is not None and a.mode is not None and a.high is not None:
        run("deal_probabilistic.py", "--spec", a.spec,
            "--low", str(a.low), "--mode", str(a.mode), "--high", str(a.high))
    print("\nDone. Open the workbook; the live tabs recalc on open and the Summary + Pono Notes "
          "sheets show values everywhere.")


if __name__ == "__main__":
    main()
