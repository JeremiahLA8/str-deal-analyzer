# Changelog

## 2026-06-20 — accuracy pass (this package)

The underwriting engine got materially more accurate. What changed:

### Revenue accuracy
- **AirROI ADR calibration** (`airroi_lookup.py`). AirROI's `ttm_avg_rate` (and thus its
  revenue) runs high versus realized host revenue, and the error is concentrated in **ADR, not
  occupancy** — and is worse on luxury listings (measured ~2x high near $900 ADR vs realized).
  The script now applies a clamped, ADR-level-keyed correction to each comp's ADR + revenue
  before weighting. Per-comp `keep` factor is shown in the output; disable with `--no-adr-cal`.
- **Consistent amenity premium** (`deal_scenarios.py`). The build-out grid used to compound a
  separate ADR lift and occupancy lift (e.g. pool = +18% ADR + 3pt occ), which **double-counted**
  and turned a realistic ~13% pool+hot-tub lift into +44%. It now uses **one revenue premium per
  amenity** (`rev_lift`), conservative by default and **overridable per-deal** via the spec's
  `amenity_lifts = {"hot_tub": 0.04, "pool_fiber": 0.09, ...}`. Prefer deriving the with-amenity
  revenue straight from amenity-matched comps; keep the strip premium and the add premium equal.

### Deliverable quality
- **"Pono Notes" reasoning sheet** (`fill_deal_analyzer.py`). Every workbook now ends with a sheet
  recording the analyst's reasoning per input — why this revenue base, why this rehab tier, what's
  sourced vs. assumed, the gates/caveats. Driven by the spec's `reasoning` list; falls back to
  `source_note` + `notes` if absent.
- **Live-tab recalc** (`fill_deal_analyzer.py`). openpyxl writes formulas but no cached values, so
  the live tabs read $0.00 in viewers that don't recalc. The script now drives a real recalc (Excel
  on macOS) so every formula cell carries its value and displays in any viewer; the Summary snapshot
  + `fullCalcOnLoad` remain as fallbacks on other platforms.

### Method
- **Top-quintile (P80) base.** Underwrite revenue at the top-fifth of comps (a top-20% operation),
  not the median — applied AFTER the ADR calibration and amenity normalization.
- **Source local service + tax inputs.** Don't default `spa_mo` / `landscaping_mo` / `property_tax`
  / `insurance` — research the market's weekly pool + landscaping rates, the non-homestead tax tier,
  and an STR insurance quote; record each with its source in the `reasoning` log.
- **Full-address workbook titles**, e.g. "3129 New Haven St, Irving, TX 75062 - STR COC Analysis.xlsx".
