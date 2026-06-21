#!/usr/bin/env python3
"""
airroi_lookup.py — pull + weight real STR comps from AirROI for deal underwriting.

Give an address + bed/bath/guest count; it pulls nearby comparable Airbnb/VRBO listings
(AirROI `/listings/comparables`), filters to a genuinely-active cohort, then SIMILARITY-
WEIGHTS them so the revenue estimate reflects comps that are actually like the subject —
close by, similar bath count, same amenity tier (pool / hot tub), and well-reviewed (so the
occupancy is a real annual rate, not a new-listing artifact). A far, pool-equipped, barely-
reviewed comp counts much less than a close, same-amenity, established one.

Why weighting beats a flat median: AirROI returns the ~25 *nearest relevant* listings with
no fixed radius, so it blends sub-markets (e.g. Hanalei comps into a Princeville pull) and
mixes amenity tiers. Weighting (plus an optional --radius hard cap) corrects for that.

Three accuracy features (all from the AirROI comp set, no outside data):
  1. MEASURED amenity premiums — the pool / hot-tub revenue premium is read from the comps
     returned (with-amenity vs without), shrunk toward a prior by sample size, and only used
     when there are enough comps in each group. Falls back to the prior (and says so) when a
     group is too thin. Replaces the old fixed 18% / 10% guesses.
  2. REVENUE RANGE — reports a weighted P25 / median / P75 band of amenity-adjusted revenue,
     not just one point. Feeds deal_probabilistic.py's --low / --mode / --high.
  3. SHARPENED selection — bath proximity filter + weight, plus automatic trims of distance
     and revenue outliers (with guards so a small cohort is never gutted).

Key fields used (reliable): ttm_revenue (incl. cleaning), ttm_avg_rate, ttm_days_reserved
(booked nights → calendar occupancy = booked/365), num_reviews. `ttm_available_days` is
NOT used (it doesn't reconcile). Comp coords are approximate (Airbnb obfuscates), fine at
the mile scale used here.

Setup: the key lives in config.py (AIRROI_API_KEY), or AIRROI_API_KEY env, or airroi_secret.json.

Usage:
    python3 airroi_lookup.py --address "<addr>" --beds 4 --baths 2 --guests 8
    python3 airroi_lookup.py --address "<addr>" --beds 4 --baths 2 --radius 2   # hard cap 2 mi
    python3 airroi_lookup.py --address "<addr>" --beds 4 --baths 2 --has-pool --has-hot-tub
    python3 airroi_lookup.py --address "<addr>" --beds 4 --baths 2 --json       # spec fragment
    python3 airroi_lookup.py --address "<addr>" --beds 4 --baths 2 --raw        # full API dump
    python3 airroi_lookup.py --selftest <raw.json> --beds 3 --baths 2           # offline test on a cached --raw dump
"""
import argparse, json, math, os, statistics, sys, urllib.request, urllib.parse, urllib.error

BASE = "https://api.airroi.com"
SECRET = os.path.join(os.path.dirname(__file__), "airroi_secret.json")
TIMESHARE = ("wyndham", "bali hai villas", "club ", "marriott", "timeshare")
DIST_SCALE = 1.0          # miles; comp at this distance gets ~half the distance-weight
BATH_SCALE = 1.0          # baths; comp this many baths off the subject gets ~half the bath-weight
# Priors for amenity revenue premiums. Used directly when the comp set can't measure a
# premium, and as the shrinkage target when it can. Tunable as comp data accrues.
PRIOR_PREMIUM = {"pool": 0.18, "spa": 0.10}
SHRINK_K = 3.0            # pseudo-count: measured premium is blended with the prior as
                          #   (n_eff*measured + K*prior) / (n_eff + K). Higher K = trust prior more.
MIN_GROUP = 2            # need at least this many comps WITH and WITHOUT an amenity to measure it
PREM_CLAMP = (0.0, 0.60)  # a measured premium is clamped into this range before use
MIN_COHORT_AFTER_TRIM = 4 # never let an outlier trim drop the cohort below this many comps
DIST_TRIM_MULT = 3.0      # drop comps farther than this * median distance
REV_TRIM_MAD = 3.5        # drop comps whose revenue is this many MADs from the median
# back-compat aliases (older callers/imports referenced these names)
POOL_PREMIUM = PRIOR_PREMIUM["pool"]
SPA_PREMIUM = PRIOR_PREMIUM["spa"]

