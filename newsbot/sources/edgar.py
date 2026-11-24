"""SEC EDGAR: Form 4 (insider transactions) and 8-K (material events).

Uses the public "latest filings" Atom feed, paged backwards until it reaches
filings already seen, and keeps only filings of companies in the universe.
Free, official, exact timestamps, no scraping of news sites.
"""
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from .. import net
from ..db import insert_event, kv_get, kv_set

FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
ATOM = "{http://www.w3.org/2005/Atom}"
BASE = "https://www.sec.gov"

# 8-K items that carry information worth scoring. Pure exhibit/admin items
# (9.01 exhibits, 5.07 vote results, ...) are dropped unless combined with these.
INTERESTING_8K_ITEMS = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "1.05": "Material Cybersecurity Incident",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.02": "Departure/Appointment of Directors or Officers",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
}


def _utc_iso(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(timezone.utc).isoformat()


def parse_feed(xml_text: str) -> list:
    """Atom feed -> list of filings. One filing appears once per party (issuer,
    reporting owner, filer); every entry carries the CIK of that party."""
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        title = e.findtext(f"{ATOM}title", "")
        m = re.match(r"(?P<form>[^ ]+) - (?P<name>.*) \((?P<cik>\d{10})\) \((?P<role>[^)]+)\)", title)
        if not m:
            continue
        acc = re.search(r"accession-number=([\d-]+)", e.findtext(f"{ATOM}id", ""))
        link = e.find(f"{ATOM}link")
        out.append({
            "form": m["form"], "name": m["name"], "cik": m["cik"], "role": m["role"],
            "accession": acc.group(1) if acc else None,
            "index_url": link.get("href") if link is not None else None,
            "updated": _utc_iso(e.findtext(f"{ATOM}updated")),
        })
    return out


def fetch_recent(form: str, user_agent: str, seen_until: str = None, max_pages: int = 10) -> list:
    """Page through the 'latest filings' feed (newest first) until we reach
    filings at or before `seen_until` (UTC ISO) or run out of pages."""
    filings = []
    for page in range(max_pages):
        resp = net.get(FEED_URL, headers={"User-Agent": user_agent}, params={
            "action": "getcurrent", "type": form, "count": 100, "start": page * 100,
            "owner": "include", "output": "atom"})
        batch = parse_feed(resp.text)
        if not batch:
            break
        filings.extend(batch)
        if seen_until and batch[-1]["updated"] <= seen_until:
            break
    return filings


# ---------------------------------------------------------------- Form 4

def _val(node, path):
    el = node.find(path)
    if el is None:
        return None
    v = el.findtext("value")
    return (v if v is not None else el.text or "").strip() or None


def parse_form4(xml_text: str) -> dict:
    """Structured summary of a Form 4. Only non-derivative open-market trades
    (code P = purchase, S = sale) are informative; grants, option exercises,
    tax withholding etc. are ignored."""
    root = ET.fromstring(xml_text)
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    flag = lambda tag: (rel is not None and (rel.findtext(tag) or "").strip() in ("1", "true"))
    owner = {
        "name": root.findtext("reportingOwner/reportingOwnerId/rptOwnerName", "").strip(),
        "is_director": flag("isDirector"),
        "is_officer": flag("isOfficer"),
        "is_ten_percent": flag("isTenPercentOwner"),
        "title": (rel.findtext("officerTitle") or "").strip() if rel is not None else "",
    }
    trades = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = (t.findtext("transactionCoding/transactionCode") or "").strip()
        if code not in ("P", "S"):
            continue
        shares = float(_val(t, "transactionAmounts/transactionShares") or 0)
        price = float(_val(t, "transactionAmounts/transactionPricePerShare") or 0)
        after = _val(t, "postTransactionAmounts/sharesOwnedFollowingTransaction")
        trades.append({
            "code": code, "date": _val(t, "transactionDate"),
            "shares": shares, "price": price, "value": shares * price,
            "owned_after": float(after) if after else None,
        })
    return {
        "issuer_cik": (root.findtext("issuer/issuerCik") or "").strip().zfill(10),
        "symbol": (root.findtext("issuer/issuerTradingSymbol") or "").strip().upper(),
        "owner": owner,
        "planned_10b5_1": (root.findtext("aff10b5One") or "").strip() in ("1", "true"),
        "trades": trades,
    }


def form4_xml_url(index_html: str) -> str:
    """The raw XML (not the xsl-rendered copy) linked from a filing index."""
    for href in re.findall(r'href="([^"]+\.xml)"', index_html):
        if "/xsl" not in href:
            return BASE + href if href.startswith("/") else href
    return None


# ---------------------------------------------------------------- 8-K

def parse_8k_index(index_html: str) -> dict:
    items = re.findall(r"Item (\d+\.\d+):\s*([^<]+)", index_html)
    accepted = re.search(r"Accepted</div>\s*<div class=\"info\">([^<]+)<", index_html)
    docs = []
    for href in re.findall(r'href="([^"]+\.htm)"', index_html):
        href = href.replace("/ix?doc=", "")
        if "/Archives/" in href and not href.endswith("-index.htm"):
            docs.append(BASE + href if href.startswith("/") else href)
    return {"items": [(n, d.strip()) for n, d in items],
            "accepted": accepted.group(1) if accepted else None,
            "docs": list(dict.fromkeys(docs))}


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _pick_8k_docs(docs: list) -> list:
    """Main 8-K document first, then press-release exhibits (EX-99.x), which is
    where earnings numbers and deal terms actually live."""
    main = [d for d in docs if re.search(r"8-?k", d.split("/")[-1], re.I) and "ex" not in d.split("/")[-1].lower()]
    ex99 = [d for d in docs if re.search(r"ex-?99", d.split("/")[-1], re.I)]
    return (main[:1] + ex99[:2]) or docs[:1]


# ---------------------------------------------------------------- ingest

def _cursor(filings: list, failed: list) -> str:
    """Newest timestamp we're done with. If a filing failed (e.g. its index
    page wasn't published yet), stop just before it so the next run retries
    it; already-stored filings are skipped by id, so nothing is duplicated."""
    newest = max(f["updated"] for f in filings)
    if not failed:
        return newest
    oldest_fail = datetime.fromisoformat(min(failed)) - timedelta(seconds=1)
    return min(newest, oldest_fail.isoformat())


def fetch_index(urls: list, user_agent: str) -> str:
    """A filing's index page exists under every party's CIK folder, but the
    copy under the issuer's folder sometimes appears minutes later than the
    feed entry (404). Try every party's copy before giving up."""
    last = None
    for url in dict.fromkeys(u for u in urls if u):
        try:
            return net.get(url, headers={"User-Agent": user_agent}, retries=0).text
        except Exception as e:
            last = e
    raise last or RuntimeError("no index url")


def ingest(con, settings, ciks: dict, now_iso: str) -> dict:
    """Pull new Form 4 + 8-K filings of universe companies into `events`."""
    ua = settings.sec_user_agent
    if not ua:
        raise SystemExit("SEC_USER_AGENT is not set - see .env.example")
    stats = {"form4": 0, "8k": 0}

    # --- Form 4 ---
    seen = kv_get(con, "edgar_form4_seen_until")
    filings = fetch_recent("4", ua, seen, settings.sec_max_pages)
    issuers, links, failed = {}, {}, []
    for f in filings:
        links.setdefault(f["accession"], []).append(f["index_url"])
        if f["role"] == "Issuer" and f["cik"] in ciks and (not seen or f["updated"] > seen):
            issuers.setdefault(f["accession"], f)
    for acc, f in issuers.items():
        if con.execute("SELECT 1 FROM events WHERE id=?", (f"form4:{acc}",)).fetchone():
            continue
        try:
            idx = fetch_index(links[acc], ua)
            xml_url = form4_xml_url(idx)
            parsed = parse_form4(net.get(xml_url, headers={"User-Agent": ua}).text)
        except Exception as e:
            print(f"  form4 {acc}: {e}")
            failed.append(f["updated"])
            continue
        if not parsed["trades"]:
            continue  # grants / exercises / withholding - not informative
        ticker = ciks[f["cik"]]
        buys = sum(t["value"] for t in parsed["trades"] if t["code"] == "P")
        sells = sum(t["value"] for t in parsed["trades"] if t["code"] == "S")
        role = parsed["owner"]["title"] or ("Director" if parsed["owner"]["is_director"] else
                                            "10% owner" if parsed["owner"]["is_ten_percent"] else "Insider")
        title = f"{ticker}: {parsed['owner']['name']} ({role}) " + (
            f"bought ${buys:,.0f}" if buys >= sells else f"sold ${sells:,.0f}")
        stats["form4"] += insert_event(con, {
            "id": f"form4:{acc}", "source": "edgar_form4", "kind": "insider",
            "published_at": f["updated"], "ingested_at": now_iso, "tickers": [ticker],
            "title": title, "url": f["index_url"], "meta": parsed,
        })
    if filings:
        kv_set(con, "edgar_form4_seen_until", _cursor(filings, failed))

    # --- 8-K ---
    seen = kv_get(con, "edgar_8k_seen_until")
    filings = fetch_recent("8-K", ua, seen, settings.sec_max_pages)
    failed = []
    for f in filings:
        if f["cik"] not in ciks or f["form"] not in ("8-K", "8-K/A") or (seen and f["updated"] <= seen):
            continue
        eid = f"8k:{f['accession']}"
        if con.execute("SELECT 1 FROM events WHERE id=?", (eid,)).fetchone():
            continue
        try:
            idx = parse_8k_index(fetch_index([f["index_url"]], ua))
        except Exception as e:
            print(f"  8-K {f['accession']}: {e}")
            failed.append(f["updated"])
            continue
        items = [(n, d) for n, d in idx["items"] if n in INTERESTING_8K_ITEMS]
        if not items:
            continue
        parts = []
        for url in _pick_8k_docs(idx["docs"]):
            try:
                parts.append(html_to_text(net.get(url, headers={"User-Agent": ua}).text))
            except Exception as e:
                print(f"  8-K doc {url}: {e}")
        ticker = ciks[f["cik"]]
        body = "\n\n---\n\n".join(parts)[: settings.llm_max_input_chars]
        stats["8k"] += insert_event(con, {
            "id": eid, "source": "edgar_8k", "kind": "filing",
            "published_at": f["updated"], "ingested_at": now_iso, "tickers": [ticker],
            "title": f"{ticker} 8-K: " + "; ".join(f"{n} {d}" for n, d in items),
            "body": body, "url": f["index_url"], "meta": {"items": [n for n, _ in items]},
        })
    if filings:
        kv_set(con, "edgar_8k_seen_until", _cursor(filings, failed))
    con.commit()
    return stats
