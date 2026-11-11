"""Vercel Cron -> GitHub: start the daily offers update (workflow_dispatch).

GitHub's own schedule does not fire reliably for this repo, so Vercel Cron wakes the workflow up.
The workflow itself exits without changes when today's data already exists, so extra calls are harmless.

Vercel project environment variables:
  CRON_SECRET            random string; Vercel sends it as "Authorization: Bearer <value>"
  GITHUB_DISPATCH_TOKEN  fine-grained GitHub token, this repo only, Actions: read and write
"""
import hmac
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

DISPATCH_URL = "https://api.github.com/repos/kamilszalast/auta-dla-sylwutki/actions/workflows/daily.yml/dispatches"


def authorized(header, secret):
    return bool(secret) and hmac.compare_digest((header or "").encode(), ("Bearer " + secret).encode())


def dispatch(token, opener=urllib.request.urlopen):
    """Returns GitHub's HTTP status (204 = accepted), or None when GitHub can't be reached."""
    req = urllib.request.Request(DISPATCH_URL, data=json.dumps({"ref": "main"}).encode(), method="POST", headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "auta-dla-sylwutki-cron",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with opener(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:  # URLError, connection reset, read timeout
        return None


def respond(secret, token, auth_header, opener=urllib.request.urlopen):
    """Returns (http_status, message) for one cron call."""
    if not secret or not token:
        return 500, "Brak CRON_SECRET albo GITHUB_DISPATCH_TOKEN w ustawieniach Vercela."
    if not authorized(auth_header, secret):
        return 401, "Brak dostępu."
    status = dispatch(token, opener)
    if status == 204:
        return 200, "Aktualizacja zlecona GitHubowi."
    return 502, "GitHub nie przyjął zlecenia (odpowiedź: %s)." % (status or "brak połączenia")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code, msg = respond(os.environ.get("CRON_SECRET"), os.environ.get("GITHUB_DISPATCH_TOKEN"),
                            self.headers.get("Authorization"))
        print("trigger: %s %s" % (code, msg))
        body = msg.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
