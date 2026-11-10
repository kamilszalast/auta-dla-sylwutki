import json
import tempfile
import unittest
from pathlib import Path

from scraper import overrides, store
from tests.helpers import item

URL = "https://www.otomoto.pl/osobowe/oferta/opel-astra-ID1.html"


def detailed_car(oto_id="1", url=URL):
    c = store.car_from_item(dict(item(otoId=oto_id, url=url), inAc=True), "2026-11-10")
    c["auto"] = {"equipment": {"ac": 1, "cam": 1, "pdc": 1, "cp": 0}, "plus": "Polski salon.",
                 "watch": None, "reject": None}
    return c


MANUAL = {"id": "olx:clio-17", "name": "Renault Clio IV", "engine": "1.5 dCi, 110 KM", "fuel": "on",
          "gear": "manualna", "body": "hatchback", "year": 2017, "km": 75563, "price": 28900,
          "city": "Oświęcim", "seller": "komis", "equipment": {"ac": 1, "cam": 1, "pdc": 1, "cp": 0},
          "plus": "Mały przebieg.", "olx": "https://www.olx.pl/d/oferta/renault-clio-iv-CID5-ID1cuRnS.html",
          "checked": "2026-11-10"}


class ApplyTest(unittest.TestCase):
    def test_auto_fields_restored_without_overrides(self):
        c = detailed_car()
        c.update(plus="stare", byKamil=["plus"])
        out = overrides.apply([c], {}, "2026-11-11")
        self.assertEqual((out[0]["plus"], out[0]["byKamil"], out[0]["equipment"]["cam"]), ("Polski salon.", [], 1))

    def test_exclude_by_url(self):
        out = overrides.apply([detailed_car()], {"exclude": [{"key": URL, "reason": "sprzedane"}]}, "2026-11-11")
        self.assertEqual(out[0]["reject"], "Kamil: sprzedane")

    def test_notes_replace_and_mark_kamil(self):
        ov = {"notes": {"otomoto:1": {"plus": "Serwis w ASO.", "watch": "Zapytaj o rozrząd.",
                                      "why": "Najlepsza.", "olx": "https://www.olx.pl/d/oferta/x.html"}}}
        c = overrides.apply([detailed_car()], ov, "2026-11-11")[0]
        self.assertEqual((c["plus"], c["watch"], c["why"]), ("Serwis w ASO.", "Zapytaj o rozrząd.", "Najlepsza."))
        self.assertEqual(c["links"]["olx"], "https://www.olx.pl/d/oferta/x.html")
        self.assertEqual(sorted(c["byKamil"]), ["plus", "watch", "why"])

    def test_equipment_override(self):
        c = overrides.apply([detailed_car()], {"equipment": {URL: {"cp": 1}}}, "2026-11-11")[0]
        self.assertEqual(c["equipment"], {"ac": 1, "cam": 1, "pdc": 1, "cp": 1})
        self.assertIn("equipment", c["byKamil"])

    def test_unknown_key_ignored(self):
        out = overrides.apply([detailed_car()], {"notes": {"otomoto:999": {"plus": "x"}}}, "2026-11-11")
        self.assertEqual(out[0]["plus"], "Polski salon.")

    def test_manual_entry_added(self):
        out = overrides.apply([], {"manual": [MANUAL]}, "2026-11-20")
        m = out[0]
        self.assertEqual((m["id"], m["status"], m["manual"], m["links"]["olx"]),
                         ("olx:clio-17", "active", True, MANUAL["olx"]))
        self.assertIn("10.11.2026", m["watch"])

    def test_manual_hidden_after_14_days(self):
        m = overrides.apply([], {"manual": [MANUAL]}, "2026-11-25")[0]
        self.assertEqual((m["status"], m["goneSince"]), ("gone", "2026-11-24"))

    def test_pins_resolved_to_ids(self):
        self.assertEqual(overrides.pins([detailed_car()], {"pin": {URL: 2, "nie-ma": 1}}), {"otomoto:1": 2})


class LoadTest(unittest.TestCase):
    def test_broken_json_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "overrides.json"
            p.write_text("{ to nie jest json")
            ov, err = overrides.load(p)
            self.assertEqual(ov, {})
            self.assertIn("overrides.json", err)

    def test_missing_file_is_empty(self):
        self.assertEqual(overrides.load(Path("/nie/ma/pliku.json")), ({}, None))

    def test_repo_file_is_valid(self):
        ov, err = overrides.load(Path(__file__).parent.parent / "data" / "overrides.json")
        self.assertIsNone(err)
        self.assertEqual(len(ov["manual"]), 3)
        self.assertGreaterEqual(len(ov["notes"]), 20)
        self.assertTrue(all(k.startswith("https://www.otomoto.pl/osobowe/oferta/") for k in ov["notes"]))


if __name__ == "__main__":
    unittest.main()
