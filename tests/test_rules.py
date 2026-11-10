import unittest

from scraper import rules
from tests.helpers import AUTO_LABEL, ad, item


def run(description="", label=AUTO_LABEL, keys=(), details=None, in_ac=False, **item_kw):
    return rules.classify(item(**item_kw), ad(description, label, keys, details), in_ac)


class AirConditioningTest(unittest.TestCase):
    def test_ac_from_param(self):
        r = run(label=AUTO_LABEL)
        self.assertEqual(r["equipment"]["ac"], 1)
        self.assertIsNone(r["reject"])

    def test_ac_from_description(self):
        r = run("Auto ma climatronic i tempomat.", label=None)
        self.assertEqual(r["equipment"]["ac"], 1)
        self.assertIsNone(r["reject"])

    def test_ac_plain_klimatyzacja_is_present(self):
        r = run("Sprawna klimatyzacja, nowe opony.", label=None)
        self.assertEqual(r["equipment"]["ac"], 3)
        self.assertEqual(r["watch"], [])

    def test_ac_manual_label_accepted(self):
        r = run("Zadbany.", label="Klimatyzacja manualna")
        self.assertIsNone(r["reject"])
        self.assertEqual(r["equipment"]["ac"], 3)
        self.assertIn("klima manualna", r["plus"])

    def test_no_ac_mention_is_ask(self):
        r = run("Zadbany, nowe opony.", label=None)
        self.assertIsNone(r["reject"])
        self.assertEqual(r["equipment"]["ac"], 2)
        self.assertIn("W ogłoszeniu nie ma słowa o klimatyzacji. Dopytaj.", r["watch"])

    def test_migrate_stored_ac_results(self):
        manual = {"equipment": {"ac": 0, "cam": 1, "pdc": 0, "cp": 0}, "reject": "Klimatyzacja manualna", "plus": None, "watch": None}
        rules.migrate_ac(manual)
        self.assertEqual((manual["reject"], manual["equipment"]["ac"], manual["plus"]), (None, 3, "Klima manualna."))
        none = {"equipment": {"ac": 0, "cam": 0, "pdc": 0, "cp": 0}, "reject": "Brak klimy automatycznej w ogłoszeniu", "plus": "Bezwypadkowy.", "watch": None}
        rules.migrate_ac(none)
        self.assertEqual((none["reject"], none["equipment"]["ac"], none["watch"]), (None, 2, "W ogłoszeniu nie ma słowa o klimatyzacji. Dopytaj."))
        plain = {"equipment": {"ac": 2, "cam": 0, "pdc": 0, "cp": 0}, "reject": None, "plus": None,
                 "watch": "W ogłoszeniu sama „klimatyzacja”. Dopytaj, czy jest automatyczna. Auto sprowadzone."}
        rules.migrate_ac(plain)
        self.assertEqual((plain["equipment"]["ac"], plain["watch"]), (3, "Auto sprowadzone."))
        damaged = {"equipment": {"ac": 1, "cam": 0, "pdc": 0, "cp": 0}, "reject": "Uszkodzone według opisu", "plus": None, "watch": None}
        rules.migrate_ac(damaged)
        self.assertEqual((damaged["reject"], damaged["equipment"]["ac"]), ("Uszkodzone według opisu", 1))


class RedFlagsTest(unittest.TestCase):
    def test_cesja_rejected(self):
        self.assertIn("Cesja", run("Cesja leasingu, odstępne 19 900 zł.")["reject"])
        self.assertIn("Cesja", run("Do zapłaty odstępne, dalej raty.")["reject"])

    def test_leasing_word_alone_ok(self):
        self.assertIsNone(run("Możliwy leasing i kredyt.")["reject"])

    def test_damage_rejected(self):
        self.assertEqual(run("Auto uszkodzone z przodu.")["reject"], "Uszkodzone według opisu")

    def test_negated_damage_ok(self):
        for text in ("Auto nieuszkodzony, bezwypadkowy.", "Stan idealny, bez uszkodzeń.", "Brak uszkodzeń blacharskich.",
                     "Brak jakichkolwiek uszkodzeń.", "Auto bez jakichkolwiek uszkodzeń.", "Brak wszelkich uszkodzeń.",
                     "Nie posiada najmniejszych uszkodzeń.", "Auto wolne od uszkodzeń.", "Zero uszkodzeń, zero rdzy.",
                     "Brak wgnieceń, rys i uszkodzeń."):
            self.assertIsNone(run(text)["reject"], text)

    def test_negation_does_not_cross_sentences(self):
        self.assertEqual(run("Brak rdzy. Uszkodzony zderzak z przodu.")["reject"], "Uszkodzone według opisu")

    def test_do_naprawy_is_watch_not_reject(self):
        r = run("Do naprawy czujnik ciśnienia w oponach.")
        self.assertIsNone(r["reject"])
        self.assertTrue(any("naprawy" in w for w in r["watch"]))

    def test_low_mileage_rejected(self):
        self.assertIn("mały przebieg", run(km=190, year=2018)["reject"])

    def test_low_mileage_new_car_ok(self):
        self.assertIsNone(run(km=9000, year=2023)["reject"])


