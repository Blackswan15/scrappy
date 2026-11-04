"""
Monitored Funding Agencies Configuration
========================================
Focused exclusively on:
1. Indian Council of Medical Research (ICMR)
2. Department of Biotechnology (DBT)
3. National Board for Higher Mathematics (NBHM)
"""

AGENCIES_LIST = [
    {
        "id": "icmr",
        "sn": 3,
        "agency": "ICMR",
        "name": "Indian Council of Medical Research (ICMR)",
        "category": "Medical & Health",
        "url": "https://www.icmr.gov.in/call-for-proposals",
        "type": "Project proposal",
        "active": True
    },
    {
        "id": "dbt",
        "sn": 7,
        "agency": "DBT",
        "name": "Department of Biotechnology (DBT)",
        "category": "Biotechnology",
        "url": "https://dbt.gov.in/offerings/call-for-proposals",
        "type": "Project proposal",
        "active": True
    },
    {
        "id": "nbhm",
        "sn": 40,
        "agency": "NBHM",
        "name": "National Board for Higher Mathematics (NBHM)",
        "category": "Higher Mathematics",
        "url": "https://nbhm.dae.gov.in/research.html",
        "type": "Project proposal",
        "active": True
    }
]

SOURCES_METADATA = {item["id"]: item for item in AGENCIES_LIST}
