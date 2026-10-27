#!/usr/bin/env python3
"""
Collects Pi-hole v6 statistics from its REST API and stores them in MySQL/MariaDB.

Config comes from a .env file in the same folder:
    PIHOLE_URL=http://127.0.0.1
    PIHOLE_APP_PASSWORD=...   (Pi-hole Settings > Web interface / API > app password)
    DB_HOST=localhost
    DB_USER=pistats
    DB_PASSWORD=...
    DB_NAME=pihole_stats

Install deps (inside a venv):  pip install requests mysql-connector-python python-dotenv
"""

import logging
import os
import sys

import mysql.connector
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

PIHOLE_URL = os.getenv("PIHOLE_URL", "http://127.0.0.1").rstrip("/")
TOP_N = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pihole_stats")


def login(session: requests.Session) -> str:
    """Authenticate with Pi-hole and return a session ID."""
    r = session.post(f"{PIHOLE_URL}/api/auth",
                     json={"password": os.environ["PIHOLE_APP_PASSWORD"]}, timeout=10)
    r.raise_for_status()
    auth = r.json()["session"]
    if not auth.get("valid"):
        raise RuntimeError("Pi-hole rejected the password")
    return auth["sid"]


def logout(session: requests.Session, sid: str) -> None:
    """Release the API session so we don't use up Pi-hole's session slots."""
    try:
        session.delete(f"{PIHOLE_URL}/api/auth", headers={"X-FTL-SID": sid}, timeout=10)
    except requests.RequestException:
        log.warning("Logout failed; session will expire on its own")


def fetch_stats(session: requests.Session, sid: str) -> tuple[dict, list]:
    headers = {"X-FTL-SID": sid}
    summary = session.get(f"{PIHOLE_URL}/api/stats/summary",
                          headers=headers, timeout=10)
    summary.raise_for_status()
    top = session.get(f"{PIHOLE_URL}/api/stats/top_domains",
                      params={"blocked": "true", "count": TOP_N},
                      headers=headers, timeout=10)
    top.raise_for_status()
    return summary.json(), top.json().get("domains", [])


def save(summary: dict, top_domains: list) -> int:
    q = summary["queries"]
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "pihole_stats"),
    )
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO snapshots
               (total_queries, blocked_queries, percent_blocked,
                unique_domains, active_clients, gravity_domains)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (q["total"], q["blocked"], round(q["percent_blocked"], 2),
             q["unique_domains"], summary["clients"]["active"],
             summary["gravity"]["domains_being_blocked"]),
        )
        snapshot_id = cur.lastrowid
        cur.executemany(
            "INSERT INTO top_blocked (snapshot_id, domain, hits) VALUES (%s, %s, %s)",
            [(snapshot_id, d["domain"], d["count"]) for d in top_domains],
        )
        conn.commit()
        return snapshot_id
    finally:
        conn.close()


def main() -> int:
    with requests.Session() as s:
        try:
            sid = login(s)
        except Exception as e:
            log.error("Login failed: %s", e)
            return 1
        try:
            summary, top = fetch_stats(s, sid)
        except Exception as e:
            log.error("Fetching stats failed: %s", e)
            return 1
        finally:
            logout(s, sid)

    try:
        snap = save(summary, top)
    except mysql.connector.Error as e:
        log.error("Database write failed: %s", e)
        return 1

    log.info("Snapshot %s saved: %s queries, %.1f%% blocked",
             snap, summary["queries"]["total"], summary["queries"]["percent_blocked"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