# ── AirROI ADR calibration ───────────────────────────────────────────────────
# AirROI's ttm_avg_rate (and therefore ttm_revenue) runs HIGH vs. realized host
# revenue, and the error is PROPORTIONAL TO ADR: ~correct at normal nightly rates,
# up to ~2x too high on luxury listings. Occupancy does NOT need correcting — AirROI's
# booked-nights occupancy already ran <= AirDNA's. Measured 2026-06 against AirDNA
# actuals on 4 overlapping Irving comps:
#       AirROI ADR  $444  $551  $878  $932
#       keep        0.94  0.79  0.48  0.50
# Fit as a clamped linear keep-factor on ADR, applied to each comp's adr + revenue
# (revenue = adr x booked-nights, so the same factor corrects both). Refit as more
# paired AirROI/realized data accrues. Disable with --no-adr-cal.
ADR_CAL = dict(a=1.373, b=-0.000976, floor=0.45, cap=1.0)


def adr_keep(adr):
    """AirROI ADR-inflation correction: a multiplier in [floor, cap] keyed off ADR level.
    ~1.0 at normal rates, tapering toward the floor as ADR climbs into luxury territory."""
    if not adr or adr <= 0:
        return 1.0
    return max(ADR_CAL["floor"], min(ADR_CAL["cap"], ADR_CAL["a"] + ADR_CAL["b"] * adr))


def load_key():
    env = os.environ.get("AIRROI_API_KEY")
    if env:
        return env
    try:                       # package layout: key in config.py
        import config
        if getattr(config, "AIRROI_API_KEY", None):
            return config.AIRROI_API_KEY
    except Exception:
        pass
    if os.path.exists(SECRET):  # repo layout: gitignored secret file
        return json.load(open(SECRET)).get("api_key")
    sys.exit("No AirROI key. Set it in config.py (AIRROI_API_KEY), the AIRROI_API_KEY env "
             "var, or airroi_secret.json. Get one at https://www.airroi.com/api/getting-started")


def get(path, key, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("x-api-key", key)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"AirROI GET {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")


def geocode(addr):
    """Subject address -> (lat, lon). US Census first (no key, US-only), Nominatim fallback."""
    try:
        u = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" + urllib.parse.urlencode(
            {"address": addr, "benchmark": "Public_AR_Current", "format": "json"})
        with urllib.request.urlopen(u, timeout=30) as r:
            m = json.load(r)["result"]["addressMatches"]
            if m:
                return m[0]["coordinates"]["y"], m[0]["coordinates"]["x"]
    except Exception:
        pass
    try:
        u = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": addr, "format": "json", "limit": 1})
        req = urllib.request.Request(u, headers={"User-Agent": "str-deal-analyzer/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
            if d:
                return float(d[0]["lat"]), float(d[0]["lon"])
    except Exception:
        pass
    return None


def haversine(a, b, c, d):
    R = 3959.0
    p1, p2 = math.radians(a), math.radians(c)
    dphi, dl = math.radians(c - a), math.radians(d - b)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def has_pool(amenities):
    return any(("pool" in a.lower() and "table" not in a.lower()) for a in (amenities or []))


def has_spa(amenities):
    return any(any(t in a.lower() for t in ("hot tub", "jacuzzi", "whirlpool")) for a in (amenities or []))


def quantile(vals, p):
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    if not v:
        return None
    return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]


def weighted_quantile(pairs, p):
    """Weighted quantile. pairs = list of (value, weight). p in [0,1]. Linear on cumulative weight."""
    pts = sorted((float(v), float(w)) for v, w in pairs if w and w > 0)
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0][0]
    total = sum(w for _, w in pts)
    target = p * total
    cum = 0.0
    for i, (v, w) in enumerate(pts):
        # cumulative weight at the *center* of this point's mass
        c0 = cum
        cum += w
        if cum >= target:
            # interpolate between previous point and this one on cumulative weight
            if i == 0:
                return v
            vprev, _ = pts[i - 1]
            span = w  # weight bridging the two points (approx)
            frac = (target - c0) / span if span else 0.0
            frac = max(0.0, min(1.0, frac))
            return vprev + (v - vprev) * frac
    return pts[-1][0]


