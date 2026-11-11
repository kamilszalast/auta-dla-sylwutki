"""The files Vercel loads from api/, served by a real local HTTP server (no Otomoto, no Blob)."""
import http.server
import importlib.util
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

API = Path(__file__).resolve().parent.parent / "api"


def load(name):
    spec = importlib.util.spec_from_file_location("api_" + name, API / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get(handler_cls, path, env, headers=None):
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (server.server_port, path), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)
    finally:
        server.shutdown()
        server.server_close()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class RunHandlerTest(unittest.TestCase):
    def test_without_secret_answers_500_and_runs_nothing(self):
        code, body, _ = get(load("run").handler, "/api/run", {"CRON_SECRET": "", "BLOB_READ_WRITE_TOKEN": ""})
        self.assertEqual(code, 500)
        self.assertIn("CRON_SECRET", body)

    def test_wrong_secret_answers_401(self):
        code, _, _ = get(load("run").handler, "/api/run", {"CRON_SECRET": "s3cret", "BLOB_READ_WRITE_TOKEN": "t"},
                         {"Authorization": "Bearer nope"})
        self.assertEqual(code, 401)


class DataHandlerTest(unittest.TestCase):
    def test_without_blob_serves_the_bundled_meta(self):
        code, body, headers = get(load("data").handler, "/api/data?name=meta", {"BLOB_READ_WRITE_TOKEN": ""})
        self.assertEqual(code, 200)
        self.assertIn("lastRun", json.loads(body))
        self.assertIn("application/json", headers["Content-Type"])

    def test_unknown_name_is_404(self):
        code, _, _ = get(load("data").handler, "/api/data?name=overrides", {"BLOB_READ_WRITE_TOKEN": ""})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
