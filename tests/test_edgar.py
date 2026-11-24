from newsbot.sources import edgar


def test_parse_form4_open_market_purchase(fixture_text):
    f = edgar.parse_form4(fixture_text("form4_purchase.xml"))
    assert f["symbol"] == "BORR"
    assert f["issuer_cik"] == "0001715497"
    assert f["owner"]["is_director"] and not f["owner"]["is_officer"]
    assert len(f["trades"]) == 1
    t = f["trades"][0]
    assert t["code"] == "P" and t["shares"] == 9_000_000
    assert abs(t["value"] - 9_000_000 * 3.3835) < 1e-6


def test_parse_feed(fixture_text):
    entries = edgar.parse_feed(fixture_text("current_form4.atom"))
    assert len(entries) == 100
    e = entries[0]
    assert e["form"] == "4" and len(e["cik"]) == 10 and e["accession"]
    assert e["updated"].endswith("+00:00")  # normalized to UTC
    assert {x["role"] for x in entries} <= {"Issuer", "Reporting", "Filer", "Subject"}


def test_form4_xml_url_skips_rendered_copy(fixture_text):
    url = edgar.form4_xml_url(fixture_text("form4_index.htm"))
    assert url.endswith(".xml") and "/xsl" not in url and url.startswith("https://www.sec.gov/")


def test_parse_8k_index(fixture_text):
    idx = edgar.parse_8k_index(fixture_text("8k_index.htm"))
    assert ("8.01", "Other Events") in idx["items"]
    assert idx["docs"] and all(d.startswith("https://www.sec.gov/Archives/") for d in idx["docs"])
    assert not any("ix?doc" in d for d in idx["docs"])


def test_cursor_stops_before_failed_filing():
    filings = [{"updated": "2026-11-23T15:00:00+00:00"}, {"updated": "2026-11-23T14:00:00+00:00"}]
    assert edgar._cursor(filings, []) == "2026-11-23T15:00:00+00:00"
    assert edgar._cursor(filings, ["2026-11-23T14:00:00+00:00"]) < "2026-11-23T14:00:00+00:00"


def test_html_to_text():
    t = edgar.html_to_text("<html><head><title>x</title></head><body><p>Revenue&nbsp;up</p><script>bad()</script></body></html>")
    assert "Revenue up" in t and "bad()" not in t and "x" not in t
