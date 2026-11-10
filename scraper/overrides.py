"""data/overrides.json: Kamil's manual corrections. Read only, never written."""
import json
from datetime import date, timedelta
from pathlib import Path

from . import config

NOTE_FIELDS = ("plus", "watch", "why")
NO_FACTS = {"salonPL": False, "firstOwner": False, "aso": False, "noAccident": False, "origin": None, "hasVin": False}


def load(path):
    path = Path(path)
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("główny element musi być obiektem {}")
        return data, None
    except ValueError as e:
        return {}, "overrides.json ma błąd i został pominięty: %s" % e


def _index(cars):
    idx = {}
    for c in cars:
        idx[c["id"]] = c
        if (c.get("links") or {}).get("otomoto"):
            idx[c["links"]["otomoto"]] = c
    return idx


def _reset(car):
    auto = car.get("auto")
    if not auto:
        return
    car["equipment"] = dict(auto["equipment"])
    car["plus"], car["watch"], car["reject"] = auto.get("plus"), auto.get("watch"), auto.get("reject")
    car["why"] = None
    car["byKamil"] = []


def _mark(car, field):
    if field not in car["byKamil"]:
        car["byKamil"].append(field)


def _manual(entry, today):
    checked = entry["checked"]
    expires = date.fromisoformat(checked) + timedelta(days=config.MANUAL_DAYS)
    gone = date.fromisoformat(today) > expires
    note = "Ogłoszenie tylko na OLX, sprawdzone ręcznie %s. Mogło się zmienić." % date.fromisoformat(checked).strftime("%d.%m.%Y")
    watch = " ".join(x for x in (entry.get("watch"), note) if x)
    car = {
        "id": entry["id"], "links": {"otomoto": None, "olx": entry.get("olx")},
        "name": entry["name"], "version": None, "engine": entry["engine"], "fuel": entry["fuel"],
        "gear": entry["gear"], "body": entry.get("body"), "year": entry["year"], "km": entry["km"],
        "hp": None, "cc": None, "price": entry["price"], "city": entry["city"], "region": entry.get("region", ""),
        "seller": entry["seller"], "equipment": dict(entry["equipment"]), "facts": dict(NO_FACTS),
        "out": None, "plus": entry.get("plus"), "watch": watch, "why": None, "score": 0, "top": None,
        "reject": None, "pending": False, "detailed": True, "inAc": False, "manual": True,
        "byKamil": [f for f in ("plus", "watch") if entry.get(f)],
        "firstSeen": checked, "lastSeen": checked, "shownSince": checked,
        "status": "gone" if gone else "active", "goneSince": expires.isoformat() if gone else None,
    }
    return car


MANUAL_KEYS = ("id", "name", "engine", "fuel", "gear", "year", "km", "price", "city", "seller", "equipment", "checked")


def _bad(errors, what, value):
    errors.append("overrides.json: pominięto %s: %s" % (what, json.dumps(value, ensure_ascii=False)[:120]))


def apply(cars, ov, today, errors=None):
    errors = [] if errors is None else errors
    for c in cars:
        _reset(c)
    idx = _index(cars)
    for rule in ov.get("exclude") or []:
        if not isinstance(rule, dict) or not rule.get("key"):
            _bad(errors, "wpis w exclude", rule)
            continue
        car = idx.get(rule["key"])
        if car:
            car["reject"] = "Kamil: " + str(rule.get("reason") or "wykluczone ręcznie")
            _mark(car, "reject")
    for key, note in (ov.get("notes") or {}).items():
        if not isinstance(note, dict):
            _bad(errors, "wpis w notes", {key: note})
            continue
        car = idx.get(key)
        if not car:
            continue
        for field in NOTE_FIELDS:
            if note.get(field):
                car[field] = str(note[field])
                _mark(car, field)
        if str(note.get("olx") or "").startswith("https://"):
            car["links"]["olx"] = note["olx"]
    for key, values in (ov.get("equipment") or {}).items():
        car = idx.get(key)
        if car and isinstance(values, dict):
            car["equipment"].update({k: v for k, v in values.items() if k in car["equipment"] and v in (0, 1, 2)})
            _mark(car, "equipment")
    manual = []
    for entry in ov.get("manual") or []:
        try:
            if not isinstance(entry, dict) or any(k not in entry for k in MANUAL_KEYS):
                raise ValueError("brakuje pól")
            manual.append(_manual(entry, today))
        except (ValueError, TypeError, AttributeError):
            _bad(errors, "wpis w manual (wymagane pola: %s, data RRRR-MM-DD)" % ", ".join(MANUAL_KEYS), entry)
    return cars + manual


def pins(cars, ov):
    idx = _index(cars)
    return {idx[k]["id"]: rank for k, rank in (ov.get("pin") or {}).items() if k in idx and rank in (1, 2, 3)}
