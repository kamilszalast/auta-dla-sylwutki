"""api/trigger.py: Vercel Cron asks GitHub to start the daily update."""
import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path

_spec = importlib.util.spec_from_file_location("trigger", Path(__file__).resolve().parent.parent / "api" / "trigger.py")
trigger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trigger)


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, status=204, error=None):
        self.status, self.error, self.requests = status, error, []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.error:
            raise self.error
        return FakeResponse(self.status)


class RespondTest(unittest.TestCase):
    def test_missing_config_refuses_without_calling_github(self):
        opener = FakeOpener()
        self.assertEqual(trigger.respond("", "tok", "Bearer ", opener)[0], 500)
        self.assertEqual(trigger.respond("s3cret", "", "Bearer s3cret", opener)[0], 500)
        self.assertEqual(opener.requests, [])

    def test_wrong_or_missing_secret_is_401(self):
        opener = FakeOpener()
        self.assertEqual(trigger.respond("s3cret", "tok", "Bearer nope", opener)[0], 401)
        self.assertEqual(trigger.respond("s3cret", "tok", None, opener)[0], 401)
        self.assertEqual(trigger.respond("s3cret", "tok", "s3cret", opener)[0], 401)
        self.assertEqual(opener.requests, [])

    def test_valid_cron_call_dispatches_daily_workflow_on_main(self):
        opener = FakeOpener(status=204)
        code, msg = trigger.respond("s3cret", "ghtok", "Bearer s3cret", opener)
        self.assertEqual(code, 200)
        req = opener.requests[0]
        self.assertEqual(req.full_url, "https://api.github.com/repos/kamilszalast/auta-dla-sylwutki/actions/workflows/daily.yml/dispatches")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(json.loads(req.data), {"ref": "main"})
        self.assertEqual(req.get_header("Authorization"), "Bearer ghtok")

    def test_github_rejection_is_reported_as_502_with_status(self):
        err = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b""))
        code, msg = trigger.respond("s3cret", "ghtok", "Bearer s3cret", FakeOpener(error=err))
        self.assertEqual(code, 502)
        self.assertIn("403", msg)

    def test_github_unreachable_is_502(self):
        code, _ = trigger.respond("s3cret", "ghtok", "Bearer s3cret", FakeOpener(error=urllib.error.URLError("down")))
        self.assertEqual(code, 502)

    def test_github_read_timeout_is_502(self):
        code, _ = trigger.respond("s3cret", "ghtok", "Bearer s3cret", FakeOpener(error=TimeoutError("read timed out")))
        self.assertEqual(code, 502)


class HandlerTest(unittest.TestCase):
    """The class Vercel loads, served by a real local HTTP server (GitHub is never called here)."""

    def get(self, env, headers=None):
        import http.server
        import os
        import threading
        import urllib.request
        server = http.server.HTTPServer(("127.0.0.1", 0), trigger.handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/api/trigger" % server.server_port, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()
        finally:
            server.shutdown()
            server.server_close()
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_without_config_answers_500(self):
        code, body = self.get({"CRON_SECRET": "", "GITHUB_DISPATCH_TOKEN": ""})
        self.assertEqual(code, 500)
        self.assertIn("CRON_SECRET", body)

    def test_wrong_secret_answers_401(self):
        code, _ = self.get({"CRON_SECRET": "s3cret", "GITHUB_DISPATCH_TOKEN": "tok"}, {"Authorization": "Bearer nope"})
        self.assertEqual(code, 401)


if __name__ == "__main__":
    unittest.main()
