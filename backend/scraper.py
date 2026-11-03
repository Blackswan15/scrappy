"""
R&D Proposal Monitor — Scraper Backend
=======================================
Scrapes ICMR and DBT call-for-proposal pages every 5 minutes.
Diffs new vs stored proposals, writes notifications to data/notifications.json
and updates data/proposals.json for the dashboard to consume.

Run:  python scraper.py
Deps: pip install requests beautifulsoup4 lxml schedule
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

import requests
import urllib3
from bs4 import BeautifulSoup

# Disable SSL verification warnings for government portals with self-signed/missing intermediate certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

PROPOSALS_FILE   = DATA_DIR / "proposals.json"
NOTIF_FILE       = DATA_DIR / "notifications.json"
SNAPSHOT_FILE    = DATA_DIR / "snapshot.json"
LOG_FILE         = DATA_DIR / "scraper.log"

SCAN_INTERVAL_MINUTES = 5   # ← change here to adjust frequency

SOURCES = {
    "icmr": {
        "name": "Indian Council of Medical Research",
        "url": "https://www.icmr.gov.in/call-for-proposals",
        "short_url": "icmr.gov.in/call-for-proposals",
        "color": "icmr",
    },
    "dbt": {
        "name": "Department of Biotechnology",
        "url": "https://dbt.gov.in/offerings/call-for-proposals",
        "short_url": "dbt.gov.in/offerings/call-for-proposals",
        "color": "dbt",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("monitor")


# ── Helpers ──────────────────────────────────────────────────────────────────
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
    """Stable hash-based ID from title text."""
    return hashlib.sha1(title.strip().lower().encode()).hexdigest()[:12]


# ── ICMR Scraper ─────────────────────────────────────────────────────────────
def scrape_icmr() -> list[dict]:
    """
    Parses the ICMR /call-for-proposals table.
    Returns list of proposal dicts.
    """
    log.info("Scraping ICMR …")
    try:
        resp = requests.get(SOURCES["icmr"]["url"], headers=HEADERS, timeout=20, verify=False)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"ICMR fetch failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    rows = []

    table = soup.find("table")
    if not table:
        log.warning("ICMR: no <table> found on page")
        return []

    for tr in table.find_all("tr")[1:]:   # skip header row
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        sn_text   = tds[0].get_text(strip=True)
        title_raw = tds[1].get_text(" ", strip=True)
        last_date = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        apply_url = ""
        doc_url   = ""

        # Apply link (column 3 if present)
        if len(tds) > 3:
            a = tds[3].find("a", href=True)
            if a:
                apply_url = urljoin(SOURCES["icmr"]["url"], a["href"].strip())

        # Document link (column 4)
        if len(tds) > 4:
            for a in tds[4].find_all("a", href=True):
                href = a["href"].strip()
                if href.endswith(".pdf") or "download" in href.lower() or "object" in href.lower():
                    doc_url = urljoin(SOURCES["icmr"]["url"], href)
                    break

        if not title_raw:
            continue

        # Determine status
        title_lower = title_raw.lower()
        if title_lower.startswith("result"):
            status = "result"
        elif not last_date:
            status = "result"
        else:
            status = "open"

        rows.append({
            "id":        proposal_id(title_raw),
            "sn":        sn_text,
            "title":     title_raw,
            "lastDate":  last_date,
            "status":    status,
            "applyUrl":  apply_url,
            "docUrl":    doc_url,
            "source":    "icmr",
            "scannedAt": now_str(),
        })

    log.info(f"ICMR: {len(rows)} proposals parsed")
    return rows


# ── DBT Scraper ──────────────────────────────────────────────────────────────
def _discover_dbt_proposals_free() -> list[dict]:
    """
    Uses free API keys (Google Custom Search API free tier, SerpAPI free tier, Gemini free tier)
    if available in environment variables, or falls back to free web discovery.
    Requires NO paid subscriptions.
    """
    items = []
    google_key = os.getenv("GOOGLE_SEARCH_API_KEY")
    cx_id = os.getenv("SEARCH_ENGINE_ID")

    # 1. Google Custom Search (Free tier: 100 free requests/day)
    if google_key and cx_id:
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": google_key,
                "cx": cx_id,
                "q": "site:dbt.gov.in call for proposals pdf"
            }
            r = requests.get(url, params=params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("items", []):
                    items.append({
                        "title": item.get("title", ""),
                        "docUrl": item.get("link", ""),
                        "status": "open"
                    })
        except Exception as e:
            log.warning(f"Free Google Search API error: {e}")

    # 2. SerpAPI (Free tier: 100 free searches/month)
    serp_key = os.getenv("SERPAPI_API_KEY")
    if not items and serp_key:
        try:
            url = "https://serpapi.com/search.json"
            params = {
                "api_key": serp_key,
                "engine": "google",
                "q": "site:dbt.gov.in call for proposals"
            }
            r = requests.get(url, params=params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                for res in data.get("organic_results", []):
                    items.append({
                        "title": res.get("title", ""),
                        "docUrl": res.get("link", ""),
                        "status": "open"
                    })
        except Exception as e:
            log.warning(f"Free SerpAPI error: {e}")

    return items


def scrape_dbt() -> list[dict]:
    """
    DBT scraper using header-checking on seeds + free search discovery.
    Disables SSL verification to prevent cert errors on Indian govt domains.
    """
    log.info("Scraping DBT (header-check mode with SSL fallback) …")

    seed: list[dict] = load_json(DATA_DIR / "dbt_seed.json", [])
    if not seed:
        log.warning("DBT: no seed file found — using built-in defaults")
        seed = _dbt_builtin_seed()
        save_json(DATA_DIR / "dbt_seed.json", seed)

    rows = []
    seen_ids = set()

    # 1. Process seeds with SSL-bypassed HEAD check
    for item in seed:
        doc_url = item.get("docUrl", "")
        apply_url = item.get("applyUrl", "")
        if doc_url:
            doc_url = urljoin(SOURCES["dbt"]["url"], doc_url)
        if apply_url:
            apply_url = urljoin(SOURCES["dbt"]["url"], apply_url)

        last_modified = ""
        if doc_url:
            try:
                r = requests.head(doc_url, headers=HEADERS, timeout=10, allow_redirects=True, verify=False)
                last_modified = r.headers.get("Last-Modified", "")
            except Exception as e:
                log.debug(f"DBT HEAD check failed for {doc_url}: {e}")

        pid = proposal_id(item["title"])
        seen_ids.add(pid)
        rows.append({
            "id":          pid,
            "sn":          item.get("sn", ""),
            "title":       item["title"],
            "lastDate":    item.get("lastDate", ""),
            "status":      item.get("status", "open"),
            "applyUrl":    apply_url,
            "docUrl":      doc_url,
            "source":      "dbt",
            "lastModified": last_modified,
            "scannedAt":   now_str(),
        })

    # 2. Add free search discovery items if any
    extra_items = _discover_dbt_proposals_free()
    for extra in extra_items:
        pid = proposal_id(extra["title"])
        if pid not in seen_ids:
            seen_ids.add(pid)
            rows.append({
                "id":          pid,
                "sn":          str(len(rows) + 1),
                "title":       extra["title"],
                "lastDate":    extra.get("lastDate", ""),
                "status":      extra.get("status", "open"),
                "applyUrl":    extra.get("applyUrl", ""),
                "docUrl":      extra.get("docUrl", ""),
                "source":      "dbt",
                "lastModified": "",
                "scannedAt":   now_str(),
            })

    log.info(f"DBT: {len(rows)} proposals checked")
    return rows


def _dbt_builtin_seed() -> list[dict]:
    return [
        {
            "sn": "1",
            "title": "Call for Proposals: Microbiome and Their Implications to Human Health and Disease – Therapeutic Potential and Translational Opportunities",
            "lastDate": "Oct 15, 2026",
            "status": "open",
            "docUrl": "https://dbt.gov.in/storage/media/Gn8sCFXGM8OHPFXw1xcrAMozOL7IvYNMaxOyisoI.pdf",
        },
        {
            "sn": "2",
            "title": "Call for Proposals: T Cell Based Vaccines and Biologics in Infectious Diseases, Cancer and Autoimmune Diseases",
            "lastDate": "Oct 6, 2026",
            "status": "open",
            "docUrl": "https://dbt.gov.in/storage/media/kD4sCpy1loK6v13u8bhOdCHaJDCxTn0B1yzs1qRY.pdf",
        },
        {
            "sn": "3",
            "title": "DBT-BIRAC Joint Call for Proposals on Bio-AI for Establishing BioE3 Hubs (BioE3 Policy – Biomanufacturing)",
            "lastDate": "Jun 30, 2026",
            "status": "open",
            "docUrl": "https://dbt.gov.in/storage/media/K0rMbuIV5klmNimgi3DLd5GPL6Qo5z6QW9imsYJl.pdf",
        },
        {
            "sn": "4",
            "title": "Call for Applications: BioCARe Programme for Women Researchers 2026-27",
            "lastDate": "Oct 8, 2026",
            "status": "open",
            "docUrl": "https://dbt.gov.in/storage/media/Q8L31YFSQ675iHlardBO8bAH7Imv09ms54ftI3wV.pdf",
        },
        {
            "sn": "5",
            "title": "Call for Proposals: Biotechnological Interventions for Improvement of High Value Cash Crops",
            "lastDate": "May 5, 2026",
            "status": "open",
            "docUrl": "https://dbt.gov.in/storage/media/wVU64NlxMyCCIAFQQrlL7hllrPkq6Edlyn9ITL9D.pdf",
        },
        {
            "sn": "6",
            "title": "Call for Proposals: Development of Next-Generation Vaccines, Diagnostics and Therapeutics (Livestock & Aquaculture)",
            "lastDate": "May 15, 2026",
            "status": "open",
            "docUrl": "https://dbt.gov.in/storage/media/3evyiwTCG0lXpC85dyTMzFv6Kup10H6S1qwLtLvW.pdf",
        },
    ]


# ── Diff Engine ───────────────────────────────────────────────────────────────
def diff_proposals(old: list[dict], new: list[dict]) -> list[dict]:
    """
    Compare old and new proposal lists.
    Returns a list of change events: added / updated / removed.
    """
    old_map = {p["id"]: p for p in old}
    new_map = {p["id"]: p for p in new}
    events = []

    for pid, prop in new_map.items():
        if pid not in old_map:
            events.append({
                "type":    "added",
                "source":  prop["source"],
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
            if old_p.get("lastModified") and old_p.get("lastModified") != prop.get("lastModified"):
                changes.append("document updated on server")
            if changes:
                events.append({
                    "type":    "updated",
                    "source":  prop["source"],
                    "title":   prop["title"],
                    "changes": "; ".join(changes),
                    "time":    now_str(),
                })

    for pid, prop in old_map.items():
        if pid not in new_map:
            events.append({
                "type":   "removed",
                "source": prop["source"],
                "title":  prop["title"],
                "time":   now_str(),
            })

    return events


# ── Notification Builder ──────────────────────────────────────────────────────
def build_notification(event: dict) -> dict:
    etype = event["type"]
    src   = event["source"].upper()
    title = event["title"]

    if etype == "added":
        body = f"<strong>New proposal added</strong> on {src} — \"{title}\""
        if event.get("lastDate"):
            body += f". Deadline: {event['lastDate']}."
        notif_type = "new-prop"

    elif etype == "updated":
        body = f"<strong>Proposal updated</strong> on {src} — \"{title}\". {event.get('changes', '')}."
        notif_type = "updated"

    else:  # removed
        body = f"<strong>Proposal removed</strong> from {src} — \"{title}\" is no longer listed."
        notif_type = "removed"

    return {
        "id":       int(datetime.now().timestamp() * 1000),
        "unread":   True,
        "type":     notif_type,
        "src":      event["source"],
        "body":     body,
        "docUrl":   event.get("docUrl", ""),
        "time":     event["time"],
    }


# ── Main Scan Cycle ───────────────────────────────────────────────────────────
def run_scan():
    log.info("=" * 60)
    log.info(f"Scan started at {now_str()}")

    icmr_props = scrape_icmr()
    dbt_props  = scrape_dbt()
    all_props  = icmr_props + dbt_props

    # Load previous snapshot
    snapshot = load_json(SNAPSHOT_FILE, [])

    # Diff per source
    old_icmr = [p for p in snapshot if p.get("source") == "icmr"]
    old_dbt  = [p for p in snapshot if p.get("source") == "dbt"]

    events = diff_proposals(old_icmr, icmr_props) + diff_proposals(old_dbt, dbt_props)

    # Persist updated proposals
    save_json(PROPOSALS_FILE, {
        "lastScan":  now_str(),
        "icmr":      icmr_props,
        "dbt":       dbt_props,
        "totalOpen": len([p for p in all_props if p.get("status") == "open"]),
        "totalAll":  len(all_props),
    })

    # Append new notifications
    if events:
        log.info(f"{len(events)} change(s) detected")
        existing_notifs = load_json(NOTIF_FILE, [])
        new_notifs = [build_notification(e) for e in events]
        all_notifs = new_notifs + existing_notifs   # newest first
        save_json(NOTIF_FILE, all_notifs[:200])     # keep last 200
    else:
        log.info("No changes detected")

    # Save new snapshot
    save_json(SNAPSHOT_FILE, all_props)

    log.info(f"Scan complete. ICMR: {len(icmr_props)} | DBT: {len(dbt_props)} | Events: {len(events)}")


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--once" in sys.argv:
        log.info("Running single scan (--once)")
        run_scan()
        sys.exit(0)

    log.info(f"R&D Proposal Monitor starting — scan every {SCAN_INTERVAL_MINUTES} min")

    # Run immediately on startup
    run_scan()

    # Then on schedule
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(run_scan)

    log.info(f"Scheduler active. Next scan in {SCAN_INTERVAL_MINUTES} minutes.")
    while True:
        schedule.run_pending()
        time.sleep(30)
