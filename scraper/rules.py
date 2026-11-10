"""Criteria, red flags and equipment rules (HANDOFF.md §5, §7; AUTOMAT.md)."""
import re

from . import config

AUTO_AC = re.compile(r"klimatroni|climatroni|clima?tronic|klimatyzacja automat|automatyczn\w* klim|klima automat|"
                     r"klimatyzacja (dwu|2)[- ]?strefow|dwustrefow|2[- ]strefow|climate control|klima auto", re.I)
ANY_AC = re.compile(r"klim", re.I)
CAMERA = re.compile(r"kamer", re.I)
SENSORS = re.compile(r"czujnik\w*\s+(parkowania|cofania|odległości|park|przód|przod|tył|tyl|z przodu|z tyłu)|parktroni|\bpdc\b|park ?distance|park ?assist", re.I)
CARPLAY = re.compile(r"car ?play", re.I)
ANDROID_AUTO = re.compile(r"android ?auto", re.I)
CESJA = re.compile(r"cesj|odstępne|odstepne", re.I)
DAMAGE = re.compile(r"uszkodz|powypadk|poobijan", re.I)
REPAIR = re.compile(r"do naprawy", re.I)
NEGATION = re.compile(r"(\bnie\b|\bnic\b|\bbez\b|\bbrak\w*|\bżadn\w*|\bzero\b|\bwoln\w* od\b)", re.I)
SENTENCE_END = re.compile(r"[.!?\n]")
SERVICE_CONTEXT = re.compile(r"\b(przy|do|co|od|po|na)\s+$", re.I)
NEGATION_WINDOW = 60
RULES_VERSION = 3
SALON_PL = re.compile(r"salon\w*[\s:,-]*(pl\b|polsk)|polsk\w*\s+salon", re.I)
MILEAGE = re.compile(r"przebieg\w*[^0-9\n]{0,25}?(\d{1,3}(?:[  .]\d{3})+|\d+)\s*(tys|km|kilometr)", re.I)


def nb(n):
    return "{:,}".format(n).replace(",", " ")


def _found(pattern, text):
    """First match of pattern that is not negated by the words just before it."""
    for m in pattern.finditer(text):
        before = text[max(0, m.start() - NEGATION_WINDOW):m.start()]
        before = SENTENCE_END.split(before)[-1]
        if not NEGATION.search(before):
            return m
    return None


VAN = re.compile(r"proace|berlingo|partner|rifter|caddy|dobl[oò]|kangoo|combo|tourneo|transit|citan|dokker|nemo|"
                 r"bipper|qubo|fiorino|vito|traveller|jumpy|expert|trafic|vivaro|townstar|multivan|transporter", re.I)
MINIVAN = re.compile(r"meriva|picasso|spacetourer|zafira|touran|sharan|scenic|espace|b-max|c-max|s-max|galaxy|500l|"
                     r"verso|carens|venga|ix20|\bnote\b|sportsvan|golf plus|alhambra|lodgy|mazda 5\b|active tourer|gran tourer", re.I)
SMALL_BODIES = ("auta małe", "auta miejskie")
VAN_REASON = "Dostawczak z szybami, nie dla Sylwii"


NO_AC_NOTE = "W ogłoszeniu nie ma słowa o klimatyzacji. Dopytaj."
OLD_PLAIN_AC_NOTE = "W ogłoszeniu sama „klimatyzacja”. Dopytaj, czy jest automatyczna."


def migrate_ac(auto):
    """Rewrites a stored classification from the time automatic AC was required (before 10.11 evening)."""
    if not auto:
        return
    eq = auto["equipment"]
    if auto.get("reject") == "Klimatyzacja manualna":
        auto["reject"], eq["ac"] = None, 3
        auto["plus"] = (auto["plus"][:-1] + ", klima manualna." if auto.get("plus") else "Klima manualna.")
    elif auto.get("reject") == "Brak klimy automatycznej w ogłoszeniu":
        auto["reject"], eq["ac"] = None, 2
        auto["watch"] = " ".join(x for x in (auto.get("watch"), NO_AC_NOTE) if x)
    if OLD_PLAIN_AC_NOTE in (auto.get("watch") or ""):
        auto["watch"] = auto["watch"].replace(OLD_PLAIN_AC_NOTE, "").strip() or None
        eq["ac"] = 3


def body_kind(car):
    """van / minivan / small / other, from the model name first (Otomoto body types are unreliable)."""
    name, body = car.get("name") or "", car.get("body") or ""
    if VAN.search(name):
        return "van"
    if MINIVAN.search(name) or body == "minivan":
        return "minivan"
    return "small" if body in SMALL_BODIES else "other"


def kind_reject(car):
    return VAN_REASON if body_kind(car) == "van" else None


def hard_ok(item):
    fuel, km, price, hp = item.get("fuel"), item.get("km"), item.get("price"), item.get("hp")
    if None in (km, price, hp, item.get("year")):
        return False
    adam = item.get("make") == "opel" and item.get("model") == "adam"
    if item["year"] < config.YEAR_MIN or price > config.PRICE_MAX:
        return False
    if hp < (config.HP_MIN_ADAM if adam else config.HP_MIN):
        return False
    if km > (config.KM_MAX_HYBRID if fuel == "hev" else config.KM_MAX):
        return False
    if fuel == "on":
        return item.get("cc") is not None and item["cc"] <= config.DIESEL_CC_MAX
    if fuel == "pb":
        return adam
    return fuel in ("lpg", "hev")


