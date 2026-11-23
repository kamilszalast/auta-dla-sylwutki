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


class MemBlob:
    """Like storage.Blob: head (API, fresh), fetch by URL, read/write with a content type, delete."""
    BASE = "https://store.public.blob.vercel-storage.com/data/"

    def __init__(self, head_error=None, delete_error=None):
        self.files, self.writes, self.deleted, self.misses = {}, [], [], 0
        self.head_error, self.delete_error = head_error, delete_error

    def head(self, name):
        if self.head_error:
            raise self.head_error
        return {"contentType": self.files[name][1], "url": self.BASE + name} if name in self.files else None

    def fetch(self, url):
        if self.misses:  # the version was replaced between head and fetch
            self.misses -= 1
            return None
        return self.read(url[len(self.BASE):], None)

    def read(self, name, default):
        return self.files[name][0] if name in self.files else default

    def write(self, name, obj, content_type="application/json; charset=utf-8"):
        self.writes.append(name)
        self.files[name] = (obj, content_type)

    def delete(self, names):
        if self.delete_error:
            raise self.delete_error
        self.deleted += names
        for n in names:
            self.files.pop(n, None)


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

    def test_on_blob_each_change_is_a_new_version_behind_the_pointer(self):
        blob = MemBlob()
        post(blob, {"op": "add", "item": CAR})
        first, pointer = blob.writes
        self.assertRegex(first, r"^watch/v/\d{13}-[0-9a-f]{6}\.json$")
        self.assertEqual(pointer, "watch.json")
        self.assertTrue(blob.files[pointer][1].endswith("; version=" + first[len("watch/v/"):-len(".json")]))
        post(blob, {"op": "add", "item": dict(CAR, id="otomoto:2")})
        self.assertEqual(blob.deleted, [first])
        self.assertEqual([i["id"] for i in watch.read_items(blob)[0]], [CAR["id"], "otomoto:2"])
        self.assertEqual(json.loads(watch.get_response(blob, KEY, None)[1])["items"], watch.read_items(blob)[0])

    def test_adding_a_watched_car_again_writes_nothing(self):
        blob = MemBlob()
        post(blob, {"op": "add", "item": CAR})
        n = len(blob.writes)
        self.assertEqual(post(blob, {"op": "add", "item": CAR})[0], 200)
        self.assertEqual(len(blob.writes), n)

    def test_a_version_replaced_between_head_and_fetch_is_read_again(self):
        blob = MemBlob()
        post(blob, {"op": "add", "item": CAR})
        blob.misses = 1
        self.assertEqual([i["id"] for i in watch.read_items(blob)[0]], [CAR["id"]])

    def test_a_failed_delete_does_not_fail_the_change(self):
        blob = MemBlob(delete_error=StorageError("Blob: usunięcie nie udało się"))
        post(blob, {"op": "add", "item": CAR})
        code, body = post(blob, {"op": "add", "item": dict(CAR, id="otomoto:2")})
        self.assertEqual((code, [i["id"] for i in body["items"]]), (200, [CAR["id"], "otomoto:2"]))
        self.assertEqual([i["id"] for i in watch.read_items(blob)[0]], [CAR["id"], "otomoto:2"])

    def test_a_pointer_without_a_version_is_the_older_one_file_list(self):
        blob = MemBlob()
        blob.files["watch.json"] = ({"items": [dict(CAR, added="2026-11-20")]}, "application/json; charset=utf-8")
        self.assertEqual(watch.read_items(blob), ([dict(CAR, added="2026-11-20")], None))
        post(blob, {"op": "add", "item": dict(CAR, id="otomoto:2")})
        self.assertEqual([i["id"] for i in watch.read_items(blob)[0]], [CAR["id"], "otomoto:2"])
        blob.files["watch.json"] = ({}, "application/json; charset=utf-8")
        with self.assertRaises(StorageError):
            watch.read_items(blob)

    def test_blob_head_error_is_502_and_nothing_is_saved(self):
        blob = MemBlob(head_error=StorageError("Blob: odczyt nie udał się"))
        self.assertEqual(watch.get_response(blob, KEY, None)[0], 502)
        self.assertEqual(post(blob, {"op": "add", "item": CAR})[0], 502)
        self.assertEqual(blob.writes, [])

    def test_storage_error_is_502(self):
        self.assertEqual(watch.get_response(Mem(fail=True), KEY, None)[0], 502)
        self.assertEqual(post(Mem(fail=True), {"op": "add", "item": CAR})[0], 502)


if __name__ == "__main__":
    unittest.main()
