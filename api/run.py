"""Vercel Cron: one time-limited turn of the daily offers update. Logic: scraper/vercel_app.py."""
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper import config, vercel_app  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code, text = vercel_app.run_turn(os.environ.get("CRON_SECRET"), self.headers.get("Authorization"),
                                         vercel_app.blob_auth(os.environ, self.headers), ROOT,
                                         datetime.now(ZoneInfo(config.TIMEZONE)))
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
