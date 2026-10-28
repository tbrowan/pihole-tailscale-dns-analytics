#!/usr/bin/env python3
"""
Pi-hole stats dashboard.

A small Flask web app that reads the snapshots collected by pihole_stats.py
from MariaDB and serves them as JSON, plus one HTML page that charts them.

Reads the same ../.env file as the collector (DB_HOST, DB_USER, DB_PASSWORD,
DB_NAME). The database user only needs SELECT, so the dashboard can never
change your data.

Run (from ~/pihole-stats):
    venv/bin/python dashboard/app.py
Then on your Mac (local port 5001 because macOS AirPlay Receiver owns 5000):
    ssh -L 5001:127.0.0.1:5000 pi     (keep that window open)
    open http://localhost:5001
Open it through the tunnel, not VS Code Live Server: Live Server only serves
files, so every /api/... request gets a 404.
"""

import os
from datetime import datetime
from decimal import Decimal

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

# The front end is plain files in client/: index.html plus resources/styles and
# resources/scripts. Flask serves them as-is, so there is no build step.
CLIENT_DIR = os.path.join(BASE_DIR, "client")
app = Flask(__name__, static_folder=os.path.join(CLIENT_DIR, "resources"),
            static_url_path="/resources")


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run one read-only query and return the rows as a list of dicts."""
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "pihole_stats"),
    )
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        return [clean(row) for row in cur.fetchall()]
    finally:
        conn.close()


def clean(row: dict) -> dict:
    """Convert database types that JSON can't represent directly."""
    out = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def days_param() -> int:
    """Read ?days=N from the URL, kept between 1 and 90."""
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        days = 7
    return max(1, min(days, 90))


@app.route("/")
def index():
    return send_from_directory(CLIENT_DIR, "index.html")


@app.route("/api/latest")
def latest():
    # The database computes the age so the browser's clock or timezone can't skew it.
    rows = query(
        """SELECT *, TIMESTAMPDIFF(MINUTE, taken_at, NOW()) AS age_minutes
           FROM snapshots ORDER BY taken_at DESC LIMIT 1"""
    )
    if not rows:
        return jsonify({})
    # The snapshot closest to 24h before the latest (cron drifts by seconds, so
    # search +/- 1 hour). Comparing two separate 24h windows is valid; summing is not.
    prev = query(
        """SELECT s.* FROM snapshots AS s
           CROSS JOIN (SELECT MAX(taken_at) - INTERVAL 1 DAY AS target FROM snapshots) AS t
           WHERE s.taken_at BETWEEN t.target - INTERVAL 1 HOUR AND t.target + INTERVAL 1 HOUR
           ORDER BY ABS(TIMESTAMPDIFF(SECOND, s.taken_at, t.target))
           LIMIT 1"""
    )
    return jsonify({**rows[0], "day_before": prev[0] if prev else None})


@app.route("/api/history")
def history():
    rows = query(
        """SELECT taken_at, total_queries, blocked_queries,
                  percent_blocked, active_clients
           FROM snapshots
           WHERE taken_at >= NOW() - INTERVAL %s DAY
           ORDER BY taken_at""",
        (days_param(),),
    )
    return jsonify(rows)


@app.route("/api/top-blocked")
def top_blocked():
    days = days_param()
    total = query(
        "SELECT COUNT(*) AS n FROM snapshots WHERE taken_at >= NOW() - INTERVAL %s DAY",
        (days,),
    )[0]["n"]
    rows = query(
        """SELECT tb.domain,
                  COUNT(DISTINCT tb.snapshot_id) AS snapshots_seen,
                  MAX(tb.hits) AS peak_hits
           FROM top_blocked AS tb
           JOIN snapshots AS s ON s.id = tb.snapshot_id
           WHERE s.taken_at >= NOW() - INTERVAL %s DAY
           GROUP BY tb.domain
           ORDER BY snapshots_seen DESC, peak_hits DESC
           LIMIT 15""",
        (days,),
    )
    return jsonify({"total_snapshots": total, "domains": rows})


if __name__ == "__main__":
    # 127.0.0.1 = only reachable from the Pi itself. You view it from
    # your Mac through an SSH tunnel, so no firewall change is needed.
    app.run(host="127.0.0.1", port=5000)