def soft_out(item):
    parts = []
    if item["price"] > config.BUDGET:
        parts.append("cena %s zł, ponad budżet %s zł, do negocjacji" % (nb(item["price"]), nb(config.BUDGET)))
    if item["km"] > config.KM_SOFT:
        parts.append("przebieg %s km, ponad limit %s km" % (nb(item["km"]), nb(config.KM_SOFT)))
    return "; ".join(parts) or None


def _common_flags(item, text):
    """Rejections that need only the title (and the description when we have it)."""
    if CESJA.search(text):
        return "Cesja leasingu: cena to tylko odstępne"
    if _found(DAMAGE, text):
        return "Uszkodzone według opisu"
    if item["km"] < config.LOW_KM and item["year"] <= config.LOW_KM_YEAR:
        return "Podejrzanie mały przebieg (%s km)" % nb(item["km"])
    return None


def _mileage_check(item, text, watch):
    """Compares the car's mileage stated in the description ("przebieg 93 500 km"),
    skipping service intervals such as "przy przebiegu 150 000 km"."""
    m = next((m for m in MILEAGE.finditer(text) if not SERVICE_CONTEXT.search(text[max(0, m.start() - 8):m.start()])), None)
    if not m:
        return None
    value = int(re.sub(r"\D", "", m.group(1)))
    if m.group(2).lower() == "tys" and value < 1000:
        value *= 1000
    km = item["km"]
    if value > km * 1.03:
        return "Przebieg w opisie (%s km) wyższy niż w ogłoszeniu (%s km)" % (nb(value), nb(km))
    if value < km * 0.97:
        watch.append("W opisie przebieg „%s km”, w ogłoszeniu %s km. Dopytaj, który jest prawdziwy." % (m.group(1), nb(km)))
    return None


def _facts(item, details, text=""):
    origin, source = details.get("country_origin") or item.get("origin"), "ogłoszenie"
    if not origin:
        origin, source = ("Polska", "opis") if _found(SALON_PL, text) else (None, None)
    return {
        "salonPL": origin == "Polska",
        "firstOwner": details.get("original_owner") == "Tak",
        "aso": details.get("service_record") == "Tak",
        "noAccident": details.get("no_accident") == "Tak",
        "origin": origin,
        "originFrom": source,
        "hasVin": "vin" in details,
    }


def _imported(facts, watch):
    if facts["origin"] and facts["origin"] != "Polska":
        watch.append("Auto sprowadzone (kraj pochodzenia: %s). Poproś o raport historii z zagranicy, np. z Carvertical." % facts["origin"])


def classify(item, ad, in_ac_filter):
    watch = []
    if ad is None:
        facts = _facts(item, {}, item.get("title") or "")
        _imported(facts, watch)
        return {"equipment": {"ac": 1 if in_ac_filter else 2, "cam": 2, "pdc": 2, "cp": 2}, "facts": facts,
                "body": None, "reject": _common_flags(item, item.get("title") or ""), "watch": watch,
                "plus": [], "pending": True}

    text = (item.get("title") or "") + "\n" + (ad.get("description") or "")
    keys = ad.get("equipment_keys") or set()
    label = (ad.get("ac_label") or "").lower()
    reject = _common_flags(item, text)

    # ac: 1 automatic, 3 present (manual or type not stated), 2 ask the seller. Kamil 10.11: manual AC is fine.
    auto_label = "automatyczn" in label
    manual_label = "manualn" in label
    if auto_label or (in_ac_filter and not manual_label) or (AUTO_AC.search(text) and not manual_label):
        ac = 1
    elif manual_label or ANY_AC.search(text):
        ac = 3
    else:
        ac = 2
        watch.append(NO_AC_NOTE)

    cam = 1 if any("camera" in k for k in keys) or CAMERA.search(text) else 0
    pdc = 1 if any(k.startswith("park_distance_control") for k in keys) or SENSORS.search(text) else 0
    if "apple_carplay" in keys or CARPLAY.search(text):
        cp = 1
    elif "android_auto" in keys or ANDROID_AUTO.search(text):
        cp = 2
        watch.append("W ogłoszeniu jest tylko Android Auto. Zapytaj, czy działa CarPlay.")
    else:
        cp = 0

    if _found(REPAIR, text):
        watch.append("W opisie jest „do naprawy”. Zapytaj sprzedającego, co trzeba naprawić i ile to kosztuje.")
    reject = reject or _mileage_check(item, text, watch)

    details = ad.get("details") or {}
    facts = _facts(item, details, text)
    _imported(facts, watch)
    plus = [name for flag, name in (("salonPL", "polski salon"), ("firstOwner", "pierwszy właściciel"),
                                     ("aso", "serwis w ASO"), ("noAccident", "bezwypadkowy")) if facts[flag]]
    if auto_label:
        kind = label.split(":", 1)[1].strip() if ":" in label else "automatyczna"
        plus.append("klima " + kind)
    elif manual_label:
        plus.append("klima manualna")
    body = (details.get("body_type") or "").lower() or None
    return {"equipment": {"ac": ac, "cam": cam, "pdc": pdc, "cp": cp}, "facts": facts, "body": body,
            "reject": reject, "watch": watch, "plus": plus, "pending": False}
