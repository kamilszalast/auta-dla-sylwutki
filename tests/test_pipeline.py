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


def ad_html(description, origin="Francja"):
    def set_desc(d):
        advert = d["props"]["pageProps"]["advert"]
        advert["description"] = description
        for detail in advert["details"]:
            if detail["key"] == "country_origin":
                detail["value"] = origin
    return _replace_json(FIX / "otomoto_ad.html", set_desc)


class FakeFetcher:
    def __init__(self, fail=lambda url: None):
        self.fail = fail
        self.urls = []
        self.lists = list_html()
        self.peugeot = (FIX / "otomoto_ad.html").read_text()
        self.other = ad_html("<p>Automatyczna klimatyzacja, kamera cofania.</p>", origin="Polska")

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
        tops = [c for c in offers if c["top"]]
        self.assertEqual(sorted(c["top"] for c in tops), [1, 2, 3])
        self.assertTrue(all(c["facts"]["origin"] == "Polska" and c["seller"] == "prywatnie" for c in tops))

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


class DetailQueueTest(unittest.TestCase):
    def test_title_rejected_cars_not_fetched(self):
        from scraper import store
        from tests.helpers import item
        cesja = store.car_from_item(dict(item(otoId="1", url="https://www.otomoto.pl/osobowe/oferta/a-ID1.html",
                                              title="Toyota Corolla cesja leasingu"), inAc=True), "2026-11-11")
        ok = store.car_from_item(dict(item(otoId="2", url="https://www.otomoto.pl/osobowe/oferta/b-ID2.html"),
                                      inAc=True), "2026-11-11")
        f = FakeFetcher()
        pipeline._details([cesja, ok], f, "2026-11-11", 100, [])
        self.assertEqual(f.ads(), ["https://www.otomoto.pl/osobowe/oferta/b-ID2.html"])
        self.assertIn("Cesja", cesja["auto"]["reject"])


def empty_list_html():
    def no_results(d):
        state = d["props"]["pageProps"]["urqlState"]["k1"]
        inner = json.loads(state["data"])
        inner["advertSearch"]["totalCount"] = 0
        inner["advertSearch"]["edges"] = []
        state["data"] = json.dumps(inner)
    return _replace_json(FIX / "otomoto_list.html", no_results)


class RobustnessTest(unittest.TestCase):
    setUp, run_pipeline, read = PipelineTest.setUp, PipelineTest.run_pipeline, PipelineTest.read

    def test_detail_storm_stops_after_three_failures(self):
        f = FakeFetcher(fail=lambda u: FetchError("HTTP 503") if "/oferta/" in u else None)
        self.assertEqual(self.run_pipeline(f), 0)
        self.assertEqual(len(f.ads()), 3)
        self.assertTrue(any("przerwane" in e for e in self.read("meta.json")["errors"]))

    def test_unexpected_exception_does_not_stop_run(self):
        f = FakeFetcher(fail=lambda u: RuntimeError("boom") if u == PEUGEOT or "hybrid" in u else None)
        self.assertEqual(self.run_pipeline(f), 0)
        self.assertGreater(self.read("meta.json")["activeCount"], 20)

    def test_detail_time_budget(self):
        ticks = iter(range(0, 100000, 400))
        orig = pipeline.clock
        pipeline.clock = lambda: next(ticks)
        self.addCleanup(setattr, pipeline, "clock", orig)
        f = FakeFetcher()
        self.run_pipeline(f)
        self.assertLess(len(f.ads()), 5)

    def test_empty_query_keeps_cars(self):
        self.run_pipeline(FakeFetcher())
        before = {c["id"] for c in self.read("offers.json") if c["status"] == "active"}
        f = FakeFetcher()
        f.lists = empty_list_html()  # e.g. Otomoto renamed a filter: every query comes back empty
        self.run_pipeline(f, now=NOW + timedelta(days=1))
        after = {c["id"] for c in self.read("offers.json") if c["status"] == "active"}
        self.assertEqual(before, after)

    def test_page_cap_counts_as_incomplete(self):
        seen, complete, ok = pipeline._search(FakeFetcher(), [])
        self.assertTrue(complete)
        orig = pipeline.MAX_PAGES
        pipeline.MAX_PAGES = 0
        self.addCleanup(setattr, pipeline, "MAX_PAGES", orig)
        seen, complete, ok = pipeline._search(FakeFetcher(), [])
        self.assertFalse(complete)

    def test_outdated_rules_rechecked(self):
        self.run_pipeline(FakeFetcher())
        offers = self.read("offers.json")
        detailed = [c for c in offers if c.get("detailed")]
        for i, c in enumerate(detailed):
            c["rulesVersion"] = 1
            if i % 2 == 0:
                c["auto"]["reject"] = c["reject"] = "Klimatyzacja manualna"
        (self.root / "data" / "offers.json").write_text(json.dumps(offers))
        rejected = {c["links"]["otomoto"] for c in offers if c.get("reject")}
        f = FakeFetcher()
        self.run_pipeline(f, now=NOW + timedelta(days=1), detail_limit=4)
        self.assertEqual(len(f.ads()), 4)
        self.assertTrue(rejected)
        self.assertFalse(set(f.ads()) & rejected)  # cars Sylwia sees are rechecked before rejected ones

    def test_warnings_marked_for_actions(self):
        import io, os
        from contextlib import redirect_stdout
        (self.root / "data" / "overrides.json").write_text('{"manual": [{"id": "x"}]}')
        os.environ["GITHUB_ACTIONS"] = "true"
        self.addCleanup(os.environ.pop, "GITHUB_ACTIONS")
        out = io.StringIO()
        with redirect_stdout(out):
            self.run_pipeline(FakeFetcher())
        self.assertIn("::warning::overrides.json", out.getvalue())
