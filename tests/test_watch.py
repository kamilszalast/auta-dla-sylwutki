"""scraper/watch.py: the shared "Obserwowane" list behind /api/watch."""
import json
import unittest

from scraper import watch
from scraper.storage import StorageError

KEY = "k3y-for-tests"
CAR = {"id": "otomoto:6151101294", "name": "Opel Astra", "year": 2020, "city": "Myszków", "price": 28900,
       "url": "https://www.otomoto.pl/osobowe/oferta/opel-astra-ID6Ihorc.html"}


class Mem:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.writes = data, fail, []

    def read(self, name, default):
        if self.fail:
            raise StorageError("Blob: odczyt nie udał się")
        return self.data if self.data is not None else default

    def write(self, name, obj):
        self.writes.append((name, obj))
        self.data = obj


def post(storage, req, given=KEY, key=KEY, today="2026-11-23"):
    code, body, _ = watch.post_response(storage, key, given, json.dumps(req).encode(), today)
    return code, json.loads(body)


class ApplyTest(unittest.TestCase):
    def test_add_saves_a_copy_with_the_day_it_was_added(self):
        items = watch.apply([], {"op": "add", "item": CAR}, "2026-11-23")
        self.assertEqual(items, [dict(CAR, added="2026-11-23")])

    def test_adding_a_watched_car_again_keeps_the_first_price_and_day(self):
        first = watch.apply([], {"op": "add", "item": CAR}, "2026-11-20")
        again = watch.apply(first, {"op": "add", "item": dict(CAR, price=25000)}, "2026-11-23")
        self.assertEqual(again, [dict(CAR, added="2026-11-20")])

    def test_remove_drops_only_that_car(self):
        other = dict(CAR, id="otomoto:1", name="Opel Adam")
        items = watch.apply(watch.apply([], {"op": "add", "item": CAR}, "2026-11-23"), {"op": "add", "item": other}, "2026-11-23")
        self.assertEqual([i["id"] for i in watch.apply(items, {"op": "remove", "id": CAR["id"]}, "2026-11-23")], ["otomoto:1"])

    def test_import_adds_the_saved_cars_that_are_not_on_the_list(self):
        items = watch.apply([dict(CAR, added="2026-11-20")], {"op": "import", "items": [CAR, dict(CAR, id="otomoto:2")]}, "2026-11-23")
        self.assertEqual([(i["id"], i["added"]) for i in items], [(CAR["id"], "2026-11-20"), ("otomoto:2", "2026-11-23")])

    def test_import_skips_a_bad_car_and_moves_the_rest(self):
        items = watch.apply([], {"op": "import", "items": [dict(CAR, url="https://evil.example/x"), CAR]}, "2026-11-23")
        self.assertEqual(items, [dict(CAR, added="2026-11-23")])

    def test_unknown_fields_are_dropped_and_missing_optional_ones_skipped(self):
        item = watch.clean_item({"id": "otomoto:3", "name": "Kia Rio", "url": "https://www.olx.pl/d/oferta/x.html", "x": "<b>"})
        self.assertEqual(item, {"id": "otomoto:3", "name": "Kia Rio", "url": "https://www.olx.pl/d/oferta/x.html"})

    def test_links_outside_otomoto_and_olx_are_refused(self):
        for url in ("http://www.otomoto.pl/x", "https://evil.example/x", "https://otomoto.pl.evil.example/x", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(watch.WatchError) as e:
                watch.clean_item(dict(CAR, url=url))
            self.assertEqual(e.exception.code, 400)

    def test_bad_fields_are_refused(self):
        for bad in ({"price": "28900"}, {"price": -1}, {"year": True}, {"name": ""}, {"name": "x" * 121}, {"id": None}):
            with self.subTest(bad=bad), self.assertRaises(watch.WatchError):
                watch.clean_item(dict(CAR, **bad))

    def test_a_full_list_refuses_new_cars(self):
        full = [dict(CAR, id="otomoto:%d" % n) for n in range(watch.MAX_ITEMS)]
        with self.assertRaises(watch.WatchError) as e:
            watch.apply(full, {"op": "add", "item": CAR}, "2026-11-23")
        self.assertEqual(e.exception.code, 409)

    def test_unknown_change_is_refused(self):
        with self.assertRaises(watch.WatchError):
            watch.apply([], {"op": "clear"}, "2026-11-23")


class ResponsesTest(unittest.TestCase):
    def test_get_lists_items_and_says_whether_the_key_edits(self):
        mem = Mem({"items": [dict(CAR, added="2026-11-20")]})
        for given, can in ((KEY, True), ("nope", False), (None, False)):
            code, body, headers = watch.get_response(mem, KEY, given)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body), {"items": [dict(CAR, added="2026-11-20")], "canEdit": can, "keySet": True})
            self.assertEqual(headers["Cache-Control"], "no-store")

    def test_get_without_watch_key_on_the_server_says_so(self):
        body = json.loads(watch.get_response(Mem(), "", "anything")[1])
        self.assertEqual((body["canEdit"], body["keySet"]), (False, False))

    def test_get_on_a_new_store_is_an_empty_list(self):
        self.assertEqual(json.loads(watch.get_response(Mem(), KEY, None)[1])["items"], [])

    def test_post_saves_the_new_list(self):
        mem = Mem()
        code, body = post(mem, {"op": "add", "item": CAR})
        self.assertEqual(code, 200)
        self.assertEqual(body["items"], [dict(CAR, added="2026-11-23")])
        self.assertEqual(mem.writes, [("watch.json", {"items": [dict(CAR, added="2026-11-23")]})])

    def test_post_without_the_right_key_changes_nothing(self):
        mem = Mem()
        for given in ("nope", None, ""):
            self.assertEqual(post(mem, {"op": "add", "item": CAR}, given=given)[0], 403)
        self.assertEqual(post(mem, {"op": "add", "item": CAR}, key="")[0], 500)
        self.assertEqual(mem.writes, [])

    def test_bad_json_and_bad_items_are_400_without_saving(self):
        mem = Mem()
        code, _, _ = watch.post_response(mem, KEY, KEY, b"{nope", "2026-11-23")
        self.assertEqual(code, 400)
        self.assertEqual(post(mem, {"op": "add", "item": dict(CAR, url="https://evil.example/")})[0], 400)
        self.assertEqual(mem.writes, [])

    def test_storage_error_is_502(self):
        self.assertEqual(watch.get_response(Mem(fail=True), KEY, None)[0], 502)
        self.assertEqual(post(Mem(fail=True), {"op": "add", "item": CAR})[0], 502)


if __name__ == "__main__":
    unittest.main()