def build_comps(resp, origin, adr_cal=True):
    """Raw API response + subject (lat,lon)|None -> normalized comp dicts.
    When adr_cal, each comp's ADR + revenue are corrected for AirROI's ADR inflation
    (see ADR_CAL / adr_keep); raw values are retained as raw_adr / raw_rev."""
    listings = resp.get("listings", []) if isinstance(resp, dict) else (resp or [])
    comps = []
    for c in listings:
        li, pd = c.get("listing_info", {}), c.get("property_details", {})
        pm, rt, loc = c.get("performance_metrics", {}), c.get("ratings", {}), c.get("location_info", {})
        name = (li.get("listing_name") or "").replace("\n", " ").strip()
        booked = pm.get("ttm_days_reserved") or 0
        lat, lon = loc.get("latitude"), loc.get("longitude")
        dist = haversine(origin[0], origin[1], lat, lon) if (origin and lat and lon) else None
        raw_adr = pm.get("ttm_avg_rate") or 0
        raw_rev = pm.get("ttm_revenue") or 0
        keep = adr_keep(raw_adr) if adr_cal else 1.0
        comps.append(dict(
            name=name[:34], beds=pd.get("bedrooms"), baths=pd.get("baths"),
            adr=raw_adr * keep, adjocc=pm.get("ttm_adjusted_occupancy") or 0,
            cal_occ=(booked / 365) if booked else 0, rev=raw_rev * keep,
            raw_adr=raw_adr, raw_rev=raw_rev, adr_keep=keep,
            reviews=rt.get("num_reviews") or 0, locality=loc.get("locality") or "?",
            room_type=(li.get("room_type") or "").lower(), dist=dist,
            pool=has_pool(pd.get("amenities")), spa=has_spa(pd.get("amenities")),
            ts=any(t in name.lower() for t in TIMESHARE)))
    return comps


def select_cohort(comps, beds, baths, min_reviews, min_occ, radius, bath_tol):
    """Filter to the active, comparable cohort, then trim distance/revenue outliers.
    Returns (active, trim_notes)."""
    def is_entire(c):
        return c["room_type"] in ("", "entire_home", "entire_place", "entire home")

    active = [c for c in comps if c["beds"] == int(beds) and is_entire(c)
              and c["reviews"] >= min_reviews and c["adjocc"] >= min_occ and not c["ts"]]
    # bath proximity: drop comps more than bath_tol baths off the subject (when baths known)
    if bath_tol is not None:
        active = [c for c in active if c["baths"] is None or abs((c["baths"] or 0) - baths) <= bath_tol]
    if radius is not None:
        active = [c for c in active if c["dist"] is not None and c["dist"] <= radius]

    notes = []
    # distance-outlier trim (only when geocoded and cohort is big enough to spare some)
    dists = [c["dist"] for c in active if c["dist"] is not None]
    if len(dists) >= MIN_COHORT_AFTER_TRIM + 1:
        med_d = statistics.median(dists)
        cap = DIST_TRIM_MULT * med_d
        keep = [c for c in active if c["dist"] is None or c["dist"] <= cap]
        if MIN_COHORT_AFTER_TRIM <= len(keep) < len(active):
            dropped = [c for c in active if c not in keep]
            notes.append(f"dropped {len(dropped)} distance outlier(s) > {cap:.1f} mi "
                         f"(>{DIST_TRIM_MULT:g}x median {med_d:.1f} mi)")
            active = keep
    # revenue-outlier trim via MAD (robust); guard the floor
    revs = [c["rev"] for c in active if c["rev"]]
    if len(revs) >= MIN_COHORT_AFTER_TRIM + 1:
        med_r = statistics.median(revs)
        mad = statistics.median([abs(r - med_r) for r in revs]) or 0
        if mad > 0:
            lo, hi = med_r - REV_TRIM_MAD * 1.4826 * mad, med_r + REV_TRIM_MAD * 1.4826 * mad
            keep = [c for c in active if lo <= c["rev"] <= hi]
            if MIN_COHORT_AFTER_TRIM <= len(keep) < len(active):
                dropped = [c for c in active if c not in keep]
                notes.append(f"dropped {len(dropped)} revenue outlier(s) outside "
                             f"${lo:,.0f}–${hi:,.0f} (robust band)")
                active = keep
    return active, notes


