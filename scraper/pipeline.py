"""One daily run: search lists, fetch new listings, apply rules and overrides, write data/."""
import math
from datetime import datetime
from pathlib import Path

from . import config, otomoto, overrides, ranking, rules, store
from .http import Blocked, FetchError, NotFound

LABELS = {"on": "diesel", "lpg": "gaz", "hev": "hybryda", "pb": "Opel Adam"}
OLX_STATUS = "zablokowane dla automatu (403), sprawdzaj ręcznie"
MAX_PAGES = 20


def visible(car):
    return car["status"] == "active" and not car.get("reject") and (car.get("detailed") or car.get("inAc"))


def _sentence(parts):
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] + "." if text else None


def _search(fetcher, errors):
    """Returns (seen, lists_complete, any_ok)."""
    seen, complete, any_ok = {}, True, False
    for query in config.QUERIES:
        for with_ac in (True, False):
            label = LABELS[query["key"]] + (" z klimą automatyczną" if with_ac else "")
            page, pages = 1, 1
            while page <= pages:
                try:
                    total, items = otomoto.parse_list(fetcher.get(otomoto.search_url(query, with_ac, page)))
                except Blocked as e:
                    errors.append("Otomoto zablokowało wyszukiwanie (%s): %s" % (label, e))
                    return seen, False, any_ok
                except (FetchError, ValueError) as e:
                    errors.append("Otomoto, %s, strona %d: %s" % (label, page, e))
                    complete = False
                    break
                any_ok = True
                pages = min(MAX_PAGES, math.ceil(total / config.PAGE_SIZE))
                for item in items:
                    if rules.hard_ok(item):
                        cid = "otomoto:" + item["otoId"]
                        prev = seen.get(cid)
                        seen[cid] = dict(item, inAc=with_ac or bool(prev and prev["inAc"]))
                if not items:
                    break
                page += 1
    return seen, complete, any_ok


def _store_classification(car, result):
    car["facts"], car["pending"] = result["facts"], result["pending"]
    if result["body"]:
        car["body"] = result["body"]
    car["auto"] = {"equipment": result["equipment"], "plus": _sentence(result["plus"]),
                   "watch": " ".join(result["watch"]) or None, "reject": result["reject"]}


def _details(cars, fetcher, today, limit, errors):
    queue = []
    for car in cars:
        if car["status"] != "active" or car.get("detailed") or car.get("manual"):
            continue
        _store_classification(car, rules.classify(car, None, car.get("inAc")))
        if not car["auto"]["reject"]:
            queue.append(car)
    queue.sort(key=lambda c: (not c.get("inAc"), -c["year"], c["km"]))
    failed = 0
    for car in queue[:limit]:
        try:
            ad = otomoto.parse_ad(fetcher.get(car["links"]["otomoto"]))
        except NotFound:
            car.update(status="gone", goneSince=today)
            continue
        except Blocked as e:
            errors.append("Otomoto zablokowało pobieranie ogłoszeń (%s). Reszta przy następnej aktualizacji." % e)
            break
        except (FetchError, ValueError):
            failed += 1
            continue
        if ad["status"] != "ACTIVE":
            car.update(status="gone", goneSince=today)
            continue
        if ad["price"]:
            car["price"] = ad["price"]
        _store_classification(car, rules.classify(car, ad, car.get("inAc")))
        car.update(detailed=True, detailedAt=today)
    if failed:
        errors.append("Nie udało się pobrać %d ogłoszeń. Spróbuję przy następnej aktualizacji." % failed)


def run(root, fetcher, now, ran_by, detail_limit, force):
    data = Path(root) / "data"
    offers_path, meta_path = data / "offers.json", data / "meta.json"
    meta = store.load(meta_path, {})
    today = now.date().isoformat()
    if not force and (meta.get("lastRun") or "")[:10] == today:
        print("Dzisiejsze dane już są (%s, %s). Koniec bez zmian." % (meta["lastRun"], meta.get("ranBy")))
        return 0

    stamp = now.isoformat(timespec="seconds")
    errors = []
    seen, complete, any_ok = _search(fetcher, errors)
    if not any_ok:
        meta.update(lastAttempt=stamp, errors=errors[:20],
                    sources={"otomoto": "błąd", "olx": OLX_STATUS})
        store.save_json(meta_path, meta)
        print("Otomoto nie odpowiedziało. Zostają dane z poprzedniej aktualizacji.\n" + "\n".join(errors))
        return 1

    cars, _ = store.merge(store.load(offers_path, []), seen, today, complete)
    _details(cars, fetcher, today, detail_limit, errors)

    ov, ov_error = overrides.load(data / "overrides.json")
    if ov_error:
        errors.append(ov_error)
    cars = overrides.apply(cars, ov, today)
    for car in cars:
        car["out"] = rules.soft_out(car)
        car["score"] = ranking.score(car)
    ranking.pick_top(cars, overrides.pins(cars, ov))
    for car in cars:
        if visible(car) and not car.get("shownSince"):
            car["shownSince"] = today
    cars.sort(key=lambda c: (c["status"] != "active", bool(c.get("reject")), c.get("top") or 9, -c["score"]))

    active = [c for c in cars if c["status"] == "active"]
    meta = {
        "lastRun": stamp, "lastAttempt": stamp, "ranBy": ran_by,
        "newCount": sum(1 for c in active if visible(c) and c.get("shownSince") == today),
        "activeCount": sum(1 for c in active if visible(c)),
        "rejectedCount": sum(1 for c in active if c.get("reject")),
        "pendingDetails": sum(1 for c in active if not c.get("detailed") and not c.get("manual") and not c.get("reject")),
        "sources": {"otomoto": "ok" if not errors else "częściowo", "olx": OLX_STATUS},
        "errors": errors[:20],
    }
    store.save_json(offers_path, cars)
    store.save_json(meta_path, meta)
    print("Aktualizacja %s: %d aut na stronie, nowe: %d, odrzucone: %d, czeka na szczegóły: %d."
          % (stamp, meta["activeCount"], meta["newCount"], meta["rejectedCount"], meta["pendingDetails"]))
    for e in errors:
        print("Uwaga: " + e)
    return 0
