import tempfile
import unittest
from pathlib import Path

from scraper import store
from tests.helpers import item


def seen(*items, in_ac=False):
    return {"otomoto:" + i["otoId"]: dict(i, inAc=in_ac) for i in items}


class CarFromItemTest(unittest.TestCase):
    def test_car_fields(self):
        c = store.car_from_item(dict(item(otoId="42", cc=1560, hp=92), inAc=True), "2026-11-11")
        self.assertEqual(c["id"], "otomoto:42")
        self.assertEqual(c["links"], {"otomoto": "https://www.otomoto.pl/osobowe/oferta/opel-astra-ID1.html", "olx": None})
        self.assertEqual(c["engine"], "1.6, 92 KM")
        self.assertEqual((c["firstSeen"], c["lastSeen"], c["status"]), ("2026-11-11", "2026-11-11", "active"))
        self.assertFalse(c["detailed"])
        self.assertTrue(c["inAc"])


class MergeTest(unittest.TestCase):
    def test_new_car_gets_first_seen(self):
        cars, new = store.merge([], seen(item(otoId="1")), "2026-11-11", True)
        self.assertEqual(new, ["otomoto:1"])
        self.assertEqual(cars[0]["firstSeen"], "2026-11-11")

    def test_existing_updates_price_keeps_first_seen(self):
        old = store.car_from_item(dict(item(otoId="1", price=29000), inAc=False), "2026-11-10")
        old["detailed"] = True
        cars, new = store.merge([old], seen(item(otoId="1", price=27500)), "2026-11-11", True)
        self.assertEqual(new, [])
        self.assertEqual((cars[0]["price"], cars[0]["firstSeen"], cars[0]["lastSeen"]), (27500, "2026-11-10", "2026-11-11"))
        self.assertTrue(cars[0]["detailed"])

    def test_missing_marked_gone_only_when_lists_complete(self):
        old = store.car_from_item(dict(item(otoId="1"), inAc=False), "2026-11-10")
        cars, _ = store.merge([dict(old)], {}, "2026-11-11", False)
        self.assertEqual(cars[0]["status"], "active")
        cars, _ = store.merge([dict(old)], {}, "2026-11-11", True)
        self.assertEqual((cars[0]["status"], cars[0]["goneSince"]), ("gone", "2026-11-11"))

    def test_gone_older_than_30_days_dropped(self):
        old = store.car_from_item(dict(item(otoId="1"), inAc=False), "2026-09-01")
        old.update(status="gone", goneSince="2026-10-11")
        self.assertEqual(store.merge([old], {}, "2026-11-11", True)[0], [])
        old["goneSince"] = "2026-10-13"
        self.assertEqual(len(store.merge([old], {}, "2026-11-11", True)[0]), 1)

    def test_reappearing_car_active_again(self):
        old = store.car_from_item(dict(item(otoId="1"), inAc=False), "2026-11-01")
        old.update(status="gone", goneSince="2026-11-05")
        cars, new = store.merge([old], seen(item(otoId="1")), "2026-11-11", True)
        self.assertEqual((cars[0]["status"], cars[0]["goneSince"], new), ("active", None, []))


class JsonTest(unittest.TestCase):
    def test_load_missing_returns_default_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            self.assertEqual(store.load(p, []), [])
            store.save_json(p, {"a": "zł"})
            self.assertEqual(store.load(p, None), {"a": "zł"})
            self.assertIn("zł", p.read_text())


if __name__ == "__main__":
    unittest.main()
