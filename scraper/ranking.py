"""Score and "Polecane 3" (HANDOFF.md §8). Rules only, no LLM."""
from . import config, rules

EQUIP_POINTS = {"cam": 12, "pdc": 8, "cp": 12}
FACT_POINTS = {"salonPL": 15, "firstOwner": 6, "aso": 6, "noAccident": 4}
DIVERSE = ("lpg", "hev", "pb")
DIVERSITY_GAP = 6


def score(car):
    eq, facts = car["equipment"], car["facts"]
    s = sum(p for k, p in EQUIP_POINTS.items() if eq.get(k) == 1)
    s += 3 if eq.get("cp") == 2 else 0
    s += 5 if eq.get("ac") == 1 else 0
    s -= 4 * sum(1 for v in eq.values() if v == 2)
    s += sum(p for k, p in FACT_POINTS.items() if facts.get(k))
    s += 8 if car.get("seller") == "prywatnie" else 0  # Kamil: Polish origin and private seller first
    kind = rules.body_kind(car)
    s += {"small": 6, "minivan": -6}.get(kind, 0)  # Sylwia wants a small car
    s += (car["year"] - config.YEAR_MIN) * 2
    s += (config.KM_SOFT - min(car["km"], config.KM_SOFT)) / 10000
    s -= 3 if car["price"] > 29000 else 0
    s -= 3 if car["km"] > 110000 else 0
    return int(round(s))


def _eligible(car):
    # Polish origin and private seller are score bonuses (Kamil, 10.11); vans and minivans never get recommended
    return (car.get("status") == "active" and not car.get("reject") and not car.get("out")
            and not car.get("pending") and not car.get("manual")
            and rules.body_kind(car) not in ("van", "minivan"))


def _model(car):
    return (car.get("make"), car.get("model")) if car.get("model") else car.get("name")


def why_text(car):
    eq = car["equipment"]
    have = [name for key, name in (("cam", "kamera"), ("pdc", "czujniki"), ("cp", "CarPlay")) if eq.get(key) == 1]
    parts = []  # salon/owner/ASO facts are already in "plus", so "why" names the rest
    if len(have) == 3:
        parts.append("pełne wyposażenie: kamera, czujniki i CarPlay")
    elif have:
        parts.append(" i ".join(have))
    parts.append({"lpg": "gaz, czyli tani kilometr w mieście", "hev": "hybryda, dobra do korków",
                  "pb": "mały Opel Adam, łatwy do parkowania"}.get(car["fuel"], ""))
    if car["year"] >= 2018:
        parts.append("młody rocznik")
    if car["km"] < 80000:
        parts.append("mały przebieg")
    parts = [p for p in parts if p]
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] + "." if text else None


def pick_top(cars, pins):
    by_id = {c["id"]: c for c in cars}
    for c in cars:
        c["top"] = None
        if "why" not in (c.get("byKamil") or []):
            c["why"] = None

    slots = {}
    for cid, rank in sorted(pins.items(), key=lambda x: x[1]):
        if cid in by_id and rank in (1, 2, 3) and rank not in slots and by_id[cid].get("status") == "active":
            slots[rank] = by_id[cid]
    pinned = {c["id"] for c in slots.values()}
    pool = sorted((c for c in cars if _eligible(c) and c["id"] not in pinned), key=lambda c: -c["score"])
    free = [r for r in (1, 2, 3) if r not in slots]
    models = {_model(c) for c in slots.values()}
    auto, rest = [], []
    for c in pool:  # no two cars of the same model in the top three
        if len(auto) < len(free) and _model(c) not in models:
            auto.append(c)
            models.add(_model(c))
        else:
            rest.append(c)

    if auto and not any(c["fuel"] in DIVERSE for c in list(slots.values()) + auto):
        taken = {_model(c) for c in list(slots.values()) + auto[:-1]}
        alt = next((c for c in rest if c["fuel"] in DIVERSE and _model(c) not in taken), None)
        if alt and len(auto) == len(free) and alt["score"] >= auto[-1]["score"] - DIVERSITY_GAP:
            auto[-1] = alt

    for rank, c in zip(free, auto):
        slots[rank] = c
    for rank, c in slots.items():
        c["top"] = rank
        if "why" not in (c.get("byKamil") or []):
            c["why"] = why_text(c)