def measure_premium(active, amenity, prior):
    """Measure an amenity's revenue premium from the cohort (median-with / median-without),
    shrink it toward the prior by sample size, clamp, and return (premium, source_str).
    Falls back to the prior when either group is too thin."""
    has = [c["rev"] for c in active if c[amenity] and c["rev"]]
    lacks = [c["rev"] for c in active if not c[amenity] and c["rev"]]
    if len(has) < MIN_GROUP or len(lacks) < MIN_GROUP:
        return prior, f"default {prior:+.0%} (only {len(has)} with / {len(lacks)} without — too thin to measure)"
    mh, ml = statistics.median(has), statistics.median(lacks)
    if ml <= 0:
        return prior, f"default {prior:+.0%} (no usable baseline)"
    raw = mh / ml - 1.0
    raw = max(PREM_CLAMP[0], min(PREM_CLAMP[1], raw))
    n_eff = min(len(has), len(lacks))
    prem = (n_eff * raw + SHRINK_K * prior) / (n_eff + SHRINK_K)
    return prem, (f"measured {prem:+.0%} (raw {raw:+.0%} from {len(has)} with / {len(lacks)} "
                  f"without, shrunk toward {prior:+.0%})")


def amenity_factor(c, subj, prem):
    """Multiplier to normalize a comp's revenue to the SUBJECT's amenity tier.
    Discount a comp that has an amenity the subject lacks; credit the reverse.
    `prem` = {"pool": x, "spa": y} effective premiums."""
    f = 1.0
    if c["pool"] and not subj["pool"]:
        f /= (1 + prem["pool"])
    elif subj["pool"] and not c["pool"]:
        f *= (1 + prem["pool"])
    if c["spa"] and not subj["spa"]:
        f /= (1 + prem["spa"])
    elif subj["spa"] and not c["spa"]:
        f *= (1 + prem["spa"])
    return f


def comp_weight(c, subj_baths):
    """Similarity weight: distance x bath-proximity x tenure. (Amenity handled by hedonic adjustment.)"""
    w = 1.0
    if c["dist"] is not None:
        w *= 1.0 / (1.0 + (c["dist"] / DIST_SCALE) ** 2)           # closer = higher
    if c["baths"] is not None and subj_baths is not None:
        w *= 1.0 / (1.0 + (abs(c["baths"] - subj_baths) / BATH_SCALE) ** 2)  # bath match
    w *= max(0.3, min(1.0, c["reviews"] / 50.0))                   # tenure (reliability)
    return w


def analyze(active, subj, baths):
    """Compute weighted, amenity-adjusted revenue + range from the active cohort.
    Returns a result dict. Mutates each comp with w / adj_rev / adj_adr."""
    prem = {}
    prem_src = {}
    for a in ("pool", "spa"):
        prem[a], prem_src[a] = measure_premium(active, a, PRIOR_PREMIUM[a])
    for c in active:
        c["w"] = comp_weight(c, baths)
        c["adj_rev"] = c["rev"] * amenity_factor(c, subj, prem)
        c["adj_adr"] = c["adr"] * amenity_factor(c, subj, prem)
    W = sum(c["w"] for c in active) or 1.0
    w_rev = sum(c["w"] * c["adj_rev"] for c in active) / W
    w_adr = sum(c["w"] * c["adj_adr"] for c in active) / W
    w_occ = sum(c["w"] * c["cal_occ"] for c in active) / W
    rev_pairs = [(c["adj_rev"], c["w"]) for c in active]
    p25 = weighted_quantile(rev_pairs, 0.25)
    p50 = weighted_quantile(rev_pairs, 0.50)
    p75 = weighted_quantile(rev_pairs, 0.75)
    p80 = weighted_quantile(rev_pairs, 0.80)   # top-quintile: StayAscend's "top-fifth operator" base
    med_rev = statistics.median([c["rev"] for c in active])
    matched = [c for c in active if c["pool"] == subj["pool"] and c["spa"] == subj["spa"]]
    med_matched = statistics.median([c["rev"] for c in matched]) if matched else None
    return dict(w_rev=w_rev, w_adr=w_adr, w_occ=w_occ, p25=p25, p50=p50, p75=p75, p80=p80,
                med_rev=med_rev, med_matched=med_matched, n_matched=len(matched),
                prem=prem, prem_src=prem_src)


