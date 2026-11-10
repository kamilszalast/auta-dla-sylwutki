"""Otomoto search URLs and parsers for the __NEXT_DATA__ JSON in pages."""
import html
import json
import re
import urllib.parse

from . import config

NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def search_url(query, with_ac, page):
    params = dict(query["params"])
    if with_ac:
        params.update(config.AC_PARAMS)
    if page > 1:
        params["page"] = page
    return config.BASE + query["path"] + "?" + urllib.parse.urlencode(params)


def _next_data(page):
    m = NEXT_RE.search(page)
    if not m:
        raise ValueError("brak danych __NEXT_DATA__ na stronie")
    return json.loads(m.group(1))


def _int(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def parse_list(page):
    state = _next_data(page)["props"]["pageProps"].get("urqlState") or {}
    for value in state.values():
        data = value.get("data")
        data = json.loads(data) if isinstance(data, str) else data
        if data and "advertSearch" in data:
            search = data["advertSearch"]
            return search["totalCount"], [_item(e["node"]) for e in search["edges"]]
    raise ValueError("brak wyników wyszukiwania na stronie")


def _item(node):
    params = {p["key"]: p for p in node.get("parameters") or []}

    def val(key):
        return (params.get(key) or {}).get("value")

    def disp(key):
        return (params.get(key) or {}).get("displayValue")

    location = node.get("location") or {}
    seller = (node.get("seller") or {}).get("__typename")
    return {
        "otoId": str(node["id"]),
        "url": node["url"],
        "title": node.get("title") or "",
        "make": val("make"),
        "model": val("model"),
        "name": " ".join(x for x in (disp("make"), disp("model")) if x),
        "version": disp("version"),
        "year": _int(val("year")),
        "km": _int(val("mileage")),
        "hp": _int(val("engine_power")),
        "cc": _int(val("engine_capacity")),
        "fuel": config.FUEL_MAP.get(val("fuel_type"), "other"),
        "gear": config.GEAR_MAP.get(val("gearbox"), disp("gearbox") or ""),
        "price": _int(((node.get("price") or {}).get("amount") or {}).get("units")),
        "city": ((location.get("city") or {}).get("name")) or "",
        "region": ((location.get("region") or {}).get("name")) or "",
        "seller": "prywatnie" if seller == "PrivateSeller" else "komis",
        "origin": disp("country_origin"),
    }


def _text(fragment):
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", fragment or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def parse_ad(page):
    advert = _next_data(page)["props"]["pageProps"].get("advert")
    if not advert:
        raise ValueError("brak danych ogłoszenia na stronie")
    keys, ac_label = set(), None
    for group in advert.get("equipment") or []:
        for v in group.get("values") or []:
            keys.add(v.get("key"))
            if v.get("key") == "air_conditioning_type":
                ac_label = v.get("label")
    details = {d["key"]: d.get("value") or "" for d in advert.get("details") or [] if d.get("key")}
    return {
        "status": advert.get("status"),
        "price": _int((advert.get("price") or {}).get("value")),
        "equipment_keys": keys,
        "ac_label": ac_label,
        "details": details,
        "description": _text(advert.get("description")),
    }
