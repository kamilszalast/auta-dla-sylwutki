"""Search settings. Values come from HANDOFF.md §5–6 and AUTOMAT.md."""

BASE = "https://www.otomoto.pl"
PAGE_SIZE = 32

PRICE_MIN = 5000
PRICE_MAX = 31000          # hard limit (30 000 zł budget + negotiation room)
BUDGET = 30000             # above this: "Poza kryteriami"
KM_MAX = 125000            # hard limit for search
KM_MAX_HYBRID = 160000
KM_SOFT = 120000           # above this: "Poza kryteriami"
YEAR_MIN = 2011
HP_MIN = 91
HP_MIN_ADAM = 85            # Kamil 10.11: 1.4 87 KM is fine, 1.2 70 KM is not
DIESEL_CC_MAX = 1600
LOW_KM = 15000             # below this with year <= LOW_KM_YEAR: suspicious
LOW_KM_YEAR = 2020

DETAIL_LIMIT = 100
DETAIL_BUDGET_S = 20 * 60   # stop fetching listings after this, publish what we have
MAX_FAILURES_IN_ROW = 3
DELAY = (3, 6)
TIMEZONE = "Europe/Warsaw"
GONE_DROP_DAYS = 30
MANUAL_DAYS = 14

AC_PARAMS = {
    "search[filter_enum_air_conditioning_type][0]": "automatic-climate-control",
    "search[filter_enum_air_conditioning_type][1]": "dualzone-automatic-climate-control",
    "search[filter_enum_air_conditioning_type][2]": "trizone-automatic-climate-control",
}

_COMMON = {
    "search[filter_float_price:from]": PRICE_MIN,
    "search[filter_float_price:to]": PRICE_MAX,
    "search[filter_enum_damaged]": 0,
    "search[order]": "filter_float_mileage:asc",
}

QUERIES = [
    {"key": "on", "path": "/osobowe/od-2011", "params": dict(_COMMON, **{
        "search[filter_enum_fuel_type]": "diesel",
        "search[filter_float_engine_capacity:to]": DIESEL_CC_MAX,
        "search[filter_float_mileage:to]": KM_MAX,
        "search[filter_float_engine_power:from]": HP_MIN})},
    {"key": "lpg", "path": "/osobowe/od-2011", "params": dict(_COMMON, **{
        "search[filter_enum_fuel_type]": "petrol-lpg",
        "search[filter_float_mileage:to]": KM_MAX,
        "search[filter_float_engine_power:from]": HP_MIN})},
    {"key": "hev", "path": "/osobowe/od-2011", "params": dict(_COMMON, **{
        "search[filter_enum_fuel_type]": "hybrid",
        "search[filter_float_mileage:to]": KM_MAX_HYBRID,
        "search[filter_float_engine_power:from]": HP_MIN})},
    {"key": "pb", "path": "/osobowe/opel/adam/od-2011", "params": dict(_COMMON, **{
        "search[filter_float_mileage:to]": KM_MAX,
        "search[filter_float_engine_power:from]": HP_MIN_ADAM})},
]

FUEL_MAP = {"diesel": "on", "petrol-lpg": "lpg", "hybrid": "hev", "plugin-hybrid": "hev", "petrol": "pb"}
GEAR_MAP = {"manual": "manualna", "automatic": "automat"}
