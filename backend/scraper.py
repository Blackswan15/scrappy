"""
R&D Proposal Monitor — Scraper Backend (ICMR, DBT & NBHM Only)
==============================================================
Monitors research calls across:
1. ICMR (Indian Council of Medical Research)
2. DBT (Department of Biotechnology)
3. NBHM (National Board for Higher Mathematics)

Diffs new vs stored proposals and updates data/proposals.json seamlessly.
"""

import json
import os
import sys
import hashlib
import schedule
import time
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3
from bs4 import BeautifulSoup

from sources_config import SOURCES_METADATA, AGENCIES_LIST
from agency_seeds import AGENCY_SEEDS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

PROPOSALS_FILE   = DATA_DIR / "proposals.json"
NOTIF_FILE       = DATA_DIR / "notifications.json"
SNAPSHOT_FILE    = DATA_DIR / "snapshot.json"
LOG_FILE         = DATA_DIR / "scraper.log"

SCAN_INTERVAL_MINUTES = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("monitor")


def now_str():
    return datetime.now().strftime("%d %b %Y, %I:%M %p")


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            pass
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def proposal_id(title: str) -> str:
    return hashlib.sha1(title.strip().lower().encode()).hexdigest()[:12]


# ── Fast Parallel Document Header Verification ────────────────────────────────
def check_headers_parallel(urls: list[str]) -> dict[str, str]:
    results = {}
    valid = list(set(u for u in urls if u and u.startswith("http")))
    if not valid:
        return results

    def _fetch_one(u):
        try:
            r = requests.head(u, headers=HEADERS, timeout=(0.8, 1.2), allow_redirects=False, verify=False)
            return u, r.headers.get("Last-Modified", "")
        except Exception:
            return u, ""

    with ThreadPoolExecutor(max_workers=8) as pool:
        for u, lm in pool.map(_fetch_one, valid):
            results[u] = lm
    return results


# ── Dynamic Parsers ──────────────────────────────────────────────────────────

def scrape_icmr() -> list[dict]:
    """Parses the ICMR /call-for-proposals live table."""
    log.info("Checking ICMR live portal …")
    meta = SOURCES_METADATA.get("icmr", {})
    sn_val = str(meta.get("sn", "3"))
    url = "https://www.icmr.gov.in/call-for-proposals"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=(2.0, 5.0), verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table")
            if table:
                rows = []
                for tr in table.find_all("tr")[1:]:
                    tds = tr.find_all("td")
                    if len(tds) < 2:
                        continue

                    title_raw = tds[1].get_text(" ", strip=True)
                    last_date = tds[2].get_text(strip=True) if len(tds) > 2 else ""
                    apply_url = url
                    doc_url   = ""

                    if len(tds) > 4:
                        for a in tds[4].find_all("a", href=True):
                            href = a["href"].strip()
                            if href.endswith(".pdf") or "download" in href.lower() or "object" in href.lower():
                                doc_url = urljoin(url, href)
                                break

                    if not title_raw:
                        continue

                    status = "result" if title_raw.lower().startswith("result") or not last_date else "open"

                    rows.append({
                        "id":        proposal_id(title_raw),
                        "sn":        sn_val,
                        "title":     title_raw,
                        "lastDate":  last_date or "Open",
                        "status":    status,
                        "applyUrl":  apply_url,
                        "docUrl":    doc_url or apply_url,
                        "source":    "icmr",
                        "sourceName": meta.get("name", "Indian Council of Medical Research (ICMR)"),
                        "type":      meta.get("type", "Project proposal"),
                        "scannedAt": now_str(),
                    })
                if rows:
                    log.info(f"ICMR: {len(rows)} live proposals parsed")
                    return rows
    except Exception as e:
        log.warning(f"ICMR live check notice: {e}, using verified seeds")

    return scrape_generic_agency("icmr")


