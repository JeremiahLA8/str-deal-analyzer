#!/usr/bin/env python3
"""
listing_hasdata.py — pull a subject listing's data + PHOTOS + description via HasData (Zillow).

This is the practical fix for "listing sites 403 my photo fetch" WITHOUT needing MLS
authorization. The MLS RESO route (scripts/listing_api.py) is the gold standard but requires a
participant/subscriber relationship + signed data license + OAuth2 creds — a high bar. HasData
scrapes Zillow on our behalf and returns:
  - the property record: price, beds/baths, sqft, year, lot, HOA, tax, homeType, MLS#, the
    listing `description` (a text condition signal, like RESO PublicRemarks)
  - `photos`: direct zillowstatic CDN URLs that DON'T 403 (verified) — so the renovation tier
    can be scored against condition-rubric.md (Read the images, apply the rubric).

Flow: --address -> Zillow SEARCH endpoint resolves to the best-matching listing URL, then the
Zillow PROPERTY endpoint returns the full record. Pass --url directly to skip the search.

Mirrors listing_api.py's CLI so it's a drop-in for the photo+data role of /analyze-deal:

    python3 listing_hasdata.py --address "12309 Patron Dr, Austin, TX 78758" --photos-out /tmp/subj
    python3 listing_hasdata.py --url "https://www.zillow.com/homedetails/.../29439961_zpid/" --json
    python3 listing_hasdata.py --address "<addr>" --raw      # dump the matched property record

Setup once: sign up at https://hasdata.com, grab the API key, save it (gitignored by
scripts/*.json):

    scripts/hasdata_secret.json   ->   {"api_key": "YOUR_KEY"}

The script also reads HASDATA_API_KEY from the env as a fallback.
"""
import argparse, json, os, re, sys, urllib.request, urllib.parse, urllib.error

BASE = "https://api.hasdata.com"
SECRET = os.path.join(os.path.dirname(__file__), "hasdata_secret.json")

# Zillow homeType -> the template's property_type values (README: Home / Condo / Townhome)
HOMETYPE = {
    "SINGLE_FAMILY": "Home", "CONDO": "Condo", "TOWNHOUSE": "Townhome",
    "MULTI_FAMILY": "Multi-family", "MANUFACTURED": "Manufactured",
    "APARTMENT": "Condo", "LOT": "Land",
}


def load_key():
    key = os.environ.get("HASDATA_API_KEY")
    if not key and os.path.exists(SECRET):
        key = json.load(open(SECRET)).get("api_key")
    if not key:
        sys.exit("No HasData key. Save scripts/hasdata_secret.json = {\"api_key\": \"...\"} "
                 "or set HASDATA_API_KEY. See the header of this file.")
    return key


def call(key, path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-api-key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"HasData {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")


# ---- field parsing helpers (Zillow nests the same fact in several places) ----

