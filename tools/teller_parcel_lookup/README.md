# Teller County (CO) Parcel Ownership Lookup

`teller_parcel_lookup.py` pulls the ownership record for a single Teller
County, Colorado parcel from the county ArcGIS REST endpoint and returns
structured JSON plus the raw response for verification.

## Usage

```bash
python3 teller_parcel_lookup.py "29 Nez Perce St, Woodland Park, CO 80863" \
    --expect-assessed 12561 --raw
```

Only the Python standard library is required. If `requests` is installed it
is used; otherwise it falls back to `urllib`.

### Options
- `--expect-assessed 12561` — confirm the match against a known 2024 assessed
  value before trusting the result (strongly recommended).
- `--mapserver <url>` — override the ArcGIS base URL.
- `--layer <id>` — force a layer id instead of auto-discovering the parcel layer.
- `--situs-field <NAME>` — force the address field if the heuristic misses.
- `--raw` — include the full raw ArcGIS responses in the output.

## Output shape

```json
{
  "query": {...},
  "source": "Teller County ArcGIS Property/MapServer (layer N)",
  "match_verified": true,
  "verification_note": "assessed value 12561 matches expected 12561",
  "record": {
    "owner_name": "...",
    "mailing_address": "...",
    "schedule_number": "R00xxxxxx",
    "situs_address": "29 NEZ PERCE ST",
    "last_sale_date": "...",
    "last_sale_price": ...,
    "zoning": "...",
    "lot_size_acres": ...,
    "lot_size_sqft": ...,
    "lot_size_sqft_derived_from_acres": ...,
    "legal_description": "...",
    "assessed_value": ...,
    "actual_value": ...,
    "tax_year": ...
  },
  "jurisdiction_note": "...",
  "raw": { "layer_fields": [...], "field_map": {...}, "query_where": "...", ... },
  "errors": []
}
```

## Data sources (priority order)
1. **Teller County GIS** — Esri/ArcGIS REST:
   `https://tcweb.tellercounty.gov/arcgis/rest/services/Property/MapServer`
   Queried directly by address; the JSON carries owner + schedule number.
2. **Assessor property-records / EagleWeb** (Tyler "Eagle"), fallback if GIS
   omits ownership:
   `https://tcweb.tellercounty.gov/proprecs/SearchAddress.aspx`
3. **Clerk & Recorder** — recorded deeds for exact sale date/price and vesting.

**Not used:** `payments.municipay.com` (tax *payment* portal, not a records source).

## How the match is verified
ArcGIS field names vary by county and change over time, so the script does not
hard-code them. It reads the MapServer + layer metadata, maps logical fields
(owner, schedule, mailing, sale, zoning, lot size, legal, assessed/actual
value) onto the real field names with name heuristics, queries by address, and
then **confirms the parcel using `--expect-assessed`** before trusting it. It
also derives lot sqft from acreage so the "~8,276 sqft" fact can be
cross-checked (0.19 ac == 8,276 sqft).

## City limits vs. unincorporated (buildability)
The parcel layer may carry a city/tax-district attribute, but an authoritative
in/out-of-Woodland-Park answer needs the municipal **city-limits polygon**
(GIS `Municipalities`/`CityLimits` layer) overlaid on the parcel geometry.
`jurisdiction_note` flags this; confirm before drawing septic-vs-sewer /
buildability conclusions.

## Note on running this in a sandboxed/egress-restricted environment
If outbound HTTPS to `tcweb.tellercounty.gov` is blocked by a network policy
(e.g. a CI or agent sandbox), the ArcGIS call returns HTTP 403 at the proxy and
the script reports it in `errors` rather than crashing. Run it from a network
that can reach the county host. The Assessor can also be reached at
719-689-2941.
