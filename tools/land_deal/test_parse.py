"""Offline tests for land_deal parsing (no network)."""
import land_deal as L


def test_mailing_two_line():
    html = ("<tr><td>Mailing Address</td><td>149 ROSEWOOD AVE<br>"
            "ORMOND BEACH, FL 321745524</td></tr>"
            "<tr><td>Physical Address</td><td>29 NEZ PERCE ST</td></tr>")
    f = L.parse_eagleweb_detail(html)
    assert f["mailing_address"] == "149 ROSEWOOD AVE, ORMOND BEACH, FL 321745524", f["mailing_address"]
    s = L.split_mailing(f["mailing_address"])
    assert s["street"] == "149 ROSEWOOD AVE", s
    assert s["city"] == "ORMOND BEACH", s
    assert s["state"] == "FL", s
    assert s["zip"] == "32174-5524", s


def test_full_detail():
    html = """
    <tr><td>Account No</td><td>R0011302</td></tr>
    <tr><td>Actual</td><td>$15,192</td></tr>
    <tr><td>Assessed</td><td>$4,100</td></tr>
    <tr><td>Owner Name</td><td>TRIZ, JONATHAN JULIAN</td></tr>
    <tr><td>Acres</td><td>0.190000</td></tr>
    <tr><td>Zoned</td><td>R-1</td></tr>
    """
    f = L.parse_eagleweb_detail(html)
    assert f["account_no"] == "R0011302"
    assert f["assessed_value_num"] == 4100.0
    assert f["lot_size_sqft"] == 8276
    assert L.split_owner_name(f["owner_name"]) == {
        "first": "Jonathan", "last": "Triz", "raw": "TRIZ, JONATHAN JULIAN"}


if __name__ == "__main__":
    test_mailing_two_line()
    test_full_detail()
    print("ALL TESTS PASSED")