def run(resp, address, beds, baths, guests, subj, radius, min_reviews, min_occ, bath_tol, geocode_fn, adr_cal=True):
    """Pure-ish pipeline: response -> result. geocode_fn() returns origin or None."""
    origin = geocode_fn()
    comps = build_comps(resp, origin, adr_cal)
    active, trims = select_cohort(comps, beds, baths, min_reviews, min_occ, radius, bath_tol)
    if not active:
        return None, origin, [], trims
    res = analyze(active, subj, baths)
    return res, origin, active, trims


def build_note(res, active, guests):
    p = res["prem_src"]
    keeps = [c.get("adr_keep", 1.0) for c in active]
    cal = (f" ADR-calibrated for AirROI inflation (median keep {statistics.median(keeps):.2f})."
           if any(k < 0.999 for k in keeps) else "")
    return (f"AirROI {len(active)} active comps ({guests}-guest): bath/distance/tenure weighted, "
            f"revenue amenity-adjusted to subject tier.{cal} Weighted rev ${res['w_rev']:,.0f} incl. "
            f"cleaning, ADR ${res['w_adr']:,.0f}, cal-occ {res['w_occ']:.0%}. "
            f"Range P25–P75 ${res['p25']:,.0f}–${res['p75']:,.0f} (median ${res['p50']:,.0f}; "
            f"top-quintile P80 ${res['p80']:,.0f}). "
            f"Pool premium {p['pool']}; hot-tub premium {p['spa']}. Plain median ${res['med_rev']:,.0f}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--beds", type=float, required=True)
    ap.add_argument("--baths", type=float, required=True)
    ap.add_argument("--guests", type=int, default=None, help="default = beds*2")
    ap.add_argument("--radius", type=float, default=None, help="hard cap comps to N miles of subject")
    ap.add_argument("--bath-tol", type=float, default=1.0, help="drop comps more than N baths off subject (default 1)")
    ap.add_argument("--has-pool", action="store_true", help="subject has a (private) pool")
    ap.add_argument("--has-hot-tub", action="store_true", help="subject has a hot tub")
    ap.add_argument("--min-reviews", type=int, default=20)
    ap.add_argument("--min-occ", type=float, default=0.45, help="min adjusted occupancy")
    ap.add_argument("--no-adr-cal", dest="adr_cal", action="store_false", default=True,
                    help="disable the AirROI ADR-inflation correction (see ADR_CAL)")
    ap.add_argument("--json", action="store_true", help="print a deal-spec fragment")
    ap.add_argument("--raw", action="store_true", help="dump the full API response")
    ap.add_argument("--selftest", metavar="RAW_JSON", default=None,
                    help="run offline against a cached --raw dump (no API call, no geocode)")
    args = ap.parse_args()
    guests = args.guests or int(args.beds * 2)
    subj = {"pool": args.has_pool, "spa": args.has_hot_tub}

    # fetch (or load cached) response
    if args.selftest:
        resp = json.load(open(args.selftest))
        geocode_fn = lambda: None          # offline: skip network geocode
        address = args.address or "(selftest)"
    else:
        if not args.address:
            sys.exit("--address is required (or use --selftest <raw.json>)")
        address = args.address
        key = load_key()

        def num(x):
            return int(x) if float(x).is_integer() else x
        resp = get("/listings/comparables", key, {
            "address": address, "bedrooms": num(args.beds),
            "baths": num(args.baths), "guests": guests, "currency": "usd"})
        if args.raw:
            print(json.dumps(resp, indent=2))
            return
        geocode_fn = lambda: geocode(address)

    res, origin, active, trims = run(
        resp, address, args.beds, args.baths, guests, subj,
        args.radius, args.min_reviews, args.min_occ, args.bath_tol, geocode_fn, args.adr_cal)
    if res is None:
        print("No active comps matched. Loosen --min-reviews / --min-occ / --radius / --bath-tol.")
        return

    if args.json:
        matched_txt = (f"amenity-matched median ${res['med_matched']:,.0f}."
                       if res["med_matched"] is not None
                       else "no amenity-matched comps (subject tier rare here).")
        note = build_note(res, active, guests) + " " + matched_txt
        if trims:
            note += " Trims: " + "; ".join(trims) + "."
        print(json.dumps({
            "gross_override": round(res["w_rev"]), "adr": round(res["w_adr"]),
            "occupancy": round(res["w_occ"], 3), "turnovers_mo": 5,
            "rev_p25": round(res["p25"]), "rev_median": round(res["p50"]),
            "rev_p75": round(res["p75"]), "rev_p80": round(res["p80"]), "source_note": note,
        }, indent=2))
        return

    geo = (f"subject @ {origin[0]:.4f},{origin[1]:.4f}" if origin
           else "subject not geocoded (distance weighting off)")
    print(f"AirROI comps — {address}")
    print(f"  subject: {int(args.beds)}bd / {args.baths}ba / {guests} guests"
          f"{' / pool' if subj['pool'] else ''}{' / hot tub' if subj['spa'] else ''}   ({geo})")
    rtxt = f", within {args.radius} mi" if args.radius is not None else ""
    print(f"  {len(active)} active comps (>= {args.min_reviews} reviews, adj-occ >= {args.min_occ:.0%}"
          f", baths within {args.bath_tol}{rtxt})")
    for t in trims:
        print(f"  trim: {t}")
    if not args.adr_cal:
        print("  ADR calibration: OFF (--no-adr-cal) — using raw AirROI ADR/revenue")
    else:
        keeps = [c["adr_keep"] for c in active]
        low = [k for k in keeps if k < 0.999]
        if low:
            print(f"  ADR calibration: ON — corrected {len(low)}/{len(active)} comps for AirROI ADR "
                  f"inflation (median keep {statistics.median(keeps):.2f}, min {min(keeps):.2f})")
        else:
            print("  ADR calibration: ON — no comp ADR high enough to need correction")
    print(f"\n  amenity premiums (subject-tier normalization):")
    print(f"    pool   -> {res['prem_src']['pool']}")
    print(f"    hottub -> {res['prem_src']['spa']}")
    print(f"\n  {'name':32}{'mi':>5}{'occ':>5}{'cal rev':>9}{'keep':>6}{'amen':>5}{'adj rev':>9}{'rev#':>5}{'wt':>5}")
    for c in sorted(active, key=lambda d: -d["w"]):
        am = ("P" if c["pool"] else "-") + ("H" if c["spa"] else "-")
        dm = f"{c['dist']:.1f}" if c["dist"] is not None else "?"
        print(f"  {c['name']:32}{dm:>5}{c['cal_occ']:>5.0%}{c['rev']:>9,.0f}{c['adr_keep']:>6.2f}{am:>5}"
              f"{c['adj_rev']:>9,.0f}{c['reviews']:>5}{c['w']:>5.2f}")
    print(f"\n  WEIGHTED + AMENITY-ADJUSTED:  rev ${res['w_rev']:,.0f}  |  ADR ${res['w_adr']:,.0f}"
          f"  |  cal-occ {res['w_occ']:.0%}")
    print(f"  RANGE (weighted, amenity-adjusted):  P25 ${res['p25']:,.0f}  |  median ${res['p50']:,.0f}"
          f"  |  P75 ${res['p75']:,.0f}  |  top-quintile P80 ${res['p80']:,.0f}")
    print(f"  (raw revenue normalized to subject's amenity tier, then bath x distance x tenure weighted)")
    print(f"  reference: plain median ${res['med_rev']:,.0f}", end="")
    if res["med_matched"] is not None:
        print(f"  |  amenity-matched median ({res['n_matched']} comps) ${res['med_matched']:,.0f}")
    else:
        print(f"  |  no amenity-matched comps (subject's tier is rare here)")
    if origin:
        ds = sorted(c["dist"] for c in active if c["dist"] is not None)
        if ds:
            print(f"  comp distance: median {ds[len(ds)//2]:.1f} mi, max {ds[-1]:.1f} mi")
    from collections import Counter
    print(f"  localities: " + ", ".join(f"{k} ({n})" for k, n in Counter(c["locality"] for c in active).most_common()))
    print(f"\n  -> gross_override = weighted rev (haircut for condition); P25/P75 feed "
          f"deal_probabilistic --low/--high. --json for a spec fragment.")


if __name__ == "__main__":
    main()
