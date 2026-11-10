import unittest
import urllib.parse
from pathlib import Path

from scraper import config, otomoto
from scraper.http import Blocked, Fetcher, FetchError, NotFound

FIX = Path(__file__).parent / "fixtures"


def query(key):
    return next(q for q in config.QUERIES if q["key"] == key)


class ParseListTest(unittest.TestCase):
    def test_parse_list_total_and_fields(self):
        total, items = otomoto.parse_list((FIX / "otomoto_list.html").read_text())
        self.assertEqual(total, 115)
        self.assertEqual(len(items), 32)
        first = items[0]
        self.assertEqual(first["otoId"], "6150771539")
        self.assertEqual(first["url"], "https://www.otomoto.pl/osobowe/oferta/peugeot-2008-ID6Ig0Ez.html")
        self.assertEqual(first["name"], "Peugeot 2008")
        self.assertEqual(first["make"], "peugeot")
        self.assertEqual(first["model"], "2008")
        self.assertEqual(first["version"], "e-HDi FAP 92 STOP & START Allure")
        self.assertEqual((first["year"], first["km"], first["hp"], first["cc"]), (2015, 87000, 92, 1560))
        self.assertEqual((first["fuel"], first["gear"], first["seller"]), ("on", "manualna", "prywatnie"))
        self.assertEqual((first["price"], first["city"], first["region"]), (28900, "Tomnice", "Wielkopolskie"))
        self.assertEqual(first["origin"], "Francja")

    def test_parse_list_skips_broken_nodes(self):
        import json, re
        html = (FIX / "otomoto_list.html").read_text()
        m = re.search(r'(<script id="__NEXT_DATA__"[^>]*>)(.*?)(</script>)', html, re.S)
        data = json.loads(m.group(2))
        inner = json.loads(data["props"]["pageProps"]["urqlState"]["k1"]["data"])
        edges = inner["advertSearch"]["edges"]
        del edges[1]["node"]["id"]
        edges[2] = None
        edges[3] = {"node": None}
        data["props"]["pageProps"]["urqlState"]["k1"]["data"] = json.dumps(inner)
        total, items = otomoto.parse_list(html[:m.start(2)] + json.dumps(data) + html[m.end(2):])
        self.assertEqual((total, len(items)), (115, 29))

    def test_parse_without_page_props_raises_value_error(self):
        page = '<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>'
        with self.assertRaises(ValueError):
            otomoto.parse_list(page)
        with self.assertRaises(ValueError):
            otomoto.parse_ad(page)

    def test_parse_list_without_next_data_raises(self):
        with self.assertRaises(ValueError):
            otomoto.parse_list("<html>captcha</html>")


class ParseAdTest(unittest.TestCase):
    def test_parse_ad_equipment_and_details(self):
        ad = otomoto.parse_ad((FIX / "otomoto_ad.html").read_text())
        self.assertEqual(ad["status"], "ACTIVE")
        self.assertEqual(ad["price"], 28900)
        self.assertIn("dwustrefowa", ad["ac_label"])
        self.assertIn("park_distance_control_rear", ad["equipment_keys"])
        self.assertNotIn("rear_view_camera", ad["equipment_keys"])
        self.assertEqual(ad["details"]["no_accident"], "Tak")
        self.assertEqual(ad["details"]["country_origin"], "Francja")
        self.assertIn("Dwustrefowa automatyczna klimatyzacja", ad["description"])
        self.assertNotIn("<p>", ad["description"])


class SearchUrlTest(unittest.TestCase):
    def params(self, url):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))

    def test_search_url_contains_filters(self):
        url = otomoto.search_url(query("on"), with_ac=False, page=1)
        self.assertTrue(url.startswith("https://www.otomoto.pl/osobowe/od-2011?"))
        p = self.params(url)
        self.assertEqual(p["search[filter_enum_fuel_type]"], "diesel")
        self.assertEqual(p["search[filter_float_engine_capacity:to]"], "1600")
        self.assertEqual(p["search[filter_enum_damaged]"], "0")
        self.assertEqual(p["search[filter_float_price:to]"], "31000")
        self.assertEqual(p["search[filter_float_engine_power:from]"], "85")
        self.assertNotIn("search[filter_enum_air_conditioning_type][0]", p)
        self.assertNotIn("page", p)

    def test_search_url_with_ac_and_page(self):
        p = self.params(otomoto.search_url(query("lpg"), with_ac=True, page=3))
        self.assertEqual(p["page"], "3")
        self.assertEqual(
            {p["search[filter_enum_air_conditioning_type][%d]" % i] for i in range(3)},
            {"automatic-climate-control", "dualzone-automatic-climate-control", "trizone-automatic-climate-control"},
        )

    def test_adam_query(self):
        url = otomoto.search_url(query("pb"), with_ac=False, page=1)
        self.assertTrue(url.startswith("https://www.otomoto.pl/osobowe/opel/adam/od-2011?"))
        p = self.params(url)
        self.assertEqual(p["search[filter_float_engine_power:from]"], "85")
        self.assertNotIn("search[filter_enum_fuel_type]", p)

    def test_hybrid_mileage_limit(self):
        self.assertEqual(self.params(otomoto.search_url(query("hev"), False, 1))["search[filter_float_mileage:to]"], "160000")


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    import urllib.error
    return urllib.error.HTTPError("u", code, "x", {}, None)


class FetcherTest(unittest.TestCase):
    def test_blocked_no_retry(self):
        calls = []

        def opener(req, timeout):
            calls.append(req)
            raise http_error(403)

        f = Fetcher(delay=(0, 0), sleep=lambda s: None, opener=opener)
        with self.assertRaises(Blocked):
            f.get("https://www.otomoto.pl/x")
        self.assertEqual(len(calls), 1)

    def test_not_found(self):
        def opener(req, timeout):
            raise http_error(404)

        with self.assertRaises(NotFound):
            Fetcher(delay=(0, 0), sleep=lambda s: None, opener=opener).get("https://www.otomoto.pl/x")

    def test_retry_on_server_error_then_success(self):
        answers = [http_error(503), http_error(500)]
        waits = []

        def opener(req, timeout):
            if answers:
                raise answers.pop(0)
            return FakeResponse("ok")

        f = Fetcher(delay=(0, 0), sleep=waits.append, opener=opener)
        self.assertEqual(f.get("https://www.otomoto.pl/x"), "ok")
        self.assertEqual(waits[:2], [10, 30])

    def test_read_errors_are_retried(self):
        import http.client
        import socket
        answers = [http.client.IncompleteRead(b""), socket.timeout("timed out"), http.client.BadStatusLine("x")]

        def opener(req, timeout):
            if answers:
                raise answers.pop(0)
            return FakeResponse("ok")

        self.assertEqual(Fetcher(delay=(0, 0), sleep=lambda s: None, opener=opener).get("https://www.otomoto.pl/x"), "ok")

    def test_gives_up_after_three_retries(self):
        def opener(req, timeout):
            raise http_error(500)

        with self.assertRaises(FetchError):
            Fetcher(delay=(0, 0), sleep=lambda s: None, opener=opener).get("https://www.otomoto.pl/x")

    def test_user_agent_has_no_email(self):
        seen = {}

        def opener(req, timeout):
            seen.update(dict(req.header_items()))
            return FakeResponse("ok")

        Fetcher(delay=(0, 0), sleep=lambda s: None, opener=opener).get("https://www.otomoto.pl/x")
        ua = seen.get("User-agent", "")
        self.assertIn("Mozilla/5.0", ua)
        self.assertNotIn("@", ua)


if __name__ == "__main__":
    unittest.main()
