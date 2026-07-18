#!/usr/bin/env python3
"""
Teller County, Colorado — single-parcel ownership lookup.

Pulls the ownership record for a Teller County parcel from the county's
ArcGIS REST endpoint and returns structured JSON, plus the raw response
so the result can be independently verified.

Primary data source (priority 1):
    Teller County GIS parcel viewer runs on Esri/ArcGIS. The underlying
    REST service is:
        https://tcweb.tellercounty.gov/arcgis/rest/services/Property/MapServer
    We query the parcel layer directly by address (an attribute WHERE
    clause). The JSON response carries owner name + schedule number.

Fallback data source (priority 2):
    Teller County Assessor "EagleWeb"/property-records address search
    (Tyler Technologies). ASP.NET page, scraped only if the GIS layer does
    not expose ownership:
        https://tcweb.tellercounty.gov/proprecs/SearchAddress.aspx

Deed history (last sale date/price, exact vesting) lives with the Clerk &
Recorder; the assessor GIS/records usually carry the most recent sale, which
is what this tool reports. For a full chain of title, pull the recorded deed.

NOT used: payments.municipay.com (that's the tax *payment* portal).

--------------------------------------------------------------------------
Design notes
--------------------------------------------------------------------------
Public ArcGIS field names differ from county to county and change over time,
so this script does NOT hard-code them. It:
  1. reads the MapServer metadata and picks the layer whose name looks like
     a parcel layer,
  2. reads that layer's field list,
  3. maps our logical fields (owner, schedule, mailing address, sale, zoning,
     lot size, legal, assessed/actual value) onto the real field names using
     name heuristics,
  4. queries by address, and
  5. VERIFIES the match against a known assessed value before trusting it.

Everything is overridable from the CLI if the heuristics miss.

Only the standard library is required (urllib). `requests` is used if present.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# ---- HTTP (requests if available, else stdlib urllib) ---------------------
try:
    import requests  # type: ignore

    def _get_json(url: str, params: Dict[str, Any], timeout: int) -> Any:
        r = requests.get(url, params=params, timeout=timeout,
                         headers={"User-Agent": _UA})
        r.raise_for_status()
        return r.json(), r.url

    def _get_text(url: str, params: Dict[str, Any], timeout: int) -> Tuple[str, str]:
        r = requests.get(url, params=params, timeout=timeout,
                         headers={"User-Agent": _UA})
        r.raise_for_status()
        return r.text, r.url
except Exception:  # pragma: no cover - fallback path
    import urllib.parse
    import urllib.request

    def _get_json(url: str, params: Dict[str, Any], timeout: int) -> Any:
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(full, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace")), full

    def _get_text(url: str, params: Dict[str, Any], timeout: int) -> Tuple[str, str]:
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(full, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace"), full


_UA = "teller-parcel-lookup/1.0 (public-records research; contact: user)"

DEFAULT_MAPSERVER = (
    "https://tcweb.tellercounty.gov/arcgis/rest/services/Property/MapServer"
)
EAGLEWEB_SEARCH = "https://tcweb.tellercounty.gov/proprecs/SearchAddress.aspx"


# ---- field-name heuristics ------------------------------------------------
# Each logical field maps to an ordered list of regexes tried against the
# ArcGIS layer's real field names (case-insensitive, matched on the name).
FIELD_PATTERNS: Dict[str, List[str]] = {
    "owner_name":        [r"^owner.?name$", r"^owner$", r"owner.?nam", r"^name$", r"grantee", r"taxpayer"],
    "mailing_address":   [r"mail.*addr", r"^mailing", r"tax.*addr", r"owner.*addr", r"m_addr", r"mailadd"],
    "mailing_city":      [r"mail.*city", r"m_city", r"owner.*city"],
    "mailing_state":     [r"mail.*state", r"m_state", r"owner.*state", r"^state$"],
    "mailing_zip":       [r"mail.*zip", r"m_zip", r"owner.*zip", r"^zip"],
    "schedule_number":   [r"sched", r"^schedno", r"account", r"^acct", r"parcel.?num", r"^parcelid$", r"^pin$", r"^apn$", r"^parcel$"],
    "situs_address":     [r"situs", r"site.?addr", r"phys.?addr", r"prop.?addr", r"^address$", r"^addr$", r"location", r"full.?addr"],
    "last_sale_date":    [r"sale.?date", r"sold.?date", r"deed.?date", r"rec.?date", r"transfer.?date"],
    "last_sale_price":   [r"sale.?price", r"sale.?amt", r"sale.?amount", r"^price$", r"consideration", r"sale_val"],
    "zoning":            [r"^zon", r"zoning", r"landuse", r"land.?use", r"^use$", r"use.?desc", r"use.?code", r"abstract"],
    "lot_size_acres":    [r"acre", r"gis.?acre", r"^acres?$", r"deed.?acre", r"calc.?acre"],
    "lot_size_sqft":     [r"sq.?ft", r"sqft", r"square.?fe", r"lot.?size", r"shape.?area"],
    "legal_description": [r"legal", r"^ldesc", r"land.?desc", r"subdiv", r"description"],
    "assessed_value":    [r"assess", r"assd", r"^av$", r"assessed"],
    "actual_value":      [r"actual", r"market", r"total.?val", r"^value$", r"appraised", r"act_val"],
    "tax_year":          [r"tax.?year", r"^year$", r"assess.?year", r"roll.?year"],
    "objectid":          [r"^objectid$", r"^oid$", r"^fid$"],
}


def _match_field(patterns: List[str], field_names: List[str]) -> Optional[str]:
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for name in field_names:
            if rx.search(name):
                return name
    return None


def build_field_map(field_names: List[str]) -> Dict[str, Optional[str]]:
    return {logical: _match_field(pats, field_names)
            for logical, pats in FIELD_PATTERNS.items()}


# ---- ArcGIS discovery -----------------------------------------------------
def discover_parcel_layer(mapserver: str, timeout: int,
                          layer_override: Optional[int]) -> Tuple[int, Dict[str, Any], Any]:
    """Return (layer_id, layer_metadata, raw_root_json)."""
    root, _ = _get_json(mapserver, {"f": "json"}, timeout)
    layers = root.get("layers", []) or []
    if layer_override is not None:
        lid = layer_override
    else:
        # Prefer a layer named like "parcel"/"ownership"; else first layer.
        lid = None
        for lay in layers:
            nm = str(lay.get("name", "")).lower()
            if "parcel" in nm or "ownership" in nm or "owner" in nm:
                lid = lay.get("id")
                break
        if lid is None and layers:
            lid = layers[0].get("id")
        if lid is None:
            raise RuntimeError(
                "No layers found on MapServer. Root keys: %s" % list(root.keys()))
    meta, _ = _get_json("%s/%d" % (mapserver, lid), {"f": "json"}, timeout)
    return lid, meta, root


def query_layer_by_address(mapserver: str, layer_id: int,
                           situs_field: str, address_tokens: List[str],
                           timeout: int) -> Any:
    """Query the layer with a LIKE clause built from address tokens.

    We split the input address into a house number + street-name tokens and
    AND together UPPER(field) LIKE '%TOKEN%' so slight formatting differences
    (St vs Street, casing) still match.
    """
    clauses = []
    for tok in address_tokens:
        tok_esc = tok.replace("'", "''").upper()
        clauses.append("UPPER(%s) LIKE '%%%s%%'" % (situs_field, tok_esc))
    where = " AND ".join(clauses) if clauses else "1=1"
    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    data, final_url = _get_json("%s/%d/query" % (mapserver, layer_id), params, timeout)
    return data, where, final_url


# ---- extraction + verification -------------------------------------------
def _first_attr(attrs: Dict[str, Any], field: Optional[str]) -> Any:
    if field and field in attrs:
        return attrs.get(field)
    return None


def extract_record(attrs: Dict[str, Any], fmap: Dict[str, Optional[str]]) -> Dict[str, Any]:
    mailing = _first_attr(attrs, fmap["mailing_address"])
    # Compose a full mailing address if the county splits it into parts.
    parts = [
        _first_attr(attrs, fmap["mailing_address"]),
        _first_attr(attrs, fmap["mailing_city"]),
        _first_attr(attrs, fmap["mailing_state"]),
        _first_attr(attrs, fmap["mailing_zip"]),
    ]
    parts = [str(p).strip() for p in parts if p not in (None, "")]
    composed_mailing = ", ".join(parts) if parts else mailing

    # Derive sqft from acres when the layer only carries acreage (lets us
    # cross-check the "~8,276 sqft" fact: 0.19 ac == 8,276 sqft).
    acres = _to_number(_first_attr(attrs, fmap["lot_size_acres"]))
    sqft = _first_attr(attrs, fmap["lot_size_sqft"])
    sqft_derived = round(acres * 43560) if (sqft in (None, "") and acres) else None

    return {
        "lot_size_sqft_derived_from_acres": sqft_derived,
        "owner_name":        _first_attr(attrs, fmap["owner_name"]),
        "mailing_address":   composed_mailing,
        "schedule_number":   _first_attr(attrs, fmap["schedule_number"]),
        "situs_address":     _first_attr(attrs, fmap["situs_address"]),
        "last_sale_date":    _first_attr(attrs, fmap["last_sale_date"]),
        "last_sale_price":   _first_attr(attrs, fmap["last_sale_price"]),
        "zoning":            _first_attr(attrs, fmap["zoning"]),
        "lot_size_acres":    _first_attr(attrs, fmap["lot_size_acres"]),
        "lot_size_sqft":     _first_attr(attrs, fmap["lot_size_sqft"]),
        "legal_description": _first_attr(attrs, fmap["legal_description"]),
        "assessed_value":    _first_attr(attrs, fmap["assessed_value"]),
        "actual_value":      _first_attr(attrs, fmap["actual_value"]),
        "tax_year":          _first_attr(attrs, fmap["tax_year"]),
    }


def _to_number(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(val)))
    except (ValueError, TypeError):
        return None


def verify_match(record: Dict[str, Any], expect_assessed: Optional[float],
                 tolerance: float = 1.0) -> Tuple[bool, str]:
    """Confirm we grabbed the right parcel using the known assessed value."""
    if expect_assessed is None:
        return True, "no assessed value supplied; match not value-verified"
    got = _to_number(record.get("assessed_value"))
    if got is None:
        return False, "layer exposed no assessed value to verify against"
    if abs(got - expect_assessed) <= tolerance:
        return True, "assessed value %s matches expected %s" % (got, expect_assessed)
    return False, "assessed value %s != expected %s" % (got, expect_assessed)


# ---- city-limits determination -------------------------------------------
def infer_jurisdiction(record: Dict[str, Any]) -> str:
    """Best-effort: many Teller layers carry a city/jurisdiction field.

    Without an authoritative city-limits polygon overlay this is a guess based
    on any city/tax-district attribute; the caller should confirm against the
    Woodland Park municipal boundary layer for buildability (septic vs sewer).
    """
    return ("UNKNOWN — confirm against Woodland Park city-limits polygon "
            "(GIS 'Municipalities'/'CityLimits' layer)")


# ---- orchestration --------------------------------------------------------
def lookup(address: str, mapserver: str, expect_assessed: Optional[float],
           timeout: int, layer_override: Optional[int],
           situs_field_override: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "query": {"address": address, "mapserver": mapserver,
                  "expected_assessed_value": expect_assessed},
        "source": None,
        "match_verified": False,
        "verification_note": None,
        "record": None,
        "jurisdiction_note": None,
        "raw": {},
        "errors": [],
    }

    # Tokenize address into house number + street name (drop unit/city/state).
    m = re.match(r"\s*(\d+)\s+(.*)", address)
    if m:
        house = m.group(1)
        street = m.group(2)
        # keep the street name words up to a comma (drop city/state/zip)
        street = street.split(",")[0]
        street_words = [w for w in re.split(r"\s+", street) if w]
        # drop common suffix abbreviations so "St" vs "Street" still matches
        drop = {"st", "street", "dr", "drive", "ave", "avenue", "rd", "road",
                "ln", "lane", "ct", "court", "cir", "circle", "way", "pl",
                "place", "blvd", "trl", "trail"}
        core = [w for w in street_words if w.lower().strip(".") not in drop]
        tokens = [house] + (core if core else street_words[:1])
    else:
        tokens = [t for t in re.split(r"[,\s]+", address) if t][:3]

    try:
        layer_id, meta, root_raw = discover_parcel_layer(
            mapserver, timeout, layer_override)
        result["raw"]["mapserver_root"] = root_raw
        fields = [f.get("name") for f in meta.get("fields", []) if f.get("name")]
        result["raw"]["layer_id"] = layer_id
        result["raw"]["layer_name"] = meta.get("name")
        result["raw"]["layer_fields"] = fields

        fmap = build_field_map(fields)
        if situs_field_override:
            fmap["situs_address"] = situs_field_override
        result["raw"]["field_map"] = fmap

        situs_field = fmap["situs_address"]
        if not situs_field:
            raise RuntimeError(
                "Could not identify a situs/address field. Available fields: %s"
                % fields)

        data, where, final_url = query_layer_by_address(
            mapserver, layer_id, situs_field, tokens, timeout)
        result["raw"]["query_url"] = final_url
        result["raw"]["query_where"] = where
        result["raw"]["query_response"] = data
        result["source"] = "Teller County ArcGIS Property/MapServer (layer %d)" % layer_id

        feats = data.get("features", []) or []
        if not feats:
            result["errors"].append(
                "No parcels matched WHERE %s. Widen tokens or check the situs "
                "field." % where)
            return result

        # If multiple, pick the one whose assessed value matches (if given).
        chosen = None
        for feat in feats:
            rec = extract_record(feat.get("attributes", {}), fmap)
            ok, _ = verify_match(rec, expect_assessed)
            if ok and expect_assessed is not None:
                chosen = (feat, rec)
                break
        if chosen is None:
            feat = feats[0]
            chosen = (feat, extract_record(feat.get("attributes", {}), fmap))
            if len(feats) > 1:
                result["errors"].append(
                    "%d parcels matched; none matched the expected assessed "
                    "value, returning the first. Review raw.query_response."
                    % len(feats))

        feat, record = chosen
        result["record"] = record
        verified, note = verify_match(record, expect_assessed)
        result["match_verified"] = verified
        result["verification_note"] = note
        result["jurisdiction_note"] = infer_jurisdiction(record)
        return result

    except Exception as exc:  # noqa: BLE001 - report, don't crash
        result["errors"].append("ArcGIS path failed: %s: %s"
                                % (type(exc).__name__, exc))
        result["errors"].append(
            "Fallback: scrape the assessor address search at %s "
            "(not implemented here; page is ASP.NET/JS and may require a "
            "session). Or call the Teller County Assessor at 719-689-2941."
            % EAGLEWEB_SEARCH)
        return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Look up a Teller County, CO parcel ownership record.")
    ap.add_argument("address",
                    help='Property address, e.g. "29 Nez Perce St, Woodland Park, CO 80863"')
    ap.add_argument("--mapserver", default=DEFAULT_MAPSERVER,
                    help="ArcGIS MapServer/FeatureServer base URL")
    ap.add_argument("--expect-assessed", type=float, default=None,
                    help="Known assessed value to confirm the match (e.g. 12561)")
    ap.add_argument("--layer", type=int, default=None,
                    help="Force a specific layer id (skip auto-discovery)")
    ap.add_argument("--situs-field", default=None,
                    help="Force the address field name if the heuristic misses")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--raw", action="store_true",
                    help="Include the full raw ArcGIS responses in the output")
    args = ap.parse_args(argv)

    out = lookup(args.address, args.mapserver, args.expect_assessed,
                 args.timeout, args.layer, args.situs_field)
    if not args.raw:
        # keep field_map + query_where for verification, drop bulky payloads
        raw = out.get("raw", {})
        for k in ("mapserver_root", "query_response"):
            if k in raw:
                raw[k] = "<omitted; re-run with --raw>"
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("record") else 1


if __name__ == "__main__":
    raise SystemExit(main())
