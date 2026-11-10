import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scraper import pipeline
from scraper.http import Blocked, FetchError

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 11, 6, 4, tzinfo=ZoneInfo("Europe/Warsaw"))
PEUGEOT = "https://www.otomoto.pl/osobowe/oferta/peugeot-2008-ID6Ig0Ez.html"


def _replace_json(path, mutate):
    html = path.read_text()
    m = re.search(r'(<script id="__NEXT_DATA__"[^>]*>)(.*?)(</script>)', html, re.S)
    data = json.loads(m.group(2))
    mutate(data)
    return html[:m.start(2)] + json.dumps(data, ensure_ascii=False) + html[m.end(2):]


def list_html():
    def one_page(d):
        state = d["props"]["pageProps"]["urqlState"]["k1"]
        inner = json.loads(state["data"])
        inner["advertSearch"]["totalCount"] = len(inner["advertSearch"]["edges"])
        state["data"] = json.dumps(inner, ensure_ascii=False)
    return _replace_json(FIX / "otomoto_list.html", one_page)


def ad_html(description):
    def set_desc(d):
        d["props"]["pageProps"]["advert"]["description"] = description
    return _replace_json(FIX / "otomoto_ad.html", set_desc)


class FakeFetcher:
    def __init__(self, fail=lambda url: None):
        self.fail = fail
        self.urls = []
        self.lists = list_html()
        self.peugeot = (FIX / "otomoto_ad.html").read_text()
        self.other = ad_html("<p>Automatyczna klimatyzacja, kamera cofania.</p>")

    def get(self, url):
        self.urls.append(url)
        error = self.fail(url)
        if error:
            raise error
        if "/oferta/" in url:
            return self.peugeot if url == PEUGEOT else self.other
        return self.lists

    def ads(self):
        return [u for u in self.urls if "/oferta/" in u]


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "data").mkdir()
        self.addCleanup(shutil.rmtree, self.root)

    def run_pipeline(self, fetcher, now=NOW, **kw):
        args = dict(ran_by="actions", detail_limit=100, force=False)
        args.update(kw)
        return pipeline.run(self.root, fetcher, now, **args)

    def read(self, name):
        return json.loads((self.root / "data" / name).read_text())

    def test_run_writes_offers_and_meta(self):
        self.assertEqual(self.run_pipeline(FakeFetcher()), 0)
        meta, offers = self.read("meta.json"), self.read("offers.json")
        self.assertTrue(meta["lastRun"].startswith("2026-11-11T06:04"))
        self.assertEqual(meta["ranBy"], "actions")
        self.assertIn("403", meta["sources"]["olx"])
        self.assertGreater(meta["activeCount"], 20)
        self.assertEqual(meta["newCount"], meta["activeCount"])
        car = next(c for c in offers if c["links"]["otomoto"] == PEUGEOT)
        self.assertTrue(car["detailed"])
        self.assertEqual((car["equipment"]["ac"], car["equipment"]["pdc"]), (1, 1))
        self.assertEqual(car["shownSince"], "2026-11-11")
        self.assertEqual(sorted(c["top"] for c in offers if c["top"]), [1, 2, 3])

    def test_skip_when_already_ran_today(self):
        (self.root / "data" / "meta.json").write_text(json.dumps({"lastRun": "2026-11-11T06:01:00+01:00"}))
        f = FakeFetcher()
        self.assertEqual(self.run_pipeline(f), 0)
        self.assertEqual(f.urls, [])
        self.assertFalse((self.root / "data" / "offers.json").exists())

    def test_force_runs_again(self):
        (self.root / "data" / "meta.json").write_text(json.dumps({"lastRun": "2026-11-11T06:01:00+01:00"}))
        f = FakeFetcher()
        self.assertEqual(self.run_pipeline(f, force=True), 0)
        self.assertTrue(f.urls)

    def test_list_failure_keeps_cars_and_logs_error(self):
        self.run_pipeline(FakeFetcher())
        before = {c["id"] for c in self.read("offers.json") if c["status"] == "active"}
        (self.root / "data" / "meta.json").unlink()
        f = FakeFetcher(fail=lambda u: FetchError("timeout") if "hybrid" in u else None)
        self.assertEqual(self.run_pipeline(f), 0)
        after = {c["id"] for c in self.read("offers.json") if c["status"] == "active"}
        self.assertEqual(before, after)
        self.assertTrue(any("hybryda" in e for e in self.read("meta.json")["errors"]))

    def test_all_lists_fail_keeps_offers_exit_1(self):
        self.run_pipeline(FakeFetcher())
        offers_before = (self.root / "data" / "offers.json").read_text()
        meta_before = self.read("meta.json")
        f = FakeFetcher(fail=lambda u: Blocked("HTTP 403"))
        self.assertEqual(self.run_pipeline(f, force=True), 1)
        self.assertEqual((self.root / "data" / "offers.json").read_text(), offers_before)
        meta = self.read("meta.json")
        self.assertEqual(meta["lastRun"], meta_before["lastRun"])
        self.assertTrue(meta["errors"])
        self.assertEqual(len(f.urls), 1)

    def test_detail_limit_respected(self):
        f = FakeFetcher()
        self.run_pipeline(f, detail_limit=5)
        self.assertEqual(len(f.ads()), 5)
        meta = self.read("meta.json")
        self.assertGreater(meta["pendingDetails"], 0)

    def test_details_fetched_once(self):
        self.run_pipeline(FakeFetcher())
        f = FakeFetcher()
        self.run_pipeline(f, now=NOW + timedelta(days=1))
        self.assertEqual(f.ads(), [])
        self.assertEqual(self.read("meta.json")["newCount"], 0)

    def test_broken_overrides_logged(self):
        (self.root / "data" / "overrides.json").write_text("{ zepsute")
        self.assertEqual(self.run_pipeline(FakeFetcher()), 0)
        self.assertTrue(any("overrides.json" in e for e in self.read("meta.json")["errors"]))

    def test_no_private_fields_in_output(self):
        self.run_pipeline(FakeFetcher())
        text = (self.root / "data" / "offers.json").read_text() + (self.root / "data" / "meta.json").read_text()
        for needle in ('"description"', '"vin"', "date_registration", "Sprzedający", "Zadbany egzemplarz", "rozrząd"):
            self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main()
