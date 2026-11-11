import io
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path

from scraper import storage

TOKEN = "vercel_blob_rw_Store123_secretpart"


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, error_code):
    body = json.dumps({"error": {"code": error_code, "message": "x"}}).encode()
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(body))


class Opener:
    """Answers Blob API calls by method and URL; records every request."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        for (method, prefix), answer in self.routes.items():
            if req.get_method() == method and req.full_url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return Resp(answer)
        raise AssertionError("unexpected request %s %s" % (req.get_method(), req.full_url))


class LocalTest(unittest.TestCase):
    def test_roundtrip_and_default(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        s = storage.Local(d)
        self.assertEqual(s.read("meta.json", {}), {})
        s.write("meta.json", {"a": "zł"})
        self.assertEqual(s.read("meta.json", None), {"a": "zł"})
        self.assertIn("zł", (d / "meta.json").read_text())


class MemoryFallback:
    def __init__(self, files):
        self.files = files

    def read(self, name, default):
        return self.files.get(name, default)


class BlobTest(unittest.TestCase):
    def test_read_looks_up_url_then_downloads_fresh_copy(self):
        opener = Opener({
            ("GET", "https://vercel.com/api/blob/?url=data%2Fmeta.json"): json.dumps(
                {"url": "https://store123.public.blob.vercel-storage.com/data/meta.json"}).encode(),
            ("GET", "https://store123.public.blob.vercel-storage.com/data/meta.json"): b'{"lastRun": "x"}',
        })
        s = storage.Blob(TOKEN, MemoryFallback({}), opener=opener, now=lambda: 1234)
        self.assertEqual(s.read("meta.json", {}), {"lastRun": "x"})
        api, download = opener.requests
        self.assertEqual(api.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(api.get_header("X-api-version"), "12")
        self.assertTrue(download.full_url.endswith("meta.json?v=1234"))  # skip the CDN's cached copy
        self.assertIsNone(download.get_header("Authorization"))  # never send the token to the CDN

    def test_oidc_auth_sends_store_id(self):
        opener = Opener({("PUT", "https://vercel.com/api/blob/"): b'{"url": "u"}'})
        storage.Blob("oidc-token", MemoryFallback({}), store_id="abc123", opener=opener).write("meta.json", {})
        req = opener.requests[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer oidc-token")
        self.assertEqual(req.get_header("X-vercel-blob-store-id"), "abc123")

    def test_rejected_oidc_retries_once_with_read_write_token(self):
        answers = [http_error(403, "forbidden"), b'{"url": "u"}']
        seen = []

        def opener(req, timeout=None):
            seen.append(req)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return Resp(answer)
        s = storage.Blob("oidc", MemoryFallback({}), store_id="abc", fallback_token="vercel_blob_rw_abc_x", opener=opener)
        s.write("meta.json", {})
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1].get_header("Authorization"), "Bearer vercel_blob_rw_abc_x")
        self.assertIsNone(seen[1].get_header("X-vercel-blob-store-id"))

        opener = Opener({("GET", "https://vercel.com/api/blob/"): http_error(404, "not_found")})
        s = storage.Blob(TOKEN, MemoryFallback({"offers.json": [1, 2]}), opener=opener)
        self.assertEqual(s.read("offers.json", []), [1, 2])

    def test_other_blob_errors_are_raised(self):
        opener = Opener({("GET", "https://vercel.com/api/blob/"): http_error(403, "forbidden")})
        s = storage.Blob(TOKEN, MemoryFallback({"offers.json": [1]}), opener=opener)
        with self.assertRaises(storage.StorageError):
            s.read("offers.json", [])

    def test_write_puts_json_at_fixed_path_with_short_cache(self):
        opener = Opener({("PUT", "https://vercel.com/api/blob/"): b'{"url": "u"}'})
        storage.Blob(TOKEN, MemoryFallback({}), opener=opener).write("offers.json", [{"name": "Opel Adam"}])
        req = opener.requests[0]
        self.assertEqual(req.full_url, "https://vercel.com/api/blob/?pathname=data%2Foffers.json")
        self.assertEqual(json.loads(req.data.decode()), [{"name": "Opel Adam"}])
        self.assertEqual(req.get_header("X-add-random-suffix"), "0")
        self.assertEqual(req.get_header("X-allow-overwrite"), "1")
        self.assertEqual(req.get_header("X-cache-control-max-age"), "60")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + TOKEN)

    def test_write_failure_is_raised(self):
        opener = Opener({("PUT", "https://vercel.com/api/blob/"): http_error(503, "service_unavailable")})
        with self.assertRaises(storage.StorageError):
            storage.Blob(TOKEN, MemoryFallback({}), opener=opener).write("meta.json", {})


if __name__ == "__main__":
    unittest.main()
