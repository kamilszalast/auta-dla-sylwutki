"""The page's data: /api/data?name=offers|meta from Vercel Blob (or the copy in the deployment before the first run)."""
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper import vercel_app  # noqa: E402
from scraper.storage import Blob, Local  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        name = parse_qs(urlparse(self.path).query).get("name", [None])[0]
        blob = vercel_app.blob_auth(os.environ, self.headers)
        local = Local(ROOT / "data")
        code, body, headers = vercel_app.data_response(name, Blob(blob[0], local, store_id=blob[1], fallback_token=blob[2]) if blob else local)
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
