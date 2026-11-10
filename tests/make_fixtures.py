"""Builds small, anonymised test fixtures from saved Otomoto pages.

Usage: python3 tests/make_fixtures.py <saved_list.html> <saved_ad.html>

Keeps only the keys the parser reads. Seller names, the listing description
and registration data are replaced, so the public repo holds no personal data.
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).parent / "fixtures"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
WRAP = '<!doctype html><html><body><script id="__NEXT_DATA__" type="application/json" nonce="t">{}</script></body></html>\n'

SYNTHETIC_DESCRIPTION = (
    "<p>Zadbany egzemplarz, bezwypadkowy.</p>"
    "<p>Dwustrefowa automatyczna klimatyzacja</p>"
    "<p>Czujniki parkowania</p>"
    "<p>Przebieg 87 000 km, rozrząd wymieniony przy 60 000 km.</p>"
)


def next_data(path):
    return json.loads(NEXT_RE.search(Path(path).read_text()).group(1))


def trim_list(src):
    data = next_data(src)
    for value in data["props"]["pageProps"]["urqlState"].values():
        inner = value.get("data")
        inner = json.loads(inner) if isinstance(inner, str) else inner
        if inner and "advertSearch" in inner:
            search = inner["advertSearch"]
            keep = ("id", "title", "url", "location", "price", "parameters", "seller")
            edges = [{"node": {k: e["node"].get(k) for k in keep}} for e in search["edges"]]
            trimmed = {"advertSearch": {"totalCount": search["totalCount"], "pageInfo": search["pageInfo"], "edges": edges}}
            state = {"k1": {"data": json.dumps(trimmed, ensure_ascii=False)}}
            return {"props": {"pageProps": {"urqlState": state}}}
    raise SystemExit("no advertSearch in list page")


def trim_ad(src):
    advert = next_data(src)["props"]["pageProps"]["advert"]
    details = []
    for d in advert["details"]:
        if d.get("key") in ("date_registration", "registration"):
            continue
        details.append({"key": d["key"], "label": d.get("label"), "value": d.get("value")})
    seller = advert["seller"]
    out = {
        "id": advert["id"],
        "status": advert["status"],
        "title": advert["title"],
        "url": advert["url"],
        "price": advert["price"],
        "description": SYNTHETIC_DESCRIPTION,
        "seller": {"type": seller["type"], "name": "Sprzedający", "location": {"city": seller["location"]["city"], "region": seller["location"]["region"]}},
        "equipment": advert["equipment"],
        "details": details,
    }
    return {"props": {"pageProps": {"advert": out}}}


def main(list_src, ad_src):
    OUT.mkdir(exist_ok=True)
    (OUT / "otomoto_list.html").write_text(WRAP.format(json.dumps(trim_list(list_src), ensure_ascii=False)))
    (OUT / "otomoto_ad.html").write_text(WRAP.format(json.dumps(trim_ad(ad_src), ensure_ascii=False)))


if __name__ == "__main__":
    main(*sys.argv[1:3])