class MileageTest(unittest.TestCase):
    def test_mileage_higher_in_description_rejected(self):
        r = run("Przebieg: 159 900 km, serwisowany.", km=119900)
        self.assertEqual(r["reject"], "Przebieg w opisie (159 900 km) wyższy niż w ogłoszeniu (119 900 km)")

    def test_mileage_typo_is_watch(self):
        r = run("Niski przebieg 9 347 km.", km=93500)
        self.assertIsNone(r["reject"])
        self.assertTrue(any("9 347 km" in w and "93 500 km" in w for w in r["watch"]))

    def test_mileage_in_thousands(self):
        self.assertIsNone(run("Przebieg 100 tys. km udokumentowany.", km=100500)["reject"])

    def test_service_mileage_ignored(self):
        for text in ("Rozrząd do wymiany przy przebiegu 150 000 km.", "Następny przegląd przy przebiegu 120 tys km."):
            r = run(text, km=110000)
            self.assertIsNone(r["reject"], text)
            self.assertEqual(r["watch"], [], text)

    def test_unrelated_km_ignored(self):
        r = run("Rozrząd wymieniony przy 90 000 km.", km=100000)
        self.assertIsNone(r["reject"])
        self.assertEqual(r["watch"], [])


class EquipmentTest(unittest.TestCase):
    def test_equipment_from_keys(self):
        r = run(keys=("rear_view_camera", "park_distance_control_rear", "apple_carplay"))
        self.assertEqual(r["equipment"], {"ac": 1, "cam": 1, "pdc": 1, "cp": 1})

    def test_equipment_from_description(self):
        r = run("Kamera cofania, czujniki parkowania przód i tył, Apple CarPlay.")
        self.assertEqual(r["equipment"], {"ac": 1, "cam": 1, "pdc": 1, "cp": 1})

    def test_sensors_front_and_rear(self):
        self.assertEqual(run("Czujniki przód i tył, tempomat.")["equipment"]["pdc"], 1)

    def test_rain_sensor_is_not_parking_sensor(self):
        self.assertEqual(run("Czujnik deszczu i zmierzchu.")["equipment"]["pdc"], 0)

    def test_android_auto_only_is_ask(self):
        r = run(keys=("android_auto",))
        self.assertEqual(r["equipment"]["cp"], 2)
        self.assertTrue(any("CarPlay" in w for w in r["watch"]))

    def test_facts_and_plus(self):
        details = {"country_origin": "Polska", "original_owner": "Tak", "service_record": "Tak",
                   "no_accident": "Tak", "vin": "", "body_type": "Kombi"}
        r = run(details=details)
        self.assertEqual(r["facts"], {"salonPL": True, "firstOwner": True, "aso": True, "noAccident": True,
                                      "origin": "Polska", "originFrom": "ogłoszenie", "hasVin": True})
        self.assertEqual(r["body"], "kombi")
        self.assertEqual(r["plus"][:4], ["polski salon", "pierwszy właściciel", "serwis w ASO", "bezwypadkowy"])
        self.assertIn("klima dwustrefowa", r["plus"])

    def test_salon_pl_from_description_when_param_missing(self):
        for text in ("Salon Polska, pierwszy właściciel.", "Auto z polskiego salonu.", "Polski salon, serwis ASO.", "SALON PL"):
            facts = run(text)["facts"]
            self.assertEqual((facts["salonPL"], facts["origin"], facts["originFrom"]), (True, "Polska", "opis"), text)

    def test_param_origin_wins_over_description(self):
        facts = run("Salon Polska.", details={"country_origin": "Niemcy"})["facts"]
        self.assertEqual((facts["salonPL"], facts["origin"], facts["originFrom"]), (False, "Niemcy", "ogłoszenie"))

    def test_negated_salon_pl_ignored(self):
        self.assertFalse(run("Auto nie z polskiego salonu, sprowadzone.")["facts"]["salonPL"])

    def test_imported_watch(self):
        r = run(details={"country_origin": "Francja"})
        self.assertIn("Auto sprowadzone (kraj pochodzenia: Francja). Poproś o raport historii z zagranicy, np. z Carvertical.", r["watch"])
        self.assertFalse(r["facts"]["salonPL"])


