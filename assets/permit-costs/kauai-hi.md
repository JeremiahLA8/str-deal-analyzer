# Permit costs — Kauai County, HI

Researched 2026-06-19 for the `/analyze-deal` permitting layer. Machine-readable
version lives in `scripts/permit_costs.py` (MARKETS["kauai-hi"]). Refresh annually —
county fee schedules change.

Sources:
- [County of Kauai — Transient Vacation Rentals](https://www.kauai.gov/Government/Departments-Agencies/Planning/Transient-Vacation-Rentals)
- County of Kauai **Appendix A — Fees, Rates, Assessments & Taxes** (kauai.granicus.com)
- County of Kauai **Building Division Permit Brief** (Kauai-DPW-1)
- [Kauai TAT/GET explainer (Ambrose Kauai)](https://ambrosekauai.com/blog/tat-get-and-county-tat-for-north-shore-rentals)

## 1. STR operating permit (the right to operate)

- TVRs are allowed **only inside a Visitor Destination Area (VDA)**, or with a
  pre-2009 grandfathered **Non-Conforming Use (NCU)** certificate. Outside a VDA with
  no NCU, you cannot legally short-term rent. **Confirm VDA status first** — it's the
  go/no-go gate, not a cost line.
- **Princeville is a VDA**, so a Princeville unit registers as a permitted TVR (no NCU).
- **NCU renewal (non-VDA grandfathered units only): $500/yr.** Renewal must be filed
  >= 60 days before expiry. Does not apply to VDA units.
- **Hawaii GET license: ~$20 one-time** (Dept. of Taxation, to get a Hawaii Tax ID).
- Exact VDA TVR registration fee is not published in Appendix A — **confirm with the
  Planning Dept (808-241-4050)** for a specific property. Budget a nominal one-time
  registration in the deal's setup permit line.

## 2. Pass-through taxes (collected from the guest, not an owner cost)

GET 4.5% + State TAT 11% (2026, Act 96) + Kauai County TAT 3% = **~18.5% on rents.**
These are remitted, not absorbed, so they don't hit the owner's cash flow directly —
but they raise the guest's all-in price, which can pressure occupancy.

## 2b. Annual real property tax — USE THE VACATION-RENTAL TIER

An STR is taxed in the **Vacation Rental** class, not owner-occupied. FY2025-26 rates per
$1,000 assessed (tiered/progressive):

| Class | Rate per $1,000 |
|---|---|
| Owner-occupied | $2.59 |
| **Vacation Rental** — Tier 1 (≤ $1M) | **$11.30** |
| Vacation Rental — Tier 2 ($1M–$2.5M) | $11.75 |
| Vacation Rental — Tier 3 (> $2.5M) | $12.20 |
| Non-owner residential — Tier 1 (≤ $1.3M) | $5.45 |

The vacation-rental rate is **~4.4x** owner-occupied. A common mistake is underwriting off
the seller's current (owner-occupied) tax bill — that understates the STR tax badly. The
model computes `property_tax_estimate(market, assessed, "vacation_rental")` and warns if a
spec's `property_tax` looks like the wrong tier. Use assessed value; purchase price is a
conservative proxy until reassessment. Example: #8C at $970k → **$10,961/yr** (Tier 1).

## 3. Building permit (for reno / amenity builds)

Fee = a base fee on **construction valuation**, + **15% Building Revolving Fund**,
+ **15% plan review**. Base brackets (Appendix A):

| Construction value | Base permit fee |
|---|---|
| $1 – $500 | $15 |
| $501 – $2,000 | $17 – $45 |
| $2,001 – $25,000 | $53 – $229 |
| $25,001 – $50,000 | $236 – $404 |
| $50,001 – $100,000 | $410 – $704 |
| $100,001 – $1,000,000 | $704 + $5 / $1,000 over $100k |
| $1,000,001+ | $5,204 + $4 / $1,000 over $1M |

Computed examples (base + 15% + 15%, via `permit_costs.py`):

| Build | Total permit |
|---|---|
| Hot tub ~$14k | ~$188 |
| Hot tub ~$22k | ~$268 |
| Plunge pool ~$35k | ~$394 |
| Fiberglass pool ~$65k | ~$648 |
| Gunite pool ~$85k | ~$801 |

Takeaway: building permits for amenity-scale work are **a few hundred dollars**, far
below the flat $700 the template used to assume for a hot tub. Electrical/plumbing
sub-permits add small amounts; a major reno scales up per the table. Zoning permit
(if triggered) is $30 / $60 / $200 / $800 by class.

## What still needs a phone call

- Exact VDA TVR registration fee for a specific Princeville unit.
- Whether the Puamana HOA permits a private lanai hot tub (HOA rule, not a county fee).
- Confirm the 2026 Appendix A figures if underwriting a large reno (the base tables are
  stable year to year, but verify before relying on a big number).
