# land_deal — address in, deal packet out

One command turns a property address into: the county parcel record (owner,
schedule #, values, zoning, lot size, legal), the owner's mailing address,
skip-traced phone/email, and a ready-to-mail offer letter.

Built and tuned for **Teller County, CO** (Woodland Park area). The parsing is
tested against real assessor-record fields.

## Quick start (run on your own computer — no sandbox limits)

```bash
cd tools/land_deal
# optional but recommended:
python3 -m pip install requests

# skip-trace needs a provider key (see below). Without it you still get the
# full parcel record + letter; just no phone/email.
export SKIPTRACE_PROVIDER=batchdata
export SKIPTRACE_API_KEY=your_key_here

python3 land_deal.py "29 Nez Perce St, Woodland Park, CO 80863" \
    --buyer-name "Shaquan" \
    --buyer-contact "Shaquan@cashawmanagement.com" \
    --out packet.json --letter-out letter.txt
```

If you already have the schedule number, skip the GIS step:

```bash
python3 land_deal.py "29 Nez Perce St" --schedule R0011302 \
    --buyer-name "Shaquan" --buyer-contact "..." --out packet.json
```

Output: `packet.json` (structured data + skip-trace results) and `letter.txt`.

## What each step does
1. **Parcel** — Teller County ArcGIS REST; finds the parcel by address, returns
   owner + schedule number.
2. **Detail** — Assessor EagleWeb record page
   (`tcweb.tellercounty.gov/proprecs/Data.aspx?AcctNo=R00...`); returns
   actual/assessed value, acct type, mailing address, zoning, acres, legal.
3. **Skip trace** — owner name + mailing address -> provider API -> phones +
   emails. **Requires your API key.** No key = step skipped; nothing invented.
4. **Letter** — plain, non-pushy offer letter to the mailing address of record.

## Skip-trace providers
Default is BatchData (`SKIPTRACE_PROVIDER=batchdata`, `SKIPTRACE_API_KEY=...`).
The provider call is isolated in `_skip_batchdata()`; verify request/response
field paths against current BatchData docs and adjust if their schema changed
(the raw response is always returned in the packet for inspection). To add
another provider (Whitepages Pro, REISkip, etc.), write a `_skip_<name>()`
function and branch to it in `skip_trace()`.

## Legit-use / compliance
Owner name + mailing address are public records. Skip-tracing to contact an
owner about buying their land is standard practice, but **you** are responsible
for contact compliance: prefer mail and manual calls, honor Do-Not-Call / TCPA
(no autodialed or blast texts to cell numbers without consent), and follow your
skip-trace provider's terms of service.

## Why it may not run "live" inside a Claude Code web session
Claude Code on the web runs in a sandbox whose **outbound network is set by the
environment's network policy**. If that policy blocks `tcweb.tellercounty.gov`
and the skip-trace host, the network steps return a clear error instead of
data. Two fixes:

- **Run it locally** (above) — your laptop has open network. Most reliable.
- **Loosen the environment's network policy** to allow those hosts, then a
  Claude session can run it for you. See:
  https://code.claude.com/docs/en/claude-code-on-the-web
  (environments / network access). The policy is chosen when the environment is
  created; you or an admin can recreate/adjust it with a broader allowlist.

Either way, skip-trace also needs the API key set.

## Tests
```bash
python3 test_parse.py   # offline; no network
```
