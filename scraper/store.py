"""data/offers.json: create, merge with today's search results, mark gone."""
import json
from datetime import date
from pathlib import Path

from . import config

LIST_FIELDS = ("price", "km", "city", "region", "seller", "photo")


def load(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _engine(item):
    cc = "%.1f" % (item["cc"] / 1000) if item.get("cc") else None
    return ", ".join(x for x in (cc, "%s KM" % item["hp"]) if x)


def car_from_item(item, today):
    return {
        "id": "otomoto:" + item["otoId"],
        "links": {"otomoto": item["url"], "olx": None},
        "name": item["name"], "version": item.get("version"), "engine": _engine(item),
        "fuel": item["fuel"], "gear": item["gear"], "body": None,
        "year": item["year"], "km": item["km"], "hp": item["hp"], "cc": item.get("cc"),
        "price": item["price"], "city": item["city"], "region": item["region"], "seller": item["seller"],
        "make": item.get("make"), "model": item.get("model"), "title": item.get("title"), "origin": item.get("origin"),
        "photo": item.get("photo"),
        "equipment": {"ac": 2, "cam": 2, "pdc": 2, "cp": 2}, "facts": None,
        "out": None, "plus": None, "watch": None, "why": None, "score": 0, "top": None,
        "reject": None, "pending": True, "detailed": False, "inAc": bool(item.get("inAc")),
        "manual": False, "byKamil": [],
        "firstSeen": today, "lastSeen": today, "status": "active", "goneSince": None,
    }


def merge(existing, seen, today, lists_complete):
    cars, new_ids, done = [], [], set()
    today_d = date.fromisoformat(today)
    for car in existing:
        if car.get("manual"):
            continue
        hit = seen.get(car["id"])
        if hit:
            for f in LIST_FIELDS:
                car[f] = hit[f]
            car.update(lastSeen=today, status="active", goneSince=None, inAc=car.get("inAc") or bool(hit.get("inAc")))
            done.add(car["id"])
        elif lists_complete and car["status"] == "active":
            car.update(status="gone", goneSince=today)
        if car["status"] == "gone" and car.get("goneSince"):
            if (today_d - date.fromisoformat(car["goneSince"])).days > config.GONE_DROP_DAYS:
                continue
        cars.append(car)
    for cid, item in seen.items():
        if cid not in done:
            cars.append(car_from_item(item, today))
            new_ids.append(cid)
    return cars, new_ids
