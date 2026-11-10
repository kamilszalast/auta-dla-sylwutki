"""Builders for test data. Values are spelled out per test where they matter."""


def item(**kw):
    base = dict(otoId="1", url="https://www.otomoto.pl/osobowe/oferta/opel-astra-ID1.html", title="Opel Astra",
                make="opel", model="astra", name="Opel Astra", version="1.6 CDTI", year=2017, km=100000,
                hp=110, cc=1598, fuel="on", gear="manualna", price=28000, city="Rzeszów",
                region="Podkarpackie", seller="prywatnie", origin=None, photo=None)
    base.update(kw)
    return base


def ad(description="", label=None, keys=(), details=None, status="ACTIVE", price=28000):
    eq = set(keys)
    if label:
        eq.add("air_conditioning_type")
    return dict(status=status, price=price, equipment_keys=eq, ac_label=label,
                details=details or {}, description=description)


AUTO_LABEL = "Klimatyzacja automatyczna: dwustrefowa"
