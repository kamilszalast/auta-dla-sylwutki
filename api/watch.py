"""The shared watch list: GET/POST /api/watch on Vercel Blob (data/watch.json). Logic: scraper/watch.py.

Vercel project environment variable WATCH_KEY: the key in the edit link (?edycja=<WATCH_KEY>)."""
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper import config, vercel_app, watch  # noqa: E402
from scraper.storage import Blob, Local  # noqa: E402


def storage(headers):
    blob = vercel_app.blob_auth(os.environ, headers)
    local = Local(ROOT / "data")
    return Blob(blob[0], local, store_id=blob[1], fallback_token=blob[2]) if blob else local


class handler(BaseHTTPRequestHandler):
    def _send(self, result):
        code, body, headers = result
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(watch.get_response(storage(self.headers), os.environ.get("WATCH_KEY"), self.headers.get("X-Watch-Key")))

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        body = self.rfile.read(min(size, watch.MAX_BODY + 1)) if size > 0 else b""
        today = datetime.now(ZoneInfo(config.TIMEZONE)).date().isoformat()
        self._send(watch.post_response(storage(self.headers), os.environ.get("WATCH_KEY"),
                                       self.headers.get("X-Watch-Key"), body, today))
