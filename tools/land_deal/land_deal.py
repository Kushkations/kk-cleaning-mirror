#!/usr/bin/env python3
"""
land_deal.py — address in, deal packet out.

Give it a property address; it runs the same chain you'd do by hand:

  1. PARCEL   Teller County ArcGIS REST -> owner, schedule #, geometry.
  2. DETAIL   Teller County Assessor "EagleWeb" record page
              (tcweb.tellercounty.gov/proprecs/Data.aspx?AcctNo=R00...)
              -> actual/assessed value, acct type, mailing address, zoning,
                 acres, map/tax district, brief legal.
  3. SKIP     Owner name + mailing address -> skip-trace provider (BatchData
              by default) -> phone numbers + emails.  Requires YOUR api key.
  4. LETTER   Writes a plain, non-pushy offer/inquiry letter to the owner's
              mailing address of record.

Output: one JSON "deal packet" + a printable letter (.txt).

--------------------------------------------------------------------------
Legit-use note
--------------------------------------------------------------------------
Owner name + mailing address are public county records. Skip-tracing to
contact an owner about buying their land is standard real-estate practice,
but you are responsible for how you contact them: honor Do-Not-Call / TCPA
(mail and manual calls are safest; no autodialed/blast texts to cell numbers
without consent), and follow your skip-trace provider's terms of service.

--------------------------------------------------------------------------
Environment note
--------------------------------------------------------------------------
If run inside a sandbox that blocks outbound HTTPS to the county/skip-trace
hosts, the network steps return a clear error instead of crashing. Run it
from a normal network (your laptop) and it works end to end.

Config (env vars):
  SKIPTRACE_PROVIDER   batchdata | none            (default: batchdata)
  SKIPTRACE_API_KEY    your provider api key
  TELLER_MAPSERVER     override ArcGIS base url
Only the stdlib is required; `requests` is used if installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# HTTP (requests if available, else stdlib urllib) — proxy/tls aware errors
# --------------------------------------------------------------------------
_UA = "land-deal/1.0 (public-records + owner outreach)"

try:
    import requests  # type: ignore
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    _HAVE_REQUESTS = False
    import urllib.parse
    import urllib.request
    import urllib.error


class FetchError(RuntimeError):
    pass


def http_get(url: str, params: Optional[Dict[str, Any]] = None,
             timeout: int = 30) -> Tuple[str, str]:
    """Return (text, final_url). Raises FetchError with a friendly message."""
    try:
        if _HAVE_REQUESTS:
            r = requests.get(url, params=params or {}, timeout=timeout,
                             headers={"User-Agent": _UA})
            r.raise_for_status()
            return r.text, r.url
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(url + q, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace"), req.full_url
    except Exception as exc:  # noqa: BLE001
        raise FetchError(_explain(url, exc)) from exc


def http_post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str],
                   timeout: int = 30) -> Any:
    try:
        if _HAVE_REQUESTS:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.json()
        import urllib.request
        data = json.dumps(payload).encode()
        h = {"Content-Type": "application/json", "User-Agent": _UA, **headers}
        req = urllib.request.Request(url, data=data, headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        raise FetchError(_explain(url, exc)) from exc


def _explain(url: str, exc: Exception) -> str:
    msg = "%s: %s" % (type(exc).__name__, exc)
    if "403" in msg or "Tunnel" in msg or "ProxyError" in msg:
        return ("blocked reaching %s (%s). This host is not allowed by the "
                "current network/egress policy — run from a normal network."
                % (url, msg))
    return "failed reaching %s (%s)" % (url, msg)


def get_json(url: str, params: Dict[str, Any], timeout: int = 30) -> Tuple[Any, str]:
    text, final = http_get(url, params, timeout)
    return json.loads(text), final


# --------------------------------------------------------------------------
# Address parsing
# --------------------------------------------------------------------------
_SUFFIX = {"st", "street", "dr", "drive", "ave", "avenue", "rd", "road", "ln",
           "lane", "ct", "court", "cir", "circle", "way", "pl", "place",
           "blvd", "trl", "trail", "ter", "terrace", "pkwy", "hwy"}


def parse_address(addr: str) -> Dict[str, Any]:
    out = {"raw": addr, "house": None, "street_core": [], "tokens": [],
           "city": None, "state": None, "zip": None}
    parts = [p.strip() for p in addr.split(",")]
    street = parts[0] if parts else addr
    if len(parts) >= 2:
        out["city"] = parts[1] or None
    if len(parts) >= 3:
        m = re.search(r"([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)?", parts[2])
        if m:
            out["state"] = m.group(1).upper()
            out["zip"] = m.group(2)
    m = re.match(r"\s*(\d+)\s+(.*)", street)
    if m:
        out["house"] = m.group(1)
        words = [w for w in re.split(r"\s+", m.group(2)) if w]
        core = [w for w in words if w.lower().strip(".") not in _SUFFIX]
        out["street_core"] = core if core else words[:1]
        out["tokens"] = [out["house"]] + out["street_core"]
    else:
        out["tokens"] = [t for t in re.split(r"[,\s]+", street) if t][:3]
    return out


def split_mailing(mailing: str) -> Dict[str, Optional[str]]:
    """Split 'street, city, ST zip' into components for skip-trace payloads."""
    d = {"street": None, "city": None, "state": None, "zip": None}
    if not mailing:
        return d
    txt = re.sub(r"\s+", " ", mailing.strip())
    m = re.search(r"^(.*?),?\s*([A-Za-z .]+),\s*([A-Za-z]{2})\s*(\d{5}(?:-?\d{4})?)?\s*$", txt)
    if m:
        d["street"] = m.group(1).strip().rstrip(",")
        d["city"] = m.group(2).strip()
        d["state"] = m.group(3).upper()
        z = m.group(4)
        if z and len(z) == 9:
            z = z[:5] + "-" + z[5:]
        d["zip"] = z
    else:
        d["street"] = txt
    return d


def split_owner_name(owner: str) -> Dict[str, Optional[str]]:
    """County format is usually 'LAST, FIRST MIDDLE'. Best-effort split."""
    d = {"first": None, "last": None, "raw": owner}
    if not owner:
        return d
    if "," in owner:
        last, rest = owner.split(",", 1)
        d["last"] = last.strip().title()
        first_parts = rest.strip().split()
        d["first"] = first_parts[0].title() if first_parts else None
    else:
        parts = owner.split()
        if len(parts) >= 2:
            d["first"], d["last"] = parts[0].title(), parts[-1].title()
        elif parts:
            d["last"] = parts[0].title()
    return d


# --------------------------------------------------------------------------
# Step 1: Teller County ArcGIS parcel lookup
# --------------------------------------------------------------------------
DEFAULT_MAPSERVER = os.environ.get(
    "TELLER_MAPSERVER",
    "https://tcweb.tellercounty.gov/arcgis/rest/services/Property/MapServer")

EAGLEWEB_DETAIL = "https://tcweb.tellercounty.gov/proprecs/Data.aspx"
EAGLEWEB_SEARCH = "https://tcweb.tellercounty.gov/proprecs/SearchAddress.aspx"

_ARCGIS_FIELDS = {
    "owner_name":      [r"^owner.?name$", r"^owner$", r"owner.?nam", r"^name$"],
    "schedule_number": [r"sched", r"account", r"^acct", r"parcel.?num", r"^pin$", r"^apn$"],
    "situs_address":   [r"situs", r"site.?addr", r"phys.?addr", r"prop.?addr", r"^address$", r"location"],
    "mailing_address": [r"mail.*addr", r"^mailing", r"owner.*addr"],
    "acres":           [r"acre"],
    "assessed_value":  [r"assess", r"assd"],
    "actual_value":    [r"actual", r"market", r"total.?val", r"appraised"],
}


def _match(patterns: List[str], names: List[str]) -> Optional[str]:
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for n in names:
            if rx.search(n):
                return n
    return None


def arcgis_lookup(address: str, mapserver: str, timeout: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "schedule_number": None,
                           "owner_name": None, "attributes": None,
                           "layer_id": None, "note": None}
    root, _ = get_json(mapserver, {"f": "json"}, timeout)
    layers = root.get("layers", []) or []
    lid = None
    for lay in layers:
        if re.search(r"parcel|ownership|owner", str(lay.get("name", "")), re.I):
            lid = lay.get("id")
            break
    if lid is None and layers:
        lid = layers[0].get("id")
    if lid is None:
        out["note"] = "no layers on MapServer"
        return out
    meta, _ = get_json("%s/%d" % (mapserver, lid), {"f": "json"}, timeout)
    names = [f.get("name") for f in meta.get("fields", []) if f.get("name")]
    fmap = {k: _match(pats, names) for k, pats in _ARCGIS_FIELDS.items()}
    situs = fmap["situs_address"]
    if not situs:
        out["note"] = "no address field; fields=%s" % names
        return out
    toks = parse_address(address)["tokens"]
    where = " AND ".join("UPPER(%s) LIKE '%%%s%%'" % (situs, t.replace("'", "''").upper())
                         for t in toks) or "1=1"
    data, _ = get_json("%s/%d/query" % (mapserver, lid),
                       {"where": where, "outFields": "*",
                        "returnGeometry": "false", "f": "json"}, timeout)
    feats = data.get("features") or []
    if not feats:
        out["note"] = "no parcel matched WHERE %s" % where
        out["raw_query"] = data
        return out
    attrs = feats[0].get("attributes", {})
    out.update(ok=True, layer_id=lid, attributes=attrs,
               owner_name=attrs.get(fmap["owner_name"]) if fmap["owner_name"] else None,
               schedule_number=attrs.get(fmap["schedule_number"]) if fmap["schedule_number"] else None)
    out["field_map"] = fmap
    out["match_count"] = len(feats)
    return out


# --------------------------------------------------------------------------
# Step 2: EagleWeb assessor detail page (by schedule/account number)
# --------------------------------------------------------------------------
# Field labels as they appear on tcweb.tellercounty.gov/proprecs/Data.aspx
_DETAIL_LABELS = {
    "account_no":       ["Account No"],
    "parcel_id":        ["Parcel Id"],
    "actual_value":     ["Actual"],
    "assessed_value":   ["Assessed"],
    "acct_type":        ["Acct Type"],
    "owner_name":       ["Owner Name"],
    "mailing_address":  ["Mailing Address"],
    "physical_address": ["Physical Address"],
    "school_dist":      ["School Dist"],
    "acres":            ["Acres"],
    "map_no":           ["Map No"],
    "tax_dist":         ["Tax Dist"],
    "area":             ["Area"],
    "brief_legal":      ["Brief Legal"],
    "zoning":           ["Zoned", "Zoning"],
}


def _strip_tags(html: str) -> str:
    txt = re.sub(r"(?is)<script.*?</script>", " ", html)
    txt = re.sub(r"(?is)<style.*?</style>", " ", txt)
    txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    return txt


def parse_eagleweb_detail(html: str) -> Dict[str, Any]:
    """Parse the label/value pairs off the assessor record page.

    Works on the rendered text: for each known label we grab the text that
    follows it up to the next known label. Tolerant of the ASP.NET table
    markup so it survives minor layout changes.
    """
    text = _strip_tags(html)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    joined = "\n".join(lines)

    all_labels = [lab for labs in _DETAIL_LABELS.values() for lab in labs]
    label_alt = "|".join(re.escape(l) for l in sorted(all_labels, key=len, reverse=True))

    result: Dict[str, Any] = {}
    for key, labels in _DETAIL_LABELS.items():
        val = None
        for lab in labels:
            # value = text after the label, until the next known label
            m = re.search(r"(?is)\b%s\b\s*[:\-]?\s*(.*?)(?=\b(?:%s)\b|$)"
                          % (re.escape(lab), label_alt), joined)
            if m:
                v = m.group(1).strip(" \n:-|")
                if key == "mailing_address":
                    # keep the street / city-state-zip line break as a comma
                    v = re.sub(r"\s*\n\s*", ", ", v)
                    v = re.sub(r"(,\s*)+", ", ", v).strip(" ,")
                else:
                    v = re.sub(r"\s*\n\s*", " ", v).strip()
                if v:
                    val = v
                    break
        result[key] = val

    # numeric cleanups
    for k in ("actual_value", "assessed_value"):
        if result.get(k):
            n = re.sub(r"[^0-9.]", "", result[k].split()[0])
            result[k + "_num"] = float(n) if n else None
    if result.get("acres"):
        m = re.search(r"[\d.]+", result["acres"])
        result["acres_num"] = float(m.group()) if m else None
        if result.get("acres_num"):
            result["lot_size_sqft"] = round(result["acres_num"] * 43560)
    return result


def eagleweb_detail(schedule: str, timeout: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "schedule": schedule, "fields": None,
                           "url": None, "note": None}
    url = EAGLEWEB_DETAIL
    try:
        text, final = http_get(url, {"AcctNo": schedule}, timeout)
        out["url"] = final
        fields = parse_eagleweb_detail(text)
        out["fields"] = fields
        out["ok"] = any(fields.values())
        if not out["ok"]:
            out["note"] = "page fetched but no known labels parsed"
    except FetchError as exc:
        out["note"] = str(exc)
    return out


# --------------------------------------------------------------------------
# Step 3: skip trace (pluggable providers)
# --------------------------------------------------------------------------
def skip_trace(owner_name: str, mailing: str, provider: str,
               api_key: Optional[str], timeout: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"provider": provider, "phones": [], "emails": [],
                           "ok": False, "note": None, "raw": None}
    if provider in (None, "", "none"):
        out["note"] = "skip-trace disabled (SKIPTRACE_PROVIDER=none)"
        return out
    if not api_key:
        out["note"] = ("no api key. Set SKIPTRACE_API_KEY (and "
                       "SKIPTRACE_PROVIDER). Skip-trace not run — no numbers "
                       "are invented.")
        return out
    name = split_owner_name(owner_name)
    addr = split_mailing(mailing)
    try:
        if provider == "batchdata":
            out.update(_skip_batchdata(name, addr, api_key, timeout))
        else:
            out["note"] = ("unknown provider %r. Supported: batchdata, none. "
                           "Add a function to extend." % provider)
    except FetchError as exc:
        out["note"] = str(exc)
    return out


def _skip_batchdata(name: Dict[str, Any], addr: Dict[str, Any],
                    api_key: str, timeout: int) -> Dict[str, Any]:
    """BatchData skip-trace. Verify the request/response shape against current
    BatchData API docs; field paths below follow their documented schema and
    fail soft if it differs (raw response is returned for inspection)."""
    url = "https://api.batchdata.com/api/v1/property/skip-trace"
    payload = {
        "requests": [{
            "name": {"first": name.get("first"), "last": name.get("last")},
            "propertyAddress": {
                "street": addr.get("street"), "city": addr.get("city"),
                "state": addr.get("state"), "zip": addr.get("zip"),
            },
        }]
    }
    headers = {"Authorization": "Bearer %s" % api_key,
               "Content-Type": "application/json"}
    data = http_post_json(url, payload, headers, timeout)
    phones, emails = [], []
    try:
        results = (data.get("results") or data.get("data") or {})
        persons = []
        if isinstance(results, dict):
            persons = results.get("persons") or results.get("matches") or []
        elif isinstance(results, list):
            for r in results:
                persons += (r.get("persons") or r.get("matches") or [])
        for p in persons:
            for ph in (p.get("phoneNumbers") or p.get("phones") or []):
                num = ph.get("number") or ph.get("phone") or ph
                if num:
                    phones.append({"number": num,
                                   "type": ph.get("type") if isinstance(ph, dict) else None,
                                   "dnc": ph.get("dnc") if isinstance(ph, dict) else None})
            for em in (p.get("emails") or []):
                val = em.get("email") if isinstance(em, dict) else em
                if val:
                    emails.append(val)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "phones": [], "emails": [], "raw": data,
                "note": "got a response but could not map it (%s); see raw" % exc}
    return {"ok": bool(phones or emails), "phones": phones, "emails": emails,
            "raw": data,
            "note": None if (phones or emails) else "no matches returned"}


# --------------------------------------------------------------------------
# Step 4: offer letter
# --------------------------------------------------------------------------
def offer_letter(owner_name: str, mailing: str, situs: str,
                 buyer_name: str, buyer_contact: str,
                 schedule: Optional[str]) -> str:
    disp = split_owner_name(owner_name)
    greeting = disp.get("first") or (owner_name.split(",")[0].title() if owner_name else "Property Owner")
    sched = ("  (Schedule %s)" % schedule) if schedule else ""
    return (
        "%s\n\n"
        "Re: Your vacant parcel at %s%s\n\n"
        "Dear %s,\n\n"
        "My name is %s. I'm a local buyer interested in the vacant lot you own "
        "at %s. I'm reaching out directly to ask whether you'd consider selling.\n\n"
        "There's no obligation and no cost to you. If you're open to it, I'd be "
        "glad to make you a straightforward cash offer and cover typical closing "
        "costs. If the timing isn't right, no problem at all — feel free to keep "
        "my information for the future.\n\n"
        "The easiest way to reach me is: %s.\n\n"
        "Thank you for your time.\n\n"
        "Sincerely,\n%s\n"
        % (mailing, situs, sched, greeting, buyer_name, situs,
           buyer_contact, buyer_name)
    )


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------
def run(address: str, *, mapserver: str = DEFAULT_MAPSERVER,
        provider: Optional[str] = None, api_key: Optional[str] = None,
        expect_assessed: Optional[float] = None,
        buyer_name: str = "", buyer_contact: str = "",
        timeout: int = 30) -> Dict[str, Any]:
    provider = provider if provider is not None else os.environ.get("SKIPTRACE_PROVIDER", "batchdata")
    api_key = api_key if api_key is not None else os.environ.get("SKIPTRACE_API_KEY")

    packet: Dict[str, Any] = {
        "input_address": address,
        "parcel": {}, "detail": {}, "owner_contacts": {},
        "letter": None, "match_verified": None, "warnings": [], "errors": [],
    }

    # Step 1 — ArcGIS
    try:
        a = arcgis_lookup(address, mapserver, timeout)
        packet["parcel"] = {
            "schedule_number": a.get("schedule_number"),
            "owner_name": a.get("owner_name"),
            "layer_id": a.get("layer_id"),
            "match_count": a.get("match_count"),
            "note": a.get("note"),
            "attributes": a.get("attributes"),
        }
        if not a.get("ok"):
            packet["errors"].append("ArcGIS: %s" % a.get("note"))
    except FetchError as exc:
        packet["errors"].append("ArcGIS: %s" % exc)
        a = {"schedule_number": None, "owner_name": None}

    schedule = a.get("schedule_number")

    # Step 2 — EagleWeb detail (needs a schedule number)
    if schedule:
        d = eagleweb_detail(str(schedule).strip(), timeout)
        packet["detail"] = d
        if not d.get("ok") and d.get("note"):
            packet["warnings"].append("EagleWeb: %s" % d["note"])
    else:
        packet["warnings"].append(
            "No schedule number from ArcGIS -> skipped EagleWeb detail. "
            "Pass --schedule R00xxxxxx to pull it directly.")

    # Resolve owner/mailing/situs from whichever source has them
    det = (packet.get("detail") or {}).get("fields") or {}
    owner_name = det.get("owner_name") or a.get("owner_name") or ""
    mailing = det.get("mailing_address") or ""
    situs = det.get("physical_address") or address
    packet["resolved"] = {
        "owner_name": owner_name or None,
        "mailing_address": mailing or None,
        "situs_address": situs,
        "schedule_number": det.get("account_no") or schedule,
        "actual_value": det.get("actual_value"),
        "assessed_value": det.get("assessed_value"),
        "zoning": det.get("zoning"),
        "acres": det.get("acres"),
        "lot_size_sqft": det.get("lot_size_sqft"),
        "brief_legal": det.get("brief_legal"),
        "area_subdivision": det.get("area"),
        "acct_type": det.get("acct_type"),
    }

    # Optional value verification
    if expect_assessed is not None:
        got = det.get("assessed_value_num")
        if got is None:
            packet["match_verified"] = False
            packet["warnings"].append(
                "Could not verify: no assessed value parsed.")
        else:
            packet["match_verified"] = abs(got - expect_assessed) <= 1.0
            if not packet["match_verified"]:
                packet["warnings"].append(
                    "Assessed value %s != expected %s (values change on "
                    "reassessment; confirm year)." % (got, expect_assessed))

    # Jurisdiction flag (city limits vs unincorporated)
    packet["jurisdiction_note"] = (
        "Confirm Woodland Park city limits vs unincorporated before "
        "septic/sewer/buildability assumptions. Zoning source on the record "
        "page indicates the administering authority.")

    # Step 3 — skip trace
    if owner_name:
        packet["owner_contacts"] = skip_trace(owner_name, mailing, provider,
                                               api_key, timeout)
    else:
        packet["owner_contacts"] = {"ok": False,
                                    "note": "no owner name resolved; skip-trace not run"}

    # Step 4 — letter
    if owner_name and mailing:
        packet["letter"] = offer_letter(
            owner_name, mailing, situs,
            buyer_name or "[YOUR NAME]",
            buyer_contact or "[YOUR PHONE / EMAIL]",
            packet["resolved"].get("schedule_number"))

    return packet


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Address -> land deal packet.")
    ap.add_argument("address", help='e.g. "29 Nez Perce St, Woodland Park, CO 80863"')
    ap.add_argument("--schedule", help="Skip ArcGIS; pull EagleWeb detail for this R00xxxxxx directly")
    ap.add_argument("--mapserver", default=DEFAULT_MAPSERVER)
    ap.add_argument("--provider", default=None, help="batchdata | none")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--expect-assessed", type=float, default=None)
    ap.add_argument("--buyer-name", default="")
    ap.add_argument("--buyer-contact", default="")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--out", help="write JSON packet here")
    ap.add_argument("--letter-out", help="write the letter .txt here")
    args = ap.parse_args(argv)

    if args.schedule:
        # Direct-detail path: skip ArcGIS entirely.
        packet: Dict[str, Any] = {"input_address": args.address, "warnings": [], "errors": []}
        d = eagleweb_detail(args.schedule, args.timeout)
        det = d.get("fields") or {}
        packet["detail"] = d
        owner = det.get("owner_name") or ""
        mailing = det.get("mailing_address") or ""
        situs = det.get("physical_address") or args.address
        packet["resolved"] = {"owner_name": owner or None,
                              "mailing_address": mailing or None,
                              "situs_address": situs,
                              "schedule_number": det.get("account_no") or args.schedule}
        packet["owner_contacts"] = (
            skip_trace(owner, mailing,
                       args.provider or os.environ.get("SKIPTRACE_PROVIDER", "batchdata"),
                       args.api_key or os.environ.get("SKIPTRACE_API_KEY"), args.timeout)
            if owner else {"ok": False, "note": "no owner parsed"})
        if owner and mailing:
            packet["letter"] = offer_letter(owner, mailing, situs,
                                            args.buyer_name or "[YOUR NAME]",
                                            args.buyer_contact or "[YOUR PHONE / EMAIL]",
                                            det.get("account_no") or args.schedule)
    else:
        packet = run(args.address, mapserver=args.mapserver,
                     provider=args.provider, api_key=args.api_key,
                     expect_assessed=args.expect_assessed,
                     buyer_name=args.buyer_name, buyer_contact=args.buyer_contact,
                     timeout=args.timeout)

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(packet, fh, indent=2, default=str)
    if args.letter_out and packet.get("letter"):
        with open(args.letter_out, "w") as fh:
            fh.write(packet["letter"])

    printable = {k: v for k, v in packet.items() if k not in ("detail",)}
    printable["detail_fields"] = (packet.get("detail") or {}).get("fields")
    print(json.dumps(printable, indent=2, default=str))
    ok = bool(packet.get("resolved", {}).get("owner_name"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
