"""The shared watch list ("Obserwowane") behind /api/watch.

One list for everyone who opened the page through the edit link (?edycja=<WATCH_KEY>). Anyone with the
page link can read it; changing it needs the key in the X-Watch-Key header. Each entry keeps a copy of the
car (name, year, city, price on the day it was added, link), so the page can still show it after the
listing disappears from offers.json.

Stored in Vercel Blob as data/watch.json: {"items": [...]}.
"""
import hmac
import json
from urllib.parse import urlsplit

from .storage import StorageError

FILE = "watch.json"
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


def _items(storage):
    data = storage.read(FILE, None) or {}
    items = data.get("items") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict) and i.get("id")] if isinstance(items, list) else []


def get_response(storage, key, given):
    """(status, body, headers) for GET /api/watch."""
    try:
        items = _items(storage)
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
        items = apply(_items(storage), req, today)
        storage.write(FILE, {"items": items})
    except (ValueError, UnicodeDecodeError):
        return _json(400, {"error": "Zły JSON."})
    except WatchError as e:
        return _json(e.code, {"error": str(e)})
    except (StorageError, OSError) as e:
        return _json(502, {"error": str(e)})
    return _json(200, {"items": items, "canEdit": True})