class PendingTest(unittest.TestCase):
    def test_pending_without_details(self):
        r = rules.classify(item(), None, True)
        self.assertTrue(r["pending"])
        self.assertEqual(r["equipment"], {"ac": 1, "cam": 2, "pdc": 2, "cp": 2})
        self.assertEqual(rules.classify(item(), None, False)["equipment"]["ac"], 2)

    def test_pending_still_checks_title_and_mileage(self):
        self.assertIn("Cesja", rules.classify(item(title="Toyota Corolla cesja leasingu"), None, True)["reject"])
        self.assertIn("mały przebieg", rules.classify(item(km=1, year=2019), None, True)["reject"])


class BodyKindTest(unittest.TestCase):
    def test_vans(self):
        for name in ("Toyota ProAce", "Citroën Berlingo", "Volkswagen Caddy", "Fiat Doblo", "Ford Transit Connect",
                     "Peugeot Partner", "Opel Combo", "Mercedes-Benz Citan", "Renault Kangoo"):
            self.assertEqual(rules.body_kind({"name": name, "body": "minivan"}), "van", name)

    def test_minivans(self):
        for name in ("Opel Meriva", "Citroën C4 Picasso", "Fiat 500L", "Renault Scenic", "Ford B-MAX", "Mazda 5"):
            self.assertEqual(rules.body_kind({"name": name, "body": "kompakt"}), "minivan", name)
        self.assertEqual(rules.body_kind({"name": "BMW Seria 2", "body": "minivan"}), "minivan")

    def test_small_and_other(self):
        self.assertEqual(rules.body_kind({"name": "Opel Adam", "body": "auta małe"}), "small")
        self.assertEqual(rules.body_kind({"name": "Citroën C3", "body": "auta miejskie"}), "small")
        self.assertEqual(rules.body_kind({"name": "Opel Astra", "body": "kompakt"}), "other")
        self.assertEqual(rules.body_kind({"name": "Mazda 3", "body": None}), "other")

    def test_van_reject_reason(self):
        self.assertEqual(rules.kind_reject({"name": "Toyota ProAce", "body": "minivan"}), "Dostawczak z szybami, nie dla Sylwii")
        self.assertIsNone(rules.kind_reject({"name": "Opel Meriva", "body": "kompakt"}))


class CriteriaTest(unittest.TestCase):
    def test_soft_out(self):
        self.assertIn("30 000", rules.soft_out(item(price=30900)))
        self.assertIn("120 000", rules.soft_out(item(fuel="hev", km=156000)))
        self.assertIsNone(rules.soft_out(item(price=29999, km=119000)))

    def test_hard_ok_adam_needs_85hp(self):
        adam = dict(make="opel", model="adam", fuel="pb", cc=1398)
        self.assertFalse(rules.hard_ok(item(hp=70, **adam)))
        self.assertTrue(rules.hard_ok(item(hp=87, **adam)))
        self.assertTrue(rules.hard_ok(item(hp=100, **adam)))
        self.assertFalse(rules.hard_ok(item(make="opel", model="corsa", fuel="pb", hp=100)))

    def test_hard_ok_diesel_cc(self):
        self.assertTrue(rules.hard_ok(item(cc=1598)))
        self.assertFalse(rules.hard_ok(item(cc=1995)))

    def test_hard_ok_limits(self):
        self.assertFalse(rules.hard_ok(item(year=2010)))
        self.assertFalse(rules.hard_ok(item(hp=90)))
        self.assertFalse(rules.hard_ok(item(price=31001)))
        self.assertFalse(rules.hard_ok(item(km=126000)))
        self.assertTrue(rules.hard_ok(item(fuel="hev", km=159000)))
        self.assertFalse(rules.hard_ok(item(fuel="other")))


if __name__ == "__main__":
    unittest.main()
