# R&D Proposal Monitor
**Real-time dashboard for ICMR & DBT call-for-proposal tracking**

---

## What this does

- Scrapes `icmr.gov.in/call-for-proposals` every **5 minutes** (configurable)
- Checks DBT proposal PDF links for server-side changes (Last-Modified header)
- Diffs new results against a stored snapshot
- Fires a notification the moment a new proposal is added, updated, or removed
- Displays everything on a live dashboard with toast alerts

---

## Project Structure

```
rd_monitor/
├── backend/
│   ├── scraper.py        ← Scrapes ICMR & DBT, writes JSON, triggers diffs
│   ├── api_server.py     ← Flask API that serves data to the dashboard
│   └── requirements.txt  ← Python dependencies
├── frontend/
│   └── dashboard.html    ← The full dashboard (opens in any browser)
├── data/                 ← Auto-created at runtime
│   ├── proposals.json    ← Current proposals from last scan
│   ├── notifications.json← Change alerts
│   ├── snapshot.json     ← Previous scan state (used for diffing)
│   ├── dbt_seed.json     ← DBT proposals seed list (auto-created)
│   └── scraper.log       ← Scan logs
└── README.md
```

---

## Setup & Running

### Automatic Quick Start (Recommended)

Run `./start.sh` from the project root. It will automatically create the Python virtual environment in `backend/venv`, install required dependencies (`flask`, `flask-cors`, `schedule`, `requests`, `beautifulsoup4`, `lxml`), and start both the scraper and API server using `setsid nohup`.

```bash
./start.sh
```

To stop all backend services:
```bash
./stop.sh
```

---

## Free API Keys & Scraping Features

- **SSL Bypass for Govt Portals**: ICMR and DBT websites use custom SSL certificates that normally cause SSL verification errors in standard Python requests. The backend bypasses SSL verification cleanly with `verify=False` and handles connection fallbacks.
- **Free API Keys Support**: No paid services or subscriptions required! Optional free tier API keys can be set via environment variables if desired:
  - `GOOGLE_SEARCH_API_KEY` & `SEARCH_ENGINE_ID`: Uses Google Custom Search JSON API free tier (100 free queries/day) for proposal discovery.
  - `SERPAPI_API_KEY`: Uses SerpAPI free tier (100 free searches/month).
  - `GEMINI_API_KEY`: Google Gemini API free tier key.
- **Automatic Fallback**: If no API keys are supplied, the scraper seamlessly defaults to free live web scraping and PDF header checking.

---

## Change the scan interval

Edit `scraper.py`, line 33:

```python
SCAN_INTERVAL_MINUTES = 5   # ← change this (5, 10, 15, 30...)
```

The dashboard's poll interval can be changed in Settings inside the UI.

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/proposals` | GET | All current proposals (ICMR + DBT) |
| `/api/notifications` | GET | All change alerts |
| `/api/notifications/read/<id>` | POST | Mark one notification read |
| `/api/notifications/read-all` | POST | Mark all read |
| `/api/scan` | POST | Trigger an immediate scan |
| `/api/status` | GET | Quick status summary |

---

## Notification types

| Type | Trigger |
|---|---|
| `new-prop` | A proposal row appears that wasn't in the previous scan |
| `updated` | An existing proposal's deadline or status changed, or its PDF changed on the server |
| `removed` | A proposal row no longer appears on the page |

---

## Note on DBT

DBT blocks automated page scraping on some routes. The scraper uses a **seed list** of known PDF URLs, checks each one's `Last-Modified` HTTP header with SSL fallback to detect updates, and performs free web discovery. To add new DBT proposals manually, edit `data/dbt_seed.json`.
