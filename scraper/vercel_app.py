"""The scraper on Vercel: /api/run (Vercel Cron, one time-limited turn) and /api/data (JSON for the page).

Vercel project environment variables:
  CRON_SECRET  random string; Vercel Cron sends it as "Authorization: Bearer <value>"
  Blob store (public access) connected to the project: BLOB_STORE_ID with the function's OIDC token,
  or BLOB_READ_WRITE_TOKEN
"""
import contextlib
import hmac
import io
import json
import traceback

from . import config, pipeline
from .http import Fetcher
from .storage import Blob, Local, StorageError

TURN_BUDGET_S = 210  # Vercel stops a function after 300 s; leave time for one slow fetch, scoring and saving
# Crons at 6:00, 12:00 and 18:00 fire anywhere in their hour on Hobby, so real gaps are 5 h 01 min or more.
# lastSearch is the turn's start time, so 4.5 h leaves a margin; a manual call sooner only fetches pending pages.
SEARCH_EVERY_H = 4.5
DATA_NAMES = ("offers", "meta")


def authorized(header, secret):
    return bool(secret) and hmac.compare_digest((header or "").encode(), ("Bearer " + secret).encode())


def blob_auth(env, headers):
    """(token, store_id, fallback_token) for the Blob store, or None.

    OIDC (store id + token) first; a read-write token is the fallback if OIDC is rejected."""
    store_id = (env.get("BLOB_STORE_ID") or "").strip()
    if store_id.startswith("store_"):
        store_id = store_id[len("store_"):]
    oidc = (headers.get("x-vercel-oidc-token") or env.get("VERCEL_OIDC_TOKEN") or "").strip()
    rw = (env.get("BLOB_READ_WRITE_TOKEN") or "").strip() or None
    if store_id and oidc:
        return oidc, store_id, rw
    return (rw, None, None) if rw else None


def run_turn(secret, auth_header, blob, root, now, fetcher=None, run=pipeline.run):
    """One cron call; blob is blob_auth(...). Returns (http_status, log text)."""
    if not secret:
        return 500, "Brak CRON_SECRET w ustawieniach Vercela."
    if not authorized(auth_header, secret):
        return 401, "Brak dostępu."
    if not blob:
        return 500, "Brak dostępu do magazynu Blob: podłącz magazyn Blob do projektu."
    storage = Blob(blob[0], Local(root / "data"), store_id=blob[1], fallback_token=blob[2])
    fetcher = fetcher or Fetcher(backoff=(5,), timeout=20)
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            code = run(root, fetcher, now, "vercel", config.DETAIL_LIMIT, False,
                       storage=storage, budget_s=TURN_BUDGET_S, search_every_h=SEARCH_EVERY_H)
    except StorageError as e:
        print(log.getvalue() + str(e))
        return 502, (log.getvalue() + str(e)).strip()
    except Exception:  # keep the log readable in Vercel instead of a bare 500
        text = (log.getvalue() + traceback.format_exc()).strip()
        print(text)
        return 500, text
    text = log.getvalue().strip() or "OK"
    print(text)
    return (200 if code == 0 else 502), text


def data_response(name, storage):
    """Returns (http_status, body bytes, headers) for /api/data?name=offers|meta."""
    plain = {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}
    if name not in DATA_NAMES:
        return 404, b"Nie ma takiego pliku.", plain
    try:
        obj = storage.read(name + ".json", None)
    except StorageError as e:
        return 502, str(e).encode("utf-8"), plain
    if obj is None:
        return 404, b"Brak danych.", plain
    return 200, json.dumps(obj, ensure_ascii=False).encode("utf-8"), {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "public, max-age=0, s-maxage=60, stale-while-revalidate=600",
    }