def _num(v):
    """'1,777 sqft' / '$253' / 1777 -> 1777 (int) or None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
    if not m:
        return None
    try:
        f = float(m.group(0).replace(",", ""))
        return int(f) if f == int(f) else f
    except ValueError:
        return None


def _glance(reso, label):
    """Value from resoData.atAGlanceFacts whose factLabel contains `label`."""
    for f in (reso.get("atAGlanceFacts") or []):
        if label.lower() in str(f.get("factLabel", "")).lower():
            return f.get("factValue")
    return None


def _beds(p, reso):
    for v in (p.get("beds"), p.get("bedrooms"), reso.get("bedrooms"),
              _num(_glance(reso, "bedroom"))):
        if v not in (None, 0):
            return _num(v)
    # duplex/multi-family: beds may only be in the prose ("each with 2 bedrooms")
    m = re.search(r"(\d+)\s*bed", p.get("description", "") or "", re.I)
    return int(m.group(1)) if m else None


def _baths(p, reso):
    for v in (reso.get("bathroomsFloat"), reso.get("bathrooms"), p.get("baths"),
              _num(_glance(reso, "bathroom"))):
        if v not in (None, 0):
            return _num(v)
    m = re.search(r"(\d+)\s*bath", p.get("description", "") or "", re.I)
    return int(m.group(1)) if m else None


def _hoa_annual(reso):
    """HOA -> annual $. Zillow shows '$250 monthly' / '$250/mo' in atAGlanceFacts or resoData."""
    raw = _glance(reso, "hoa") or reso.get("associationFee") or reso.get("hoaFee")
    n = _num(raw)
    if n is None:
        return None
    # monthly unless the text says annual/year
    txt = str(raw).lower()
    if "year" in txt or "ann" in txt:
        return round(n)
    return round(n * 12)


def spec_fragment(p):
    """Map the HasData/Zillow property record to deal-spec keys fill_deal_analyzer uses."""
    reso = p.get("resoData") or {}
    area = p.get("area") or {}
    addr = p.get("address") or {}
    tax_hist = p.get("taxHistory") or []
    addr_str = ", ".join(x for x in [addr.get("street"), addr.get("city"),
                                     addr.get("state"), addr.get("zipcode")] if x) or addr.get("addressRaw")
    tax = reso.get("taxAnnualAmount")
    if tax is None and tax_hist:
        tax = tax_hist[0].get("taxPaid")
    frag = {
        "address": addr_str,
        "listing_link": p.get("url"),
        "property_type": HOMETYPE.get(str(p.get("homeType", "")).upper(), p.get("homeType")),
        "beds": _beds(p, reso),
        "baths": _baths(p, reso),
        "sqft": area.get("livingArea") or _num(reso.get("livingArea")),
        "year_built": p.get("yearBuilt") or reso.get("yearBuilt"),
        "lot_size": area.get("lotSize") or _num(reso.get("lotSize")),
        "purchase_price": p.get("price"),
        "property_tax": _num(tax),
        "hoa_annual": _hoa_annual(reso),
    }
    return {k: v for k, v in frag.items() if v not in (None, "")}


def search(key, address):
    """Resolve an address to a Zillow listing. Returns (url, record_or_None).

    A full street-address keyword makes Zillow redirect to the detail page, so HasData returns
    a single full-fidelity `property` (we reuse it and skip the property call — saves a credit).
    A looser keyword returns a `properties` list; we score it and return just the best URL.
    """
    data = call(key, "/scrape/zillow/listing", {"keyword": address, "type": "forSale"})
    if data.get("property"):
        rec = data["property"]
        return rec.get("url"), rec
    props = data.get("properties") or []
    if not props:
        return None, None
    want = re.sub(r"[^a-z0-9]", "", address.lower())
    zip_m = re.search(r"\b(\d{5})\b", address)
    want_zip = zip_m.group(1) if zip_m else None

    def score(pr):
        raw = re.sub(r"[^a-z0-9]", "", str(pr.get("addressRaw", "")).lower())
        s = 0
        # leading street number + name overlap
        num = re.match(r"\d+", want)
        if num and raw.startswith(num.group(0)):
            s += 5
        if want_zip and want_zip in str(pr.get("addressRaw", "")):
            s += 3
        # crude token overlap
        s += sum(1 for tok in re.findall(r"[a-z]+", address.lower())[:4] if tok in raw)
        return s

    props.sort(key=score, reverse=True)
    return props[0].get("url"), None


def download(urls, out, cap=12):
    os.makedirs(out, exist_ok=True)
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) str-deal-analyzer"
    saved = []
    for i, u in enumerate(urls[:cap], 1):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=30) as r:
                ctype = r.headers.get("Content-Type", "").split(";")[0].lower()
                ext = {"image/png": ".png", "image/webp": ".webp"}.get(ctype, ".jpg")
                data = r.read()
            path = os.path.join(out, f"{i:02d}{ext}")
            open(path, "wb").write(data)
            saved.append(path)
            print(f"  [{i:>2}] {os.path.basename(path)}  ({len(data)//1024} KB)")
        except Exception as e:
            print(f"  [{i:>2}] {type(e).__name__} — {str(u)[:70]}")
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--url", help="Zillow listing URL (skips the address search)")
    ap.add_argument("--photos-out", default=None, help="download photos to this folder")
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--json", action="store_true", help="print a deal-spec fragment + description")
    ap.add_argument("--raw", action="store_true", help="dump the matched property record")
    args = ap.parse_args()
    if not args.address and not args.url:
        sys.exit("Pass --address or --url.")
    key = load_key()

    url, p = args.url, None
    if not url:
        url, p = search(key, args.address)
        if not url:
            print("No matching listing found on Zillow. Try --url with the listing link.")
            return
        print(f"Matched: {url}")

    if p is None:  # came in via --url, or a list hit — fetch the full property record
        data = call(key, "/scrape/zillow/property", {"url": url})
        p = data.get("property") or data
    if args.raw:
        print(json.dumps(p, indent=2)[:6000])
        return

    desc = p.get("description") or ""
    frag = spec_fragment(p)
    urls = p.get("photos") or []

    if args.json:
        print(json.dumps({**frag, "mls": p.get("mlsId"),
                          "status": p.get("status") or p.get("trueStatus"),
                          "remarks": desc, "n_photos": len(urls)}, indent=2))
    else:
        price = frag.get("purchase_price")
        print(f"Listing: {frag.get('address')}  (MLS {p.get('mlsId')}, "
              f"{p.get('status') or p.get('trueStatus')})")
        print(f"  {frag.get('beds')}bd/{frag.get('baths')}ba  {frag.get('sqft')} sqft  "
              f"built {frag.get('year_built')}  {frag.get('property_type')}"
              + (f"  list ${price:,}" if price else ""))
        if frag.get("hoa_annual"):
            print(f"  HOA: ${frag['hoa_annual']:,}/yr   tax: ${frag.get('property_tax', 0):,}/yr")
        print(f"  photos available: {len(urls)}")
        print(f"\n  DESCRIPTION (condition signal):\n  {desc[:600]}")

    if args.photos_out and urls:
        print(f"\nDownloading {min(len(urls), args.max)} photos -> {args.photos_out}")
        saved = download(urls, args.photos_out, args.max)
        print(f"\n{len(saved)} photos saved. Next: Read them, score against "
              f"condition-rubric.md, then renovation_budget.py --sqft {frag.get('sqft','<N>')} --tier <result>.")


if __name__ == "__main__":
    main()
