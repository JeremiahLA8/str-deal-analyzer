# Copy this file to `config.py` and fill in your keys. The engine reads it for API keys and
# the workbook template path. config.py is gitignored — never commit real keys.
#
# Both API keys are OPTIONAL: fill_deal_analyzer + deal_scenarios + deal_probabilistic run with
# no keys at all (they only need openpyxl). Keys are required only for the live data pulls:
#   - AIRROI_API_KEY   -> airroi_lookup.py   (comps / revenue)        https://www.airroi.com/api/getting-started
#   - HASDATA_API_KEY  -> listing_hasdata.py (subject data + photos)  https://hasdata.com
# Each key can also be supplied via the matching environment variable instead of this file.
import os

AIRROI_API_KEY = ""    # or set env AIRROI_API_KEY
HASDATA_API_KEY = ""   # or set env HASDATA_API_KEY

# Path to the blank workbook template shipped with this package. Leave as-is.
TEMPLATE = os.path.join(os.path.dirname(__file__), "assets", "template.xlsx")
