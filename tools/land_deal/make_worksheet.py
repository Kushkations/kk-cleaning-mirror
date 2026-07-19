"""Generate a manual skip-trace worksheet (free-lookup links) from the CSV.

Reads a contacts CSV (owner_name, mailing_address, mailing_city, mailing_state,
mailing_zip, situs_address, schedule) and writes a Markdown worksheet with
ready-to-click TruePeopleSearch / FastPeopleSearch links per owner and blank
fields to record what you find. No network; ToS-compliant (links only).
"""
import csv
import sys
import land_deal as L


def build(rows):
    out = ["# Skip-trace worksheet (free manual lookup)\n",
           "For each owner: click a link, find the result whose address matches "
           "**Match against**, then write the phone/email in the blanks. "
           "Address-based links are the most reliable for residences; use the "
           "name link when the mailing address is an office/PO box.\n"]
    for r in rows:
        name = r.get("owner_name", "")
        mailing = ", ".join(p for p in [
            r.get("mailing_address", ""),
            r.get("mailing_city", ""),
            "%s %s" % (r.get("mailing_state", ""), r.get("mailing_zip", "")),
        ] if p and p.strip())
        links = L.people_search_links(name, mailing)
        out.append("\n---\n")
        out.append("## %s" % name)
        out.append("- **Property:** %s  (Schedule %s)" %
                   (r.get("situs_address", ""), r.get("schedule", "")))
        out.append("- **Match against:** %s" % links["match_against"])
        if links["fastpeoplesearch_by_address"]:
            out.append("- Search by ADDRESS (best): %s" % links["fastpeoplesearch_by_address"])
        if links["fastpeoplesearch_by_name"]:
            out.append("- Search by NAME (FastPeopleSearch): %s" % links["fastpeoplesearch_by_name"])
        if links["truepeoplesearch_by_name"]:
            out.append("- Search by NAME (TruePeopleSearch): %s" % links["truepeoplesearch_by_name"])
        out.append("")
        out.append("  - Phone 1: ______________________  (mobile / landline?)")
        out.append("  - Phone 2: ______________________")
        out.append("  - Email:   ______________________")
        out.append("  - Notes:   ______________________")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "output/nez_perce_contacts.csv"
    with open(src, newline="") as fh:
        rows = list(csv.DictReader(fh))
    md = build(rows)
    dst = sys.argv[2] if len(sys.argv) > 2 else "output/skiptrace_worksheet.md"
    with open(dst, "w") as fh:
        fh.write(md)
    print("Wrote %s (%d owners)" % (dst, len(rows)))
    print(md)
