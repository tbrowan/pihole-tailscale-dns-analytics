"""Tests for app.py using fake data, so no MariaDB is needed.

Run (from the project folder):  venv/bin/python -m unittest dashboard/test_app.py
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

LATEST = {"taken_at": "2026-10-28T10:00:00", "total_queries": 5000, "age_minutes": 15}
DAY_BEFORE = {"taken_at": "2026-10-27T10:00:00", "total_queries": 4000}


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_serves_client_files(self):
        for path in ("/", "/resources/styles/main.css", "/resources/scripts/app.js"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            r.close()

    def test_latest_includes_day_before(self):
        with patch.object(app, "query", side_effect=[[LATEST], [DAY_BEFORE]]):
            data = self.client.get("/api/latest").get_json()
        self.assertEqual(data["total_queries"], 5000)
        self.assertEqual(data["day_before"], DAY_BEFORE)

    def test_latest_without_day_before(self):
        with patch.object(app, "query", side_effect=[[LATEST], []]):
            self.assertIsNone(self.client.get("/api/latest").get_json()["day_before"])

    def test_latest_empty_database(self):
        with patch.object(app, "query", return_value=[]):
            self.assertEqual(self.client.get("/api/latest").get_json(), {})

    def test_days_param_is_clamped(self):
        for raw, expected in (("0", 1), ("500", 90), ("abc", 7), ("30", 30)):
            with patch.object(app, "query", return_value=[]) as q:
                self.client.get(f"/api/history?days={raw}")
            self.assertEqual(q.call_args.args[1], (expected,), raw)


if __name__ == "__main__":
    unittest.main()
