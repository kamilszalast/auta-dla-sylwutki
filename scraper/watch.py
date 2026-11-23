"""The shared watch list ("Obserwowane") behind /api/watch.

One list for everyone who opened the page through the edit link (?edycja=<WATCH_KEY>). Anyone with the
page link can read it; changing it needs the key in the X-Watch-Key header. Each entry keeps a copy of the
car (name, year, city, price on the day it was added, link), so the page can still show it after the
listing disappears from offers.json.

In Vercel Blob each version of the list gets its own path, data/watch/v/<version>.json = {"items": [...]}, never
overwritten; data/watch.json points at the current one through its content type ("...; version=<version>").
Vercel's CDN keeps an overwritten blob for up to a minute, also with a query string in the URL, so reading the
list right after a write gave the old one and the next write lost the change. The pointer is read through the
Blob API (head, no CDN) and the CDN has never seen a new version's path. Reading costs two simple operations,
a change two advanced ones (Hobby: 2,000 a month). Locally (no Blob) the list is one file, data/watch.json,
and a pointer without a version (that older format) is read as the list itself.
"""
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from .storage import StorageError

FILE = "watch.json"
VERSIONS = "watch/v/"
MAX_ITEMS = 300
MAX_BODY = 64 * 1024
HOSTS = ("otomoto.pl", "olx.pl")
TEXT = {"id": 120, "name": 120, "city": 80}


class WatchError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def can_edit(given, key):
    return bool(key) and bool(given) and hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8"))


def _text(raw, name, required):
    v = raw.get(name)
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > TEXT[name]:
        raise WatchError(400, "Złe pole: " + name)
    return v.strip()


def _int(raw, name, low, high):
    v = raw.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
        raise WatchError(400, "Złe pole: " + name)
    return v


def _url(v):
    if not isinstance(v, str) or len(v) > 500:
        raise WatchError(400, "Zły link")
    parts = urlsplit(v)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not any(host == h or host.endswith("." + h) for h in HOSTS):
        raise WatchError(400, "Zły link")
    return v


def clean_item(raw):
    """The fields the page sends, checked; anything else is dropped."""
    if not isinstance(raw, dict):
        raise WatchError(400, "Zła pozycja")
    item = {"id": _text(raw, "id", True), "name": _text(raw, "name", True), "url": _url(raw.get("url"))}
    year, city, price = _int(raw, "year", 1950, 2100), _text(raw, "city", False), _int(raw, "price", 0, 10_000_000)
    for k, v in (("year", year), ("city", city), ("price", price)):
        if v is not None:
            item[k] = v
    return item


def apply(items, req, today):
    """New list after one change. today: YYYY-MM-DD in Warsaw, saved as the day the car was added."""
    if not isinstance(req, dict):
        raise WatchError(400, "Zła zmiana")
    op = req.get("op")
    if op == "remove":
        wid = req.get("id")
        if not isinstance(wid, str):
            raise WatchError(400, "Złe pole: id")
        return [i for i in items if i.get("id") != wid]
    if op == "add":
        new = [clean_item(req.get("item"))]
    elif op == "import":
        raw = req.get("items")
        if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
            raise WatchError(400, "Złe pole: items")
        new = []
        for r in raw:  # one bad car must not block moving the others
            try:
                new.append(clean_item(r))
            except WatchError:
                pass
    else:
        raise WatchError(400, "Nieznana zmiana")
    out, seen = list(items), {i.get("id") for i in items}
    for item in new:
        if item["id"] in seen:
            continue  # already watched: keep the price from the day it was first added
        if len(out) >= MAX_ITEMS:
            raise WatchError(409, "Lista obserwowanych jest pełna")
        item["added"] = today
        out.append(item)
        seen.add(item["id"])
    return out


def _json(code, obj):
    return code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), {
        "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}


def _clean_list(data):
    items = data.get("items") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict) and i.get("id")] if isinstance(items, list) else []


def read_items(storage):
    """(items, version); version is None on a new store and for the local file."""
    if not hasattr(storage, "head"):
        return _clean_list(storage.read(FILE, None)), None
    for _ in range(3):
        info = storage.head(FILE)
        if info is None:
            return [], None  # nobody has added anything yet
        m = re.search(r"version=([\w-]+)", info.get("contentType") or "")
        if not m:
            data = storage.read(FILE, None)  # the older one-file format: the list itself
            if not isinstance(data, dict) or "items" not in data:
                raise StorageError("Blob: nie rozpoznaję pliku listy obserwowanych")
            return _clean_list(data), None
        url = info.get("url") or ""
        if not url.endswith("/" + FILE):
            raise StorageError("Blob: brak adresu listy obserwowanych")
        data = storage.fetch(url[:-len(FILE)] + VERSIONS + m.group(1) + ".json")
        if data is not None:
            return _clean_list(data), m.group(1)
        # None: another change has just replaced that version, so read the pointer again
    raise StorageError("Blob: lista obserwowanych zmienia się za szybko")


def write_items(storage, items, prev):
    """A new version, then the pointer to it; the version before goes (deleting is free)."""
    if not hasattr(storage, "head"):
        storage.write(FILE, {"items": items})
        return
    ver = "%d-%s" % (time.time() * 1000, secrets.token_hex(3))
    storage.write(VERSIONS + ver + ".json", {"items": items})
    storage.write(FILE, {"version": ver}, content_type="application/json; charset=utf-8; version=" + ver)
    if prev:
        try:
            storage.delete([VERSIONS + prev + ".json"])
        except StorageError:
            pass  # an old version stays behind; nothing reads it


def get_response(storage, key, given):
    """(status, body, headers) for GET /api/watch."""
    try:
        items = read_items(storage)[0]
    except StorageError as e:
        return _json(502, {"error": str(e)})
    # keySet: without WATCH_KEY on the server nobody can edit, but the page keeps its key for when it is set again
    return _json(200, {"items": items, "canEdit": can_edit(given, key), "keySet": bool(key)})


def post_response(storage, key, given, body, today):
    """(status, body, headers) for POST /api/watch with {"op": "add"|"remove"|"import", ...}."""
    if not key:
        return _json(500, {"error": "Brak WATCH_KEY w ustawieniach Vercela."})
    if not can_edit(given, key):
        return _json(403, {"error": "Brak dostępu do edycji."})
    if len(body) > MAX_BODY:
        return _json(413, {"error": "Za dużo danych."})
    try:
        req = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _json(400, {"error": "Zły JSON."})
    try:
        current, ver = read_items(storage)
        items = apply(current, req, today)
        if items != current:  # e.g. the same car again: no write, writes count against the Blob limit
            write_items(storage, items, ver)
    except WatchError as e:
        return _json(e.code, {"error": str(e)})
    except (StorageError, OSError) as e:
        return _json(502, {"error": str(e)})
    return _json(200, {"items": items, "canEdit": True})
