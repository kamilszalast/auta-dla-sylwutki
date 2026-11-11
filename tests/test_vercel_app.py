"""scraper/vercel_app.py: what /api/run and /api/data answer on Vercel."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scraper import storage, vercel_app

NOW = datetime(2026, 11, 12, 6, 10, tzinfo=ZoneInfo("Europe/Warsaw"))


class RunTurnTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def fake_run(self, code=0, error=None):
        def run(root, fetcher, now, ran_by, detail_limit, force, **kw):
            self.calls.append(dict(ran_by=ran_by, force=force, **kw))
            if error:
                raise error
            print("Aktualizacja: 338 aut na stronie, nowe: 4")
            return code
        return run

    def turn(self, secret="s3cret", header="Bearer s3cret", blob=("vercel_blob_rw_St_x", None, None), run=None):
        return vercel_app.run_turn(secret, header, blob, Path("/tmp"), NOW, fetcher=object(), run=run or self.fake_run())

    def test_missing_secret_or_blob_refuses_without_running(self):
        self.assertEqual(self.turn(secret="")[0], 500)
        self.assertEqual(self.turn(blob=None)[0], 500)
        self.assertEqual(self.calls, [])

    def test_wrong_secret_is_401(self):
        self.assertEqual(self.turn(header="Bearer nope")[0], 401)
        self.assertEqual(self.turn(header=None)[0], 401)
        self.assertEqual(self.calls, [])

    def test_valid_call_runs_one_time_limited_turn_on_blob(self):
        code, text = self.turn()
        self.assertEqual(code, 200)
        self.assertIn("338 aut", text)
        call = self.calls[0]
        self.assertEqual((call["ran_by"], call["force"], call["continue_details"]), ("vercel", False, True))
        self.assertLessEqual(call["budget_s"], 240)  # Vercel stops the function after 300 s
        self.assertIsInstance(call["storage"], storage.Blob)

    def test_failed_turn_and_storage_errors_are_502(self):
        self.assertEqual(self.turn(run=self.fake_run(code=1))[0], 502)
        code, text = self.turn(run=self.fake_run(error=storage.StorageError("Blob: zapis nie udał się")))
        self.assertEqual(code, 502)
        self.assertIn("Blob", text)

    def test_unexpected_error_is_500_with_readable_log(self):
        code, text = self.turn(run=self.fake_run(error=RuntimeError("boom")))
        self.assertEqual(code, 500)
        self.assertIn("RuntimeError", text)


class BlobAuthTest(unittest.TestCase):
    def test_oidc_from_request_header_with_store_id_wins(self):
        env = {"BLOB_STORE_ID": "store_Abc123", "BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_x_y"}
        self.assertEqual(vercel_app.blob_auth(env, {"x-vercel-oidc-token": "oidc"}), ("oidc", "Abc123", "vercel_blob_rw_x_y"))

    def test_oidc_from_env(self):
        self.assertEqual(vercel_app.blob_auth({"BLOB_STORE_ID": "Abc", "VERCEL_OIDC_TOKEN": "o"}, {}), ("o", "Abc", None))

    def test_read_write_token_without_oidc(self):
        self.assertEqual(vercel_app.blob_auth({"BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_x_y"}, {}), ("vercel_blob_rw_x_y", None, None))

    def test_store_id_without_any_token_is_none(self):
        self.assertIsNone(vercel_app.blob_auth({"BLOB_STORE_ID": "Abc"}, {}))
        self.assertIsNone(vercel_app.blob_auth({}, {}))


class DataTest(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.data)
        (self.data / "meta.json").write_text(json.dumps({"lastRun": "2026-11-12T06:10:00+01:00"}))

    def test_serves_known_files_as_json(self):
        code, body, headers = vercel_app.data_response("meta", storage.Local(self.data))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"lastRun": "2026-11-12T06:10:00+01:00"})
        self.assertIn("application/json", headers["Content-Type"])
        self.assertIn("s-maxage", headers["Cache-Control"])

    def test_unknown_name_is_404(self):
        for name in ("overrides", "../meta", "", None):
            self.assertEqual(vercel_app.data_response(name, storage.Local(self.data))[0], 404)

    def test_missing_file_is_404(self):
        self.assertEqual(vercel_app.data_response("offers", storage.Local(self.data))[0], 404)

    def test_storage_error_is_502(self):
        class Broken:
            def read(self, name, default):
                raise storage.StorageError("Blob: odczyt nie udał się")
        self.assertEqual(vercel_app.data_response("offers", Broken())[0], 502)


if __name__ == "__main__":
    unittest.main()