def scrape_dbt() -> list[dict]:
    """DBT scraper using verified seeds."""
    log.info("Checking DBT …")
    return scrape_generic_agency("dbt")


def scrape_nbhm_live() -> list[dict]:
    """Scrapes NBHM live research page."""
    log.info("Checking NBHM live …")
    meta = SOURCES_METADATA.get("nbhm", {})
    sn_val = str(meta.get("sn", "40"))
    url = meta.get("url", "https://nbhm.dae.gov.in/research.html")
    proposals = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=(1.0, 2.5), verify=False)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                txt = a.get_text(" ", strip=True)
                href = a["href"].strip()
                if "\\" in href:
                    continue
                if ("guideline" in txt.lower() or "result" in txt.lower() or "mandate" in txt.lower() or "grant" in txt.lower()) and len(txt) > 6:
                    status = "result" if "result" in txt.lower() else "open"
                    proposals.append({
                        "id": proposal_id(txt),
                        "sn": sn_val,
                        "title": txt,
                        "lastDate": "Open",
                        "status": status,
                        "applyUrl": url,
                        "docUrl": urljoin(url, href),
                        "source": "nbhm",
                        "sourceName": meta.get("name", "National Board for Higher Mathematics (NBHM)"),
                        "type": meta.get("type", "Project proposal"),
                        "scannedAt": now_str()
                    })
    except Exception as e:
        log.debug(f"NBHM check note: {e}")

    return proposals if proposals else scrape_generic_agency("nbhm")


def scrape_generic_agency(agency_id: str) -> list[dict]:
    """Uses verified agency seeds with HTTP 200 URLs."""
    meta = SOURCES_METADATA.get(agency_id, {})
    sn_val = str(meta.get("sn", ""))
    name = meta.get("name", agency_id.upper())
    agency_type = meta.get("type", "Project proposal")
    seeds = AGENCY_SEEDS.get(agency_id, [])

    rows = []
    for item in seeds:
        apply_url = item.get("applyUrl", meta.get("url", ""))
        doc_url = item.get("docUrl") or apply_url

        rows.append({
            "id":          proposal_id(item["title"]),
            "sn":          sn_val or item.get("sn", str(len(rows) + 1)),
            "title":       item["title"],
            "lastDate":    item.get("lastDate", "Open"),
            "status":      item.get("status", "open"),
            "applyUrl":    apply_url,
            "docUrl":      doc_url,
            "source":      agency_id,
            "sourceName":  name,
            "type":        agency_type,
            "lastModified": "",
            "scannedAt":   now_str(),
        })

    return rows


# ── Diff Engine ───────────────────────────────────────────────────────────────
def diff_proposals(old: list[dict], new: list[dict]) -> list[dict]:
    old_map = {p["id"]: p for p in old}
    new_map = {p["id"]: p for p in new}
    events = []

    for pid, prop in new_map.items():
        if pid not in old_map:
            events.append({
                "type":    "added",
                "source":  prop["source"],
                "sourceName": prop.get("sourceName", prop["source"].upper()),
                "title":   prop["title"],
                "lastDate": prop.get("lastDate", ""),
                "docUrl":  prop.get("docUrl", ""),
                "time":    now_str(),
            })
        else:
            old_p = old_map[pid]
            changes = []
            if old_p.get("lastDate") != prop.get("lastDate"):
                changes.append(f"deadline changed from '{old_p.get('lastDate')}' to '{prop.get('lastDate')}'")
            if old_p.get("status") != prop.get("status"):
                changes.append(f"status changed to '{prop.get('status')}'")

            if changes:
                events.append({
                    "type":    "updated",
                    "source":  prop["source"],
                    "sourceName": prop.get("sourceName", prop["source"].upper()),
                    "title":   prop["title"],
                    "changes": "; ".join(changes),
                    "time":    now_str(),
                })

    for pid, prop in old_map.items():
        if pid not in new_map:
            events.append({
                "type":   "removed",
                "source": prop["source"],
                "sourceName": prop.get("sourceName", prop["source"].upper()),
                "title":  prop["title"],
                "time":   now_str(),
            })

    return events


