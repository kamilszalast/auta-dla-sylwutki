"""Where offers.json and meta.json live: data/ on disk, or Vercel Blob on Vercel."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import store

BLOB_API = "https://vercel.com/api/blob/"
BLOB_API_VERSION = "12"


class StorageError(Exception):
    pass


class Local:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def read(self, name, default):
        return store.load(self.data_dir / name, default)

    def write(self, name, obj):
        store.save_json(self.data_dir / name, obj)


class Blob:
    """Vercel Blob store with public access. Files sit at fixed paths (data/<name>) and are overwritten
    (the watch list keeps each version under its own path instead; see scraper/watch.py).

    Auth: a read-write token, or a Vercel OIDC token together with the store id.
    The first read on a fresh store falls back to the copy bundled with the deployment.
    """

    def __init__(self, token, fallback, store_id=None, fallback_token=None, prefix="data/",
                 opener=urllib.request.urlopen, now=time.time):
        self.token, self.fallback, self.store_id, self.fallback_token = token, fallback, store_id, fallback_token
        self.prefix, self.opener, self.now = prefix, opener, now

    def _api(self, method, params, body=None, headers=None, path=""):
        try:
            return self._call(self.token, self.store_id, method, params, body, headers, path)
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403) or not (self.store_id and self.fallback_token):
                raise
            # OIDC rejected: use the read-write token from now on
            self.token, self.store_id = self.fallback_token, None
            return self._call(self.token, None, method, params, body, headers, path)

    def _call(self, token, store_id, method, params, body, headers, path=""):
        base = {"Authorization": "Bearer " + token, "X-Api-Version": BLOB_API_VERSION}
        if store_id:
            base["X-Vercel-Blob-Store-Id"] = store_id  # an OIDC token does not carry the store id
        req = urllib.request.Request(BLOB_API + path + "?" + urllib.parse.urlencode(params), data=body, method=method,
                                     headers=dict(base, **(headers or {})))
        with self.opener(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw) if raw.strip() else {}
            except ValueError:
                raise StorageError("Blob: API odpowiedziało nie-JSON-em (%s)" % method)

    def head(self, name):
        """Metadata from the Blob API (not the CDN, so fresh right after a write), or None if there is no such file."""
        try:
            return self._api("GET", {"url": self.prefix + name})
        except urllib.error.HTTPError as e:
            code = _error_code(e)
            if e.code == 404 or code == "not_found":
                return None
            raise StorageError("Blob: odczyt %s nie udał się (HTTP %d, %s)" % (name, e.code, code))
        except OSError as e:
            raise StorageError("Blob: odczyt %s nie udał się (%s)" % (name, e))

    def fetch(self, url):
        """A blob by its public URL, or None if it is not there (e.g. deleted a moment ago)."""
        try:
            with self.opener(urllib.request.Request(url), timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise StorageError("Blob: pobranie nie udało się (HTTP %d)" % e.code)
        except (OSError, ValueError) as e:
            raise StorageError("Blob: pobranie nie udało się (%s)" % e)

    def delete(self, names):
        body = json.dumps({"urls": [self.prefix + n for n in names]}).encode("utf-8")
        try:
            self._api("POST", {}, body, {"Content-Type": "application/json"}, path="delete")
        except OSError as e:
            raise StorageError("Blob: usunięcie nie udało się (%s)" % e)

    def read(self, name, default):
        try:
            info = self._api("GET", {"url": self.prefix + name})
        except urllib.error.HTTPError as e:
            code = _error_code(e)
            if e.code == 404 or code == "not_found":
                return self.fallback.read(name, default)
            raise StorageError("Blob: odczyt %s nie udał się (HTTP %d, %s)" % (name, e.code, code))
        except OSError as e:
            raise StorageError("Blob: odczyt %s nie udał się (%s)" % (name, e))
        try:
            req = urllib.request.Request("%s?v=%d" % (info["url"], self.now() * 1000))  # skip the CDN's cached copy (ms: two reads in one second must not share it)
            with self.opener(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError, KeyError) as e:
            raise StorageError("Blob: pobranie %s nie udało się (%s)" % (name, e))

    def write(self, name, obj, content_type="application/json; charset=utf-8"):
        body = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        try:
            self._api("PUT", {"pathname": self.prefix + name}, body, {
                "X-Add-Random-Suffix": "0", "X-Allow-Overwrite": "1", "X-Cache-Control-Max-Age": "60",
                "X-Content-Type": content_type})
        except urllib.error.HTTPError as e:
            raise StorageError("Blob: zapis %s nie udał się (HTTP %d, %s)" % (name, e.code, _error_code(e)))
        except OSError as e:
            raise StorageError("Blob: zapis %s nie udał się (%s)" % (name, e))


def _error_code(err):
    try:
        return (json.loads(err.read().decode("utf-8")).get("error") or {}).get("code")
    except (ValueError, AttributeError, OSError):
        return None
