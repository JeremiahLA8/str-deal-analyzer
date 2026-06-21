# STR Deal Analyzer

A complete cash-on-cash underwriting model for short-term-rental acquisitions. Give it a property's facts and a comp-derived revenue figure; it fills a 5-tab Excel model and reports the returns — cash-on-cash, cap rate, DSCR, NOI, break-even, and manager economics — plus amenity build-out scenarios and a revenue Monte Carlo.

It's built for STR investors who want to underwrite a deal the way an operator actually does: revenue based on the **top quintile of comps** (not the median), ADR-calibrated against known market-data biases, with every soft assumption surfaced instead of hidden.

---

## About this repo

This is the underwriting engine extracted from Pono, the AI system that runs a live STR management company. The math, the live-data pullers, and the workbook model are all here. The example deal is a **real, public Redfin listing** (a Kauai condo) — public market data, no private client information.

I built this with no CS degree (pretty much Claude'd it all).

---

## What it computes

- **Returns** — cash-on-cash, cap rate, DSCR, NOI, pre-tax cash flow, break-even occupancy
- **Manager economics** — what a management company earns running the property (fee, 5-yr revenue, fee/gross)
- **Amenity build-out grid** — model adding a hot tub / pool and see the revenue lift vs. cost, using one comp-grounded premium per amenity (no ADR × occupancy double-count)
- **Revenue Monte Carlo** — P(cash flow > 0) and the CoC P10 / median / P90 band
- **Risk checks** — financing warrantability, lodging-tax pass-through, condition/rehab, and other deal-killers flagged inline

## How the revenue model works (the part that matters)

Revenue is the swing input in any STR deal, so it gets the most rigor:
- Comps are **ADR-calibrated** to correct for known inflation in market data (worse on luxury)
- Comp-weighted and normalized to the subject property
- Based on the **top-quintile (P80)** of comps — underwriting to a top-20% operation, not an average one

The engine prints what it **sourced** vs. what it **assumed**, so you confirm the soft inputs (revenue, condition, taxes, insurance) before you act on a number.

## Run it

```bash
pip install -r requirements.txt        # just openpyxl for the math

# underwrite the example deal (no API keys needed):
python3 analyze.py assets/example.spec.json

# add the amenity build-out grid + a revenue Monte Carlo:
python3 analyze.py assets/example.spec.json --scenarios --low 79000 --mode 110000 --high 147000

# end-to-end sanity check:
python3 tests/test_smoke.py
```

The workbook saves to `~/Downloads/<address> - STR COC Analysis.xlsx`. Its live tabs recalculate on open; a **Summary** snapshot and a reasoning sheet show the values in any viewer.

Live comp/listing pulls (optional) need API keys — copy `config.example.py` to `config.py` and add an [AirROI](https://www.airroi.com/api/getting-started) and/or [HasData](https://hasdata.com) key, or set them as environment variables.

## The spec

A flat JSON object — see [`assets/example.spec.json`](assets/example.spec.json). A few keys worth knowing:
- `reasoning` — a list of `{topic, detail}` notes → rendered as a reasoning sheet in the workbook
- `amenity_lifts` — per-amenity revenue premiums (e.g. `{"hot_tub": 0.04}`) → overrides the conservative defaults in the build-out grid with your comp-measured numbers

## What's in here

| File | Role |
|---|---|
| `analyze.py` | one-command pipeline: spec → workbook + full report |
| `fill_deal_analyzer.py` | writes + recalculates the workbook, prints the headline metrics |
| `airroi_lookup.py` | pull, calibrate, and weight real STR comps |
| `listing_hasdata.py` | pull the subject listing's data + photos |
| `deal_scenarios.py` | amenity build-out grid |
| `deal_probabilistic.py` | revenue Monte Carlo |
| `permit_costs.py` · `renovation_budget.py` | per-market permit/tax layer · rehab sizing |
| `assets/` | workbook template, condition rubric, example spec, permit data |
| `tests/test_smoke.py` | end-to-end test (no keys needed) |

---

Built by Jeremiah Lwin. Used in production to underwrite acquisitions for StayAscend / Ascend Vacation Rentals.