def build_notification(event: dict) -> dict:
    etype = event["type"]
    src_label = event.get("sourceName") or event["source"].upper()
    title = event["title"]

    if etype == "added":
        body = f"<strong>New proposal added</strong> on {src_label} — \"{title}\""
        if event.get("lastDate"):
            body += f". Deadline: {event['lastDate']}."
        notif_type = "new-prop"
    elif etype == "updated":
        body = f"<strong>Proposal updated</strong> on {src_label} — \"{title}\". {event.get('changes', '')}."
        notif_type = "updated"
    else:
        body = f"<strong>Proposal removed</strong> from {src_label} — \"{title}\" is no longer active."
        notif_type = "removed"

    return {
        "id":       int(datetime.now().timestamp() * 1000),
        "unread":   True,
        "type":     notif_type,
        "src":      event["source"],
        "srcName":  src_label,
        "body":     body,
        "docUrl":   event.get("docUrl", ""),
        "time":     event["time"],
    }


# ── Main Scan Cycle ───────────────────────────────────────────────────────────
def run_scan():
    log.info("=" * 60)
    log.info(f"Scan started for ICMR, DBT, and NBHM at {now_str()}")

    agency_results = {}
    all_props = []

    # 1. ICMR
    icmr_props = scrape_icmr()
    agency_results["icmr"] = icmr_props
    all_props.extend(icmr_props)

    # 2. DBT
    dbt_props = scrape_dbt()
    agency_results["dbt"] = dbt_props
    all_props.extend(dbt_props)

    # 3. NBHM
    nbhm_props = scrape_nbhm_live()
    agency_results["nbhm"] = nbhm_props
    all_props.extend(nbhm_props)

    # Non-blocking parallel header verification
    doc_urls = [p["docUrl"] for p in all_props if p.get("docUrl")]
    headers_map = check_headers_parallel(doc_urls)
    for p in all_props:
        u = p.get("docUrl", "")
        if u in headers_map:
            p["lastModified"] = headers_map[u]

    # Diff against previous snapshot
    snapshot = load_json(SNAPSHOT_FILE, [])
    events = diff_proposals(snapshot, all_props)

    # Persist updated proposals
    output_data = {
        "lastScan": now_str(),
        "totalOpen": len([p for p in all_props if p.get("status") == "open"]),
        "totalAll": len(all_props),
        "totalAgencies": len(SOURCES_METADATA),
        "agencies": SOURCES_METADATA,
        "proposals": all_props,
        "icmr": agency_results.get("icmr", []),
        "dbt": agency_results.get("dbt", []),
        "nbhm": agency_results.get("nbhm", []),
    }

    save_json(PROPOSALS_FILE, output_data)

    if events:
        log.info(f"{len(events)} change(s) detected")
        existing_notifs = load_json(NOTIF_FILE, [])
        new_notifs = [build_notification(e) for e in events]
        all_notifs = new_notifs + existing_notifs
        save_json(NOTIF_FILE, all_notifs[:100])
    else:
        log.info("No changes detected")

    save_json(SNAPSHOT_FILE, all_props)
    log.info(f"Scan complete. Total Proposals: {len(all_props)} across 3 agencies (ICMR, DBT, NBHM).")


if __name__ == "__main__":
    if "--once" in sys.argv:
        log.info("Running single scan (--once)")
        run_scan()
        sys.exit(0)

    log.info(f"R&D Proposal Monitor starting — scan every {SCAN_INTERVAL_MINUTES} min")
    run_scan()
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scan)
    log.info(f"Scheduler active. Next scan in {SCAN_INTERVAL_MINUTES} minutes.")
    while True:
        schedule.run_pending()
        time.sleep(30)
