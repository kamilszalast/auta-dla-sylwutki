import unittest

from scraper import ranking

FULL = {"ac": 1, "cam": 1, "pdc": 1, "cp": 1}
BARE = {"ac": 1, "cam": 0, "pdc": 0, "cp": 0}
NO_FACTS = {"salonPL": False, "firstOwner": False, "aso": False, "noAccident": False, "origin": None, "hasVin": False}
PL = dict(NO_FACTS, salonPL=True, origin="Polska")


def car(cid, fuel="on", km=60000, equipment=FULL, facts=PL, **kw):
    c = dict(id=cid, name=cid, body="kompakt", fuel=fuel, year=2017, km=km, price=27000, seller="prywatnie", equipment=dict(equipment), facts=dict(facts),
             out=None, pending=False, reject=None, status="active", manual=False, top=None, why=None, byKamil=[])
    c.update(kw)
    c["score"] = ranking.score(c)
    return c


def tops(cars):
    return [c["id"] for c in sorted((c for c in cars if c["top"]), key=lambda c: c["top"])]


class ScoreTest(unittest.TestCase):
    def test_full_equipment_beats_bare(self):
        self.assertGreater(car("a")["score"], car("b", equipment=BARE)["score"])

    def test_each_ask_costs(self):
        ask = dict(FULL, cp=2)
        self.assertLess(car("a", equipment=ask)["score"], car("b")["score"])

    def test_newer_and_lower_mileage_score_higher(self):
        self.assertGreater(car("a", year=2019)["score"], car("b", year=2015)["score"])
        self.assertGreater(car("a", km=40000)["score"], car("b", km=100000)["score"])


class PickTopTest(unittest.TestCase):
    def test_top_three_by_score(self):
        cars = [car("d%d" % i, km=10000 * (i + 1)) for i in range(5)]
        ranking.pick_top(cars, {})
        self.assertEqual(tops(cars), ["d0", "d1", "d2"])

    def test_out_pending_rejected_and_manual_never_top(self):
        cars = [car("out", km=1000, out="cena"), car("pend", km=1000, pending=True),
                car("rej", km=1000, reject="Cesja"), car("man", km=1000, manual=True),
                car("gone", km=1000, status="gone"), car("ok1"), car("ok2"), car("ok3")]
        ranking.pick_top(cars, {})
        self.assertEqual(sorted(tops(cars)), ["ok1", "ok2", "ok3"])

    def test_polish_private_bonus(self):
        self.assertGreater(car("pl")["score"], car("de", facts=dict(NO_FACTS, origin="Niemcy"))["score"] + 10)
        self.assertGreater(car("priv")["score"], car("komis", seller="komis")["score"] + 5)

    def test_imported_dealer_car_can_still_be_top(self):
        cars = [car("de", km=1000, year=2021, seller="komis", facts=dict(NO_FACTS, origin="Niemcy")),
                car("pl1", year=2012), car("pl2", year=2012), car("pl3", year=2012)]
        ranking.pick_top(cars, {})
        self.assertIn("de", tops(cars))

    def test_small_body_bonus(self):
        self.assertGreater(car("adam", name="Opel Adam", body="auta małe")["score"], car("astra", body="kompakt")["score"])

    def test_automatic_ac_scores_higher_than_manual(self):
        self.assertGreater(car("auto")["score"], car("manual", equipment=dict(FULL, ac=3))["score"])
        self.assertGreater(car("manual", equipment=dict(FULL, ac=3))["score"], car("ask", equipment=dict(FULL, ac=2))["score"])

    def test_vans_and_minivans_never_top(self):
        cars = [car("van", km=1000, name="Toyota ProAce"), car("meriva", km=1000, name="Opel Meriva"),
                car("a", name="Opel Astra"), car("b", name="Citroën C3"), car("c", name="Opel Adam")]
        ranking.pick_top(cars, {})
        self.assertEqual(sorted(tops(cars)), ["a", "b", "c"])

    def test_no_duplicate_model_in_top(self):
        cars = [car("astra1", km=10000, name="Opel Astra"), car("astra2", km=20000, name="Opel Astra"),
                car("c3", km=50000, name="Citroën C3"), car("adam", km=60000, name="Opel Adam")]
        ranking.pick_top(cars, {})
        self.assertEqual(tops(cars), ["astra1", "c3", "adam"])

    def test_pin_may_override_origin_rule(self):
        cars = [car("komis", seller="komis"), car("pl1"), car("pl2")]
        ranking.pick_top(cars, {"komis": 1})
        self.assertEqual(tops(cars), ["komis", "pl1", "pl2"])

    def test_diversity_swaps_in_lpg_when_close(self):
        cars = [car("d1", km=20000), car("d2", km=40000), car("d3", km=60000), car("lpg", fuel="lpg", km=100000)]
        ranking.pick_top(cars, {})
        self.assertEqual(tops(cars), ["d1", "d2", "lpg"])

    def test_no_swap_when_far(self):
        cars = [car("d1", km=20000), car("d2", km=40000), car("d3", km=60000), car("lpg", fuel="lpg", equipment=BARE)]
        ranking.pick_top(cars, {})
        self.assertEqual(tops(cars), ["d1", "d2", "d3"])

    def test_pin_wins(self):
        cars = [car("d1", km=20000), car("d2", km=40000), car("d3", km=60000), car("weak", equipment=BARE)]
        ranking.pick_top(cars, {"weak": 1})
        self.assertEqual(tops(cars), ["weak", "d1", "d2"])

    def test_previous_top_cleared(self):
        cars = [car("old", equipment=BARE, top=1, why="stare"), car("a"), car("b"), car("c")]
        ranking.pick_top(cars, {})
        self.assertIsNone(cars[0]["top"])
        self.assertIsNone(cars[0]["why"])

    def test_why_does_not_repeat_plus_facts(self):
        facts = dict(PL, firstOwner=True)
        cars = [car("a", facts=facts, fuel="lpg", year=2019), car("b"), car("c")]
        ranking.pick_top(cars, {})
        why = cars[0]["why"]
        self.assertTrue(why.startswith("Pełne wyposażenie: kamera, czujniki i CarPlay"), why)
        self.assertIn("gaz", why)
        self.assertIn("młody rocznik", why)
        self.assertNotIn("salon", why.lower())
        self.assertNotIn("właściciel", why)

    def test_kamil_why_kept(self):
        cars = [car("a", why="Najlepsza.", byKamil=["why"]), car("b"), car("c")]
        ranking.pick_top(cars, {})
        self.assertEqual(cars[0]["why"], "Najlepsza.")


if __name__ == "__main__":
    unittest.main()
